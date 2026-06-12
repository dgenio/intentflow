"""Command-line interface for IntentFlow.

Commands:

    intentflow parse <file>            print the AST as JSON
    intentflow validate <file> [...]   run semantic checks (--json for machine output)
    intentflow lint <file> [...]       static analysis of policies
    intentflow compile <file>          print the execution plan as JSON
    intentflow inspect <file>          summarize goals, actions, evidence, warnings
    intentflow format <file> [...]     canonically reformat (--check / --write)
    intentflow run <file>              execute (defaults to the simulate backend)
    intentflow run <file> --backend openai      execute with a real model
    intentflow run <file> --trace-dir traces/    save an inspectable witness
    intentflow audit <file> <result>   verify a run's trace against the plan
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path

from intentflow import __version__
from intentflow.auditor import audit_document
from intentflow.backends import BACKENDS, make_backend
from intentflow.compiler import (
    CompileError,
    compile_program,
    inspect_program,
    validate_program,
)
from intentflow.formatter import format_source
from intentflow.judges import make_judge
from intentflow.linter import lint_program
from intentflow.parser import ParseError, parse_file
from intentflow.runtime import GoalRuntime, run_pipeline
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
    try:
        return compile_program(program)
    except CompileError as exc:
        print(f"compile error: {exc}", file=sys.stderr)
        raise SystemExit(1)


def cmd_parse(args: argparse.Namespace) -> int:
    program = _load(args.file)
    print(json.dumps(program.to_dict(), indent=2))
    return 0


def _validate_file(file: str, *, json_mode: bool) -> tuple[int, dict | None]:
    program = _load(file)
    diagnostics = validate_program(program)
    errors = [d for d in diagnostics if d.level == "error"]
    warnings = [d for d in diagnostics if d.level == "warning"]

    if json_mode:
        report = {
            "source": program.source_name,
            "ok": not errors,
            "goals": len(program.goals),
            "error_count": len(errors),
            "warning_count": len(warnings),
            "diagnostics": [
                {"level": d.level, "message": d.message, "line": d.line}
                for d in diagnostics
            ],
        }
        return (1 if errors else 0), report

    for diag in diagnostics:
        print(f"{program.source_name}:{diag.line}: {diag.level}: {diag.message}")
    if errors:
        print(f"validation failed: {len(errors)} error(s)", file=sys.stderr)
        return 1, None
    suffix = f" ({len(warnings)} warning(s))" if warnings else ""
    print(f"OK: {len(program.goals)} goal(s) valid{suffix}")
    return 0, None


def cmd_validate(args: argparse.Namespace) -> int:
    reports = []
    exit_code = 0
    for file in args.files:
        code, report = _validate_file(file, json_mode=getattr(args, "json", False))
        exit_code = max(exit_code, code)
        if report is not None:
            reports.append(report)
    if getattr(args, "json", False):
        payload = reports[0] if len(reports) == 1 else reports
        print(json.dumps(payload, indent=2))
    return exit_code


def cmd_lint(args: argparse.Namespace) -> int:
    exit_code = 0
    for file in args.files:
        program = _load(file)
        findings = lint_program(program)
        for finding in findings:
            print(
                f"{program.source_name}:{finding.line}: {finding.rule_id} "
                f"{finding.level}: {finding.message}"
            )
        warnings = [f for f in findings if f.level == "warning"]
        print(f"lint: {len(warnings)} warning(s), {len(findings) - len(warnings)} info")
        if warnings and args.strict:
            exit_code = 1
    return exit_code


def cmd_compile(args: argparse.Namespace) -> int:
    program = _load(args.file)
    document = _compile_or_fail(program)
    print(json.dumps(document, indent=2))
    return 0


def _plan_hash(document: dict) -> str:
    import hashlib

    canonical = json.dumps(document, sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()[:16]


def _write_trace_artifact(
    trace_dir: str, document: dict, result: dict, backend_name: str, source: str
) -> str:
    """Write a self-contained, inspectable witness of a run to ``trace_dir``.

    The artifact bundles the run result with provenance (source file, backend,
    timestamp, compiled-plan hash) so a third party can later replay it with
    ``intentflow audit``."""
    directory = Path(trace_dir)
    directory.mkdir(parents=True, exist_ok=True)
    label = result.get("goal") or result.get("pipeline") or "run"
    trace_id = result.get("trace_id") or _plan_hash(result)
    timestamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"{label}-{timestamp}-{trace_id}.json"
    artifact = {
        "source": source,
        "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "backend": backend_name,
        "plan_hash": _plan_hash(document),
        "trace_id": trace_id,
        "result": result,
    }
    path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    return str(path)


def _print_run_summary(result: dict) -> None:
    summary = result.get("summary")
    if not summary:  # e.g. a pipeline result
        return
    print("\n--- summary ---")
    print(f"  goal:               {result.get('goal')}")
    print(f"  backend:            {result.get('backend')}")
    print(f"  confidence:         {summary.get('confidence')}")
    print(f"  verification:       {summary.get('verification_status')}")
    print(f"  uncertainty:        {summary.get('uncertainty_status')}")
    print(f"  actions requested:  {summary.get('actions_requested') or '(none)'}")
    blocked = [b.get("action") for b in summary.get("actions_blocked", [])]
    print(f"  actions blocked:    {blocked or '(none)'}")
    print(f"  trace id:           {summary.get('trace_id')}")


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
    document = _compile_or_fail(program)
    cassette = args.cassette if backend_name == "replay" else args.record_cassette
    try:
        backend = make_backend(backend_name, cassette)
        judge = make_judge(args.judge) if args.judge else None
        sign_key = _sign_key(args)
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    approver = _build_approver(args)

    if args.pipeline:
        names = [p["name"] for p in document["pipelines"]]
        if args.pipeline not in names:
            print(
                f"error: pipeline {args.pipeline!r} not found; available: {names}",
                file=sys.stderr,
            )
            return 1
        result = run_pipeline(
            document,
            args.pipeline,
            backend=backend,
            workspace=args.workspace,
            approver=approver,
            judge=judge,
            sign_key=sign_key,
        )
        results = [result]
    else:
        results = []
        for plan in document["plans"]:
            runtime = GoalRuntime(
                plan,
                backend=backend,
                workspace=args.workspace,
                approver=approver,
                judge=judge,
                sign_key=sign_key,
            )
            results.append(runtime.run())

    for result in results:
        print("\n=== final result ===")
        print(json.dumps(result, indent=2))
        _print_run_summary(result)

    if args.trace_dir:
        for result in results:
            path = _write_trace_artifact(
                args.trace_dir, document, result, backend.name, program.source_name
            )
            print(f"\ntrace written to {path} (audit it with 'intentflow audit')")
    if args.trace_out:
        payload = results[0] if len(results) == 1 else results
        Path(args.trace_out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nresult written to {args.trace_out} (audit it with 'intentflow audit')")
    return 0


def _format_file(args: argparse.Namespace, file: str) -> int:
    path = Path(file)
    try:
        original = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"error: file not found: {file}", file=sys.stderr)
        return 2
    # Parse first so we never reformat syntactically broken source.
    _load(file)
    formatted = format_source(original)

    if args.check:
        if formatted != original:
            print(
                f"{file}: not formatted (run 'intentflow format' to fix)",
                file=sys.stderr,
            )
            return 1
        print(f"{file}: already formatted")
        return 0
    if args.write:
        if formatted != original:
            path.write_text(formatted, encoding="utf-8")
            print(f"{file}: reformatted")
        else:
            print(f"{file}: already formatted")
        return 0
    sys.stdout.write(formatted)
    return 0


def cmd_format(args: argparse.Namespace) -> int:
    exit_code = 0
    for file in args.files:
        exit_code = max(exit_code, _format_file(args, file))
    return exit_code


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
        print(f"  distrusted evidence: {', '.join(goal['distrusted_evidence']) or '(none)'}")
        print(f"  allowed actions:     {', '.join(goal['allowed_actions']) or '(none)'}")
        print(f"  approval-gated:      {', '.join(goal['approval_gated_actions']) or '(none)'}")
        print(f"  denied actions:      {', '.join(goal['denied_actions']) or '(none)'}")
        print(f"  output fields:       {', '.join(goal['output_fields']) or '(none)'}")
        warnings = [d for d in goal["diagnostics"] if d["level"] == "warning"]
        errors = [d for d in goal["diagnostics"] if d["level"] == "error"]
        for d in errors + warnings:
            print(f"  {d['level']}: {d['message']} (line {d['line']})")
    for pipeline in report["pipelines"]:
        print(f"\npipeline {pipeline['name']}: {' -> '.join(pipeline['stages'])}")
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

    p_validate = sub.add_parser("validate", help="run semantic checks on .iflow files")
    p_validate.add_argument("files", nargs="+")
    p_validate.add_argument(
        "--json", action="store_true", help="emit machine-readable JSON diagnostics"
    )
    p_validate.set_defaults(func=cmd_validate)

    p_lint = sub.add_parser(
        "lint", help="static analysis of action/uncertainty policies"
    )
    p_lint.add_argument("files", nargs="+")
    p_lint.add_argument("--strict", action="store_true", help="exit 1 on warnings")
    p_lint.set_defaults(func=cmd_lint)

    p_compile = sub.add_parser("compile", help="compile a .iflow file to an execution plan")
    p_compile.add_argument("file")
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
    p_run.set_defaults(func=cmd_run)

    p_format = sub.add_parser("format", help="canonically reformat .iflow files")
    p_format.add_argument("files", nargs="+")
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

    p_audit = sub.add_parser(
        "audit", help="verify a run result's trace against the compiled plan"
    )
    p_audit.add_argument("file", help="the .iflow source (the contract)")
    p_audit.add_argument("result", help="the result JSON from 'run --trace-out' (the witness)")
    p_audit.set_defaults(func=cmd_audit)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
