"""Command-line interface for IntentFlow.

Commands:

    intentflow parse <file>            print the AST as JSON
    intentflow validate <file>         analyzer diagnostics (--json for machines)
    intentflow lint <file>             advisory diagnostics only (warnings/info)
    intentflow compile <file>          print the execution plan (--out plan.json)
    intentflow inspect <file>          summarize goals, actions, evidence, warnings
    intentflow explain <file>          translate a goal into plain English
    intentflow format <file>           canonically reformat (--check / --write)
    intentflow run <file>              execute (defaults to the simulate backend)
    intentflow replay <trace.json>     readable summary of a saved trace (--json)
    intentflow audit <file> <result>   verify a run's trace against the plan
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path

from intentflow._version import __version__
from intentflow.analyzer import analyze_program, errors_in, warnings_in
from intentflow.auditor import audit_document
from intentflow.backends import BACKENDS, make_backend
from intentflow.compiler import (
    CompileError,
    compile_program,
    inspect_program,
    plan_hash,
    source_hash,
)
from intentflow.explain import explain_program, render_explanation
from intentflow.formatter import format_source
from intentflow.judges import make_judge
from intentflow.parser import ParseError, parse_file
from intentflow.runtime import GoalRuntime, execute_program, run_pipeline
from intentflow.tools import PreGrantedApprover, TTYApprover, WebhookApprover


def _load(path: str):
    try:
        return parse_file(path)
    except FileNotFoundError:
        print(f"error: file not found: {path}", file=sys.stderr)
        raise SystemExit(2)
    except ParseError as exc:
        print(f"parse error: {exc}", file=sys.stderr)
        raise SystemExit(2)


def _compile_or_fail(program) -> dict:
    diagnostics = analyze_program(program)
    errors = errors_in(diagnostics)
    if errors:
        for diag in errors:
            print(diag.render(program.source_name), file=sys.stderr)
        print(f"compile failed: {len(errors)} error(s)", file=sys.stderr)
        raise SystemExit(1)
    try:
        return compile_program(program)
    except CompileError as exc:
        print(f"compile error: {exc}", file=sys.stderr)
        raise SystemExit(1)


def cmd_parse(args: argparse.Namespace) -> int:
    program = _load(args.file)
    print(json.dumps(program.to_dict(), indent=2))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    program = _load(args.file)
    diagnostics = analyze_program(program)
    errors = errors_in(diagnostics)
    warnings = warnings_in(diagnostics)

    if getattr(args, "json", False):
        report = {
            "source": program.source_name,
            "ok": not errors,
            "goals": len(program.goals),
            "error_count": len(errors),
            "warning_count": len(warnings),
            "diagnostics": [d.to_dict() for d in diagnostics],
        }
        print(json.dumps(report, indent=2))
        return 1 if errors else 0

    for diag in diagnostics:
        print(diag.render(program.source_name))
    if errors:
        print(f"validation failed: {len(errors)} error(s)", file=sys.stderr)
        return 1
    print(
        f"OK: {len(program.goals)} goal(s) valid"
        + (f" ({len(warnings)} warning(s))" if warnings else "")
    )
    return 0


def cmd_lint(args: argparse.Namespace) -> int:
    program = _load(args.file)
    diagnostics = [
        d for d in analyze_program(program) if d.severity in ("warning", "info")
    ]
    for diag in diagnostics:
        print(diag.render(program.source_name))
    warnings = [d for d in diagnostics if d.severity == "warning"]
    print(f"lint: {len(warnings)} warning(s), {len(diagnostics) - len(warnings)} info")
    if warnings and args.strict:
        return 1
    return 0


def cmd_compile(args: argparse.Namespace) -> int:
    program = _load(args.file)
    document = _compile_or_fail(program)
    payload = json.dumps(document, indent=2)
    if args.out:
        Path(args.out).write_text(payload + "\n", encoding="utf-8")
        print(f"plan written to {args.out} (plan hash: {plan_hash(document)})")
        return 0
    print(payload)
    return 0


def _write_trace_artifact(
    trace_dir: str, document: dict, result: dict, backend_name: str, program
) -> str:
    """Write a self-contained, inspectable witness of a run to ``trace_dir``.

    The artifact bundles the run result with provenance (source path and
    hash, backend, timestamp, compiled-plan hash) so a third party can later
    replay it with ``intentflow replay`` and verify it with
    ``intentflow audit``."""
    directory = Path(trace_dir)
    directory.mkdir(parents=True, exist_ok=True)
    label = result.get("goal") or result.get("pipeline") or "run"
    trace_id = result.get("trace_id") or plan_hash(result)
    timestamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"{label}-{timestamp}-{trace_id}.json"
    artifact = {
        "artifact": "intentflow-trace",
        "intentflow_version": __version__,
        "trace_id": trace_id,
        "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "source": program.source_name,
        "source_hash": source_hash(program.source_text),
        "plan_hash": plan_hash(document),
        "backend": backend_name,
        "status": result.get("status"),
        "result": result,
    }
    path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    return str(path)


def _print_run_summary(result: dict) -> None:
    summary = result.get("summary")
    if not summary:  # e.g. a pipeline result
        print(f"\nstatus: {result.get('status')}")
        return
    print("\n--- run summary ---")
    print(f"  goal:               {result.get('goal')}")
    print(f"  status:             {result.get('status')}")
    print(f"  backend:            {result.get('backend')}")
    print(f"  confidence:         {summary.get('confidence')}")
    print(f"  verification:       {summary.get('verification_status')}")
    print(f"  uncertainty:        {summary.get('uncertainty_status')}")
    print(f"  actions requested:  {summary.get('actions_requested') or '(none)'}")
    blocked = [b.get("action") for b in summary.get("actions_blocked", [])]
    print(f"  actions blocked:    {blocked or '(none)'}")
    print(f"  trace id:           {summary.get('trace_id')}")
    if result.get("escalations"):
        print("  escalations:")
        for esc in result["escalations"]:
            print(f"    - {esc.get('reason')}")


def _build_approver(args: argparse.Namespace):
    """Pick the approval channel for gated actions (precedence: webhook >
    interactive TTY > pre-granted --approve list)."""
    if args.approve_webhook:
        return WebhookApprover(args.approve_webhook)
    if args.approve_interactive:
        return TTYApprover()
    if args.approve:
        return PreGrantedApprover(set(args.approve))
    return None


def _sign_key(args: argparse.Namespace) -> bytes | None:
    if not args.sign_trace:
        return None
    key = os.environ.get("IFLOW_TRACE_KEY")
    if not key:
        raise RuntimeError("--sign-trace requires the IFLOW_TRACE_KEY environment variable")
    return key.encode("utf-8")


def cmd_run(args: argparse.Namespace) -> int:
    # --simulate is an explicit alias for the default simulate backend.
    backend_name = "simulate" if args.simulate else args.backend
    program = _load(args.file)
    cassette = args.cassette if backend_name == "replay" else args.record_cassette
    try:
        backend = make_backend(backend_name, cassette)
        judge = make_judge(args.judge) if args.judge else None
        sign_key = _sign_key(args)
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    approver = _build_approver(args)
    printer = print if args.verbose else None

    if args.pipeline:
        document = _compile_or_fail(program)
        names = [p["name"] for p in document["pipelines"]]
        if args.pipeline not in names:
            print(
                f"error: pipeline {args.pipeline!r} not found; available: {names}",
                file=sys.stderr,
            )
            return 1
        results = [
            run_pipeline(
                document,
                args.pipeline,
                backend=backend,
                printer=printer,
                workspace=args.workspace,
                approver=approver,
                judge=judge,
                sign_key=sign_key,
            )
        ]
    elif args.goal:
        document = _compile_or_fail(program)
        results = [
            execute_program(
                program,
                args.goal,
                backend=backend,
                printer=printer,
                workspace=args.workspace,
                approver=approver,
                judge=judge,
                sign_key=sign_key,
            )
        ]
    else:
        # Compile up front for the trace artifact, but let execute_program own
        # the analyze/compile phases so failed_validation is a *status*.
        diagnostics = analyze_program(program)
        document = compile_program(program) if not errors_in(diagnostics) else {}
        results = [
            execute_program(
                program,
                goal.name,
                backend=backend,
                printer=printer,
                workspace=args.workspace,
                approver=approver,
                judge=judge,
                sign_key=sign_key,
            )
            for goal in program.goals
        ]
        # Deduplicate: a failed_validation result is identical per goal.
        if results and results[0]["status"] == "failed_validation":
            results = results[:1]

    if args.json:
        payload = results[0] if len(results) == 1 else results
        print(json.dumps(payload, indent=2))
    else:
        for result in results:
            _print_run_summary(result)

    exit_code = 0
    for result in results:
        if result["status"] in ("failed_validation", "failed_verification",
                                "backend_error", "blocked"):
            exit_code = 1
        if result["status"] == "failed_validation" and not args.json:
            for diag in result.get("diagnostics", []):
                if diag["severity"] == "error":
                    print(
                        f"  {diag['severity']}[{diag['code']}]: {diag['message']} "
                        f"(line {diag['line']})",
                        file=sys.stderr,
                    )

    if args.trace_dir:
        for result in results:
            if result["status"] == "failed_validation":
                continue  # nothing executed; no witness to save
            path = _write_trace_artifact(
                args.trace_dir, document, result, backend.name, program
            )
            print(f"\ntrace written to {path}")
            print("  inspect it with 'intentflow replay', verify it with 'intentflow audit'")
    if args.trace_out:
        payload = results[0] if len(results) == 1 else results
        Path(args.trace_out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nresult written to {args.trace_out}")
    return exit_code


def cmd_format(args: argparse.Namespace) -> int:
    path = Path(args.file)
    try:
        original = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"error: file not found: {args.file}", file=sys.stderr)
        return 2
    # Parse first so we never reformat syntactically broken source.
    _load(args.file)
    formatted = format_source(original)

    if args.check:
        if formatted != original:
            print(f"{args.file}: not formatted (run 'intentflow format' to fix)",
                  file=sys.stderr)
            return 1
        print(f"{args.file}: already formatted")
        return 0
    if args.write:
        if formatted != original:
            path.write_text(formatted, encoding="utf-8")
            print(f"{args.file}: reformatted")
        else:
            print(f"{args.file}: already formatted")
        return 0
    sys.stdout.write(formatted)
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    program = _load(args.file)
    report = inspect_program(program)
    if getattr(args, "json", False):
        print(json.dumps(report, indent=2))
        return 0
    print(f"source: {report['source']}")
    for goal in report["goals"]:
        print(f"\ngoal {goal['goal']}")
        print(f"  objective:           {goal['objective'] or '(none)'}")
        print(f"  sections:            {', '.join(goal['sections']) or '(none)'}")
        print(f"  required evidence:   {', '.join(goal['required_evidence']) or '(none)'}")
        print(f"  optional evidence:   {', '.join(goal['optional_evidence']) or '(none)'}")
        print(f"  distrusted evidence: {', '.join(goal['distrusted_evidence']) or '(none)'}")
        print(f"  allowed actions:     {', '.join(goal['allowed_actions']) or '(none)'}")
        print(f"  approval-gated:      {', '.join(goal['approval_gated_actions']) or '(none)'}")
        print(f"  denied actions:      {', '.join(goal['denied_actions']) or '(none)'}")
        print(f"  output fields:       {', '.join(goal['output_fields']) or '(none)'}")
        for d in goal["diagnostics"]:
            position = f"line {d['line']}"
            print(f"  {d['severity']}[{d['code']}]: {d['message']} ({position})")
    for pipeline in report["pipelines"]:
        print(f"\npipeline {pipeline['name']}: {' -> '.join(pipeline['stages'])}")
    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    program = _load(args.file)
    try:
        report = explain_program(program)
    except CompileError as exc:
        print(f"error: cannot explain a goal that does not compile: {exc}",
              file=sys.stderr)
        return 1
    if getattr(args, "json", False):
        print(json.dumps(report, indent=2))
        return 0
    sys.stdout.write(render_explanation(report))
    return 0


def _load_trace_artifact(path: str) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"error: trace file not found: {path}", file=sys.stderr)
        raise SystemExit(2)
    except json.JSONDecodeError as exc:
        print(f"error: trace file is not valid JSON: {exc}", file=sys.stderr)
        raise SystemExit(2)
    return payload


def cmd_replay(args: argparse.Namespace) -> int:
    artifact = _load_trace_artifact(args.trace)
    # Accept both a --trace-dir artifact and a bare --trace-out result.
    result = artifact.get("result", artifact)
    if args.json:
        print(json.dumps(artifact, indent=2))
        return 0

    print("=== IntentFlow trace replay ===")
    if "artifact" in artifact:
        print(f"source:      {artifact.get('source')}")
        print(f"source hash: {artifact.get('source_hash')}")
        print(f"plan hash:   {artifact.get('plan_hash')}")
        print(f"timestamp:   {artifact.get('timestamp')}")
    print(f"goal:        {result.get('goal') or result.get('pipeline')}")
    print(f"backend:     {result.get('backend')}")
    print(f"model:       {result.get('model')}")
    print(f"status:      {result.get('status')}")
    print(f"trace id:    {result.get('trace_id')}")

    phases = result.get("phases", [])
    if phases:
        print("\nphases:")
        for phase in phases:
            detail = f" — {phase['detail']}" if phase.get("detail") else ""
            print(f"  {phase['status']:<9} {phase['name']}{detail}")

    evidence = result.get("evidence", [])
    if evidence:
        print("\nevidence:")
        for item in evidence:
            trust = "" if item.get("trusted", True) else " (distrusted)"
            print(f"  {item['id']}: {item['source']} [{item['origin']}]{trust}")

    verification = result.get("verification", {})
    if verification.get("checks"):
        print("\nverification:")
        for check in verification["checks"]:
            via = f" via {check['judged_by']}" if check.get("judged_by") else ""
            print(f"  {check['id']} [{check['status'].upper()}]{via} {check['rule']}")
            if check.get("note"):
                print(f"      {check['note']}")

    decisions = result.get("uncertainty", {}).get("decisions", [])
    if decisions:
        print("\nuncertainty decisions:")
        for decision in decisions:
            if not decision.get("evaluable"):
                outcome = "not evaluable (recorded)"
            elif decision.get("triggered"):
                outcome = f"TRIGGERED -> {decision['action']}"
            else:
                outcome = "not triggered"
            print(f"  if {decision['condition']}: {outcome}")

    actions = result.get("action_decisions", {})
    if actions:
        print("\naction policy:")
        print(f"  invoked:  {actions.get('invoked') or '(none)'}")
        blocked = [b.get("action") for b in actions.get("blocked", [])]
        print(f"  blocked:  {blocked or '(none)'}")
        print(f"  approved: {actions.get('approved') or '(none)'}")

    escalations = result.get("escalations", [])
    if escalations:
        print("\nescalations:")
        for esc in escalations:
            print(f"  - {esc.get('reason')}: {esc.get('question', esc.get('action', ''))}")

    outputs = result.get("outputs", {})
    if outputs:
        print("\noutputs:")
        for name, value in outputs.items():
            print(f"  {name}: {json.dumps(value)}")

    chain = result.get("trace_chain")
    if chain:
        signed = "signed" if chain.get("signature") else "unsigned"
        print(
            f"\ntrace chain: {chain.get('length')} event(s), root "
            f"{str(chain.get('root'))[:16]}..., {signed}"
        )
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    program = _load(args.file)
    document = _compile_or_fail(program)
    try:
        result = json.loads(Path(args.result).read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"error: result file not found: {args.result}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"error: result file is not valid JSON: {exc}", file=sys.stderr)
        return 2
    # A --trace-dir artifact wraps the run result under "result"; unwrap it so
    # the same audit works on either a --trace-out file or a --trace-dir one.
    if "result" in result and "goal" not in result and "pipeline" not in result:
        result = result["result"]
    # Verify any HMAC trace signature if the same key is available.
    key = os.environ.get("IFLOW_TRACE_KEY")
    sign_key = key.encode("utf-8") if key else None
    report = audit_document(document, result, sign_key)
    print(json.dumps(report, indent=2))
    if report["conformant"]:
        print("AUDIT: CONFORMANT — the trace stayed inside the program's envelope")
        return 0
    print("AUDIT: NONCONFORMANT — see violations above", file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="intentflow",
        description="IntentFlow: a language for governed cognitive processes.",
    )
    parser.add_argument("--version", action="version", version=f"intentflow {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_parse = sub.add_parser("parse", help="parse a .iflow file and print the AST")
    p_parse.add_argument("file")
    p_parse.set_defaults(func=cmd_parse)

    p_validate = sub.add_parser(
        "validate", help="run the static analyzer on a .iflow file"
    )
    p_validate.add_argument("file")
    p_validate.add_argument(
        "--json", action="store_true", help="emit machine-readable JSON diagnostics"
    )
    p_validate.set_defaults(func=cmd_validate)

    p_lint = sub.add_parser(
        "lint", help="advisory diagnostics only (warnings and info)"
    )
    p_lint.add_argument("file")
    p_lint.add_argument("--strict", action="store_true", help="exit 1 on warnings")
    p_lint.set_defaults(func=cmd_lint)

    p_compile = sub.add_parser("compile", help="compile a .iflow file to an execution plan")
    p_compile.add_argument("file")
    p_compile.add_argument("--out", help="write the plan JSON to this file")
    p_compile.set_defaults(func=cmd_compile)

    p_run = sub.add_parser("run", help="execute a .iflow file")
    p_run.add_argument("file")
    p_run.add_argument(
        "--simulate",
        action="store_true",
        help="alias for --backend simulate (deterministic mocked cognition)",
    )
    p_run.add_argument(
        "--backend",
        default="simulate",
        choices=sorted(BACKENDS) + ["replay"],
        help="cognition backend (default: simulate; 'replay' needs --cassette)",
    )
    p_run.add_argument("--goal", help="run a single named goal")
    p_run.add_argument(
        "--pipeline", help="run a named pipeline instead of standalone goals"
    )
    p_run.add_argument(
        "--workspace",
        help="directory of real evidence files; collection goes through the action gate",
    )
    p_run.add_argument(
        "--approve",
        action="append",
        metavar="ACTION",
        help="pre-grant human approval for an approval-gated action (repeatable)",
    )
    p_run.add_argument(
        "--approve-interactive",
        action="store_true",
        help="block and prompt on the terminal for each approval-gated action",
    )
    p_run.add_argument(
        "--approve-webhook",
        metavar="URL",
        help="request approval for gated actions from a synchronous webhook",
    )
    p_run.add_argument(
        "--judge",
        choices=["simulate", "openai", "anthropic"],
        help="run an LLM judge on 'judged' verification rules (separate tier)",
    )
    p_run.add_argument(
        "--cassette",
        help="replay recorded model responses from this file (with --backend replay)",
    )
    p_run.add_argument(
        "--record-cassette",
        help="record a real backend's model responses to this file for later replay",
    )
    p_run.add_argument(
        "--sign-trace",
        action="store_true",
        help="HMAC-sign the trace chain using the IFLOW_TRACE_KEY env var",
    )
    p_run.add_argument(
        "--trace-dir",
        help="write a timestamped, self-contained trace artifact per run to this dir",
    )
    p_run.add_argument(
        "--trace-out", help="write the full result (with trace) to a JSON file"
    )
    p_run.add_argument(
        "--json", action="store_true", help="print the full result as JSON"
    )
    p_run.add_argument(
        "--verbose", action="store_true", help="narrate every phase while running"
    )
    p_run.set_defaults(func=cmd_run)

    p_format = sub.add_parser("format", help="canonically reformat a .iflow file")
    p_format.add_argument("file")
    p_format.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if the file is not already formatted (print nothing to stdout)",
    )
    p_format.add_argument(
        "--write", action="store_true", help="rewrite the file in place"
    )
    p_format.set_defaults(func=cmd_format)

    p_inspect = sub.add_parser(
        "inspect", help="summarize goals, actions, evidence, and warnings"
    )
    p_inspect.add_argument("file")
    p_inspect.add_argument(
        "--json", action="store_true", help="emit the inspection report as JSON"
    )
    p_inspect.set_defaults(func=cmd_inspect)

    p_explain = sub.add_parser(
        "explain", help="translate a .iflow file into plain English"
    )
    p_explain.add_argument("file")
    p_explain.add_argument(
        "--json", action="store_true", help="emit the explanation as JSON"
    )
    p_explain.set_defaults(func=cmd_explain)

    p_replay = sub.add_parser(
        "replay", help="print a readable execution summary from a saved trace"
    )
    p_replay.add_argument("trace", help="a trace artifact from 'run --trace-dir'")
    p_replay.add_argument(
        "--json", action="store_true", help="emit the normalized artifact as JSON"
    )
    p_replay.set_defaults(func=cmd_replay)

    p_audit = sub.add_parser(
        "audit", help="verify a run result's trace against the compiled plan"
    )
    p_audit.add_argument("file", help="the .iflow source (the contract)")
    p_audit.add_argument("result", help="the result JSON from 'run' (the witness)")
    p_audit.set_defaults(func=cmd_audit)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except BrokenPipeError:
        # stdout was closed early (e.g. piped into `head`); exit quietly.
        try:
            sys.stdout.close()
        except Exception:
            pass
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
