"""Lint surface tests: the advisory tier of the analyzer."""

from __future__ import annotations

from intentflow.linter import lint_program
from intentflow.parser import parse_file, parse_source


def _lint(source: str):
    return lint_program(parse_source(source))


def test_lint_surfaces_warnings_with_codes() -> None:
    findings = _lint(
        "goal G {\n  objective:\n    x\n"
        "  actions:\n    allow deploy_change\n"
        "  output:\n    result: string\n}\n"
    )
    assert any(
        f.rule_id == "IFLOW010" and "deploy_change" in f.message for f in findings
    )


def test_lint_excludes_errors() -> None:
    findings = _lint("goal G {\n  output:\n    result: string\n}\n")
    assert all(f.level in ("warning", "info") for f in findings)


def test_judged_rule_is_informational() -> None:
    findings = _lint(
        "goal G {\n  objective:\n    x\n"
        "  verify:\n    the answer must be tasteful\n"
        "  output:\n    result: string\n}\n"
    )
    flagged = [f for f in findings if f.rule_id == "IFLOW021"]
    assert flagged and flagged[0].level == "info"


def test_flagship_example_has_no_lint_warnings() -> None:
    findings = lint_program(parse_file("examples/opensource_triage.iflow"))
    assert not [f for f in findings if f.level == "warning"]
