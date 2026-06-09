"""Command-line interface for IntentFlow.

Commands:

    intentflow parse <file>            print the AST as JSON
    intentflow validate <file>         run semantic checks, report diagnostics
    intentflow lint <file>             static analysis of policies
    intentflow compile <file>          print the execution plan as JSON
    intentflow run <file> --simulate   execute (simulated cognition)
    intentflow run <file> --backend anthropic   execute with a real model
    intentflow audit <file> <result>   verify a run's trace against the plan
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from intentflow import __version__
from intentflow.auditor import audit_document
from intentflow.backends import make_backend
from intentflow.compiler import CompileError, compile_program, validate_program
from intentflow.linter import lint_program
from intentflow.parser import ParseError, parse_file
from intentflow.runtime import GoalRuntime, run_pipeline


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


def cmd_validate(args: argparse.Namespace) -> int:
    program = _load(args.file)
    diagnostics = validate_program(program)
    for diag in diagnostics:
        print(f"{program.source_name}:{diag.line}: {diag.level}: {diag.message}")
    errors = [d for d in diagnostics if d.level == "error"]
    if errors:
        print(f"validation failed: {len(errors)} error(s)", file=sys.stderr)
        return 1
    print(f"OK: {len(program.goals)} goal(s) valid"
          + (f" ({len(diagnostics)} warning(s))" if diagnostics else ""))
    return 0


def cmd_lint(args: argparse.Namespace) -> int:
    program = _load(args.file)
    findings = lint_program(program)
    for finding in findings:
        print(
            f"{program.source_name}:{finding.line}: {finding.rule_id} "
            f"{finding.level}: {finding.message}"
        )
    warnings = [f for f in findings if f.level == "warning"]
    print(f"lint: {len(warnings)} warning(s), {len(findings) - len(warnings)} info")
    if warnings and args.strict:
        return 1
    return 0


def cmd_compile(args: argparse.Namespace) -> int:
    program = _load(args.file)
    document = _compile_or_fail(program)
    print(json.dumps(document, indent=2))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    if not args.simulate and args.backend == "simulate":
        print(
            "error: pass --simulate for mocked cognition, or choose a real "
            "backend with --backend anthropic",
            file=sys.stderr,
        )
        return 1
    program = _load(args.file)
    document = _compile_or_fail(program)
    try:
        backend = make_backend(args.backend)
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    approved = set(args.approve or [])

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
            approved_actions=approved,
        )
        results = [result]
    else:
        results = []
        for plan in document["plans"]:
            runtime = GoalRuntime(
                plan,
                backend=backend,
                workspace=args.workspace,
                approved_actions=approved,
            )
            results.append(runtime.run())

    for result in results:
        print("\n=== final result ===")
        print(json.dumps(result, indent=2))
    if args.trace_out:
        payload = results[0] if len(results) == 1 else results
        Path(args.trace_out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nresult written to {args.trace_out} (audit it with 'intentflow audit')")
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
    report = audit_document(document, result)
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

    p_validate = sub.add_parser("validate", help="run semantic checks on a .iflow file")
    p_validate.add_argument("file")
    p_validate.set_defaults(func=cmd_validate)

    p_lint = sub.add_parser("lint", help="static analysis of action/uncertainty policies")
    p_lint.add_argument("file")
    p_lint.add_argument("--strict", action="store_true", help="exit 1 on warnings")
    p_lint.set_defaults(func=cmd_lint)

    p_compile = sub.add_parser("compile", help="compile a .iflow file to an execution plan")
    p_compile.add_argument("file")
    p_compile.set_defaults(func=cmd_compile)

    p_run = sub.add_parser("run", help="execute a .iflow file")
    p_run.add_argument("file")
    p_run.add_argument(
        "--simulate", action="store_true", help="run with deterministic mocked cognition"
    )
    p_run.add_argument(
        "--backend",
        default="simulate",
        choices=["simulate", "anthropic"],
        help="cognition backend (default: simulate)",
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
        "--trace-out", help="write the full result (with trace) to a JSON file"
    )
    p_run.set_defaults(func=cmd_run)

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
