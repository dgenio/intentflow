"""Command-line interface for IntentFlow.

Commands:

    intentflow parse <file>            print the AST as JSON
    intentflow validate <file>         run semantic checks, report diagnostics
    intentflow compile <file>          print the execution plan as JSON
    intentflow run <file> --simulate   execute the plan in simulation mode
"""

from __future__ import annotations

import argparse
import json
import sys

from intentflow import __version__
from intentflow.compiler import CompileError, compile_program, validate_program
from intentflow.parser import ParseError, parse_file
from intentflow.runtime import SimulationRuntime


def _load(path: str):
    try:
        return parse_file(path)
    except FileNotFoundError:
        print(f"error: file not found: {path}", file=sys.stderr)
        raise SystemExit(2)
    except ParseError as exc:
        print(f"parse error: {exc}", file=sys.stderr)
        raise SystemExit(2)


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


def cmd_compile(args: argparse.Namespace) -> int:
    program = _load(args.file)
    try:
        document = compile_program(program)
    except CompileError as exc:
        print(f"compile error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(document, indent=2))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    if not args.simulate:
        print(
            "error: only simulation mode is implemented in this prototype; "
            "pass --simulate",
            file=sys.stderr,
        )
        return 1
    program = _load(args.file)
    try:
        document = compile_program(program)
    except CompileError as exc:
        print(f"compile error: {exc}", file=sys.stderr)
        return 1
    for plan in document["plans"]:
        runtime = SimulationRuntime(plan)
        result = runtime.run()
        print("\n=== final result ===")
        print(json.dumps(result, indent=2))
    return 0


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

    p_compile = sub.add_parser("compile", help="compile a .iflow file to an execution plan")
    p_compile.add_argument("file")
    p_compile.set_defaults(func=cmd_compile)

    p_run = sub.add_parser("run", help="execute a .iflow file")
    p_run.add_argument("file")
    p_run.add_argument(
        "--simulate",
        action="store_true",
        help="run with mocked cognition (required; no LLM backend yet)",
    )
    p_run.set_defaults(func=cmd_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
