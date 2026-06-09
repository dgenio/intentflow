"""Static analysis (lint) tests."""

from __future__ import annotations

from intentflow.linter import lint_program
from intentflow.parser import parse_file, parse_source


def _lint(source: str):
    return lint_program(parse_source(source))


def test_destructive_allowed_action_without_safeguards_is_flagged() -> None:
    findings = _lint(
        "goal G {\n  objective:\n    x\n"
        "  actions:\n    allow deploy_change\n"
        "  output:\n    result\n}\n"
    )
    assert any(
        f.rule_id == "IF001" and "deploy_change" in f.message for f in findings
    )


def test_destructive_action_with_verify_mention_is_not_flagged() -> None:
    findings = _lint(
        "goal G {\n  objective:\n    x\n"
        "  actions:\n    allow deploy_change\n"
        "  verify:\n    deploy_change must cite evidence of a passing canary\n"
        "  output:\n    result\n}\n"
    )
    assert not any(f.rule_id == "IF001" for f in findings)


def test_approval_gated_destructive_action_is_not_flagged() -> None:
    findings = _lint(
        "goal G {\n  objective:\n    x\n"
        "  actions:\n    require_approval deploy_change\n"
        "  output:\n    result\n}\n"
    )
    assert not any(f.rule_id == "IF001" for f in findings)


def test_unreachable_threshold_is_flagged() -> None:
    findings = _lint(
        "goal G {\n  objective:\n    x\n"
        "  uncertainty:\n    if confidence < 0.0 ask_human\n"
        "  output:\n    result\n}\n"
    )
    assert any(f.rule_id == "IF002" and "never trigger" in f.message for f in findings)


def test_duplicate_uncertainty_rule_is_flagged() -> None:
    findings = _lint(
        "goal G {\n  objective:\n    x\n"
        "  uncertainty:\n    if confidence < 0.5 ask_human\n"
        "    if confidence < 0.5 ask_human\n"
        "  output:\n    result\n}\n"
    )
    assert any(f.rule_id == "IF002" and "duplicate" in f.message for f in findings)


def test_unevaluable_symbolic_condition_is_informational() -> None:
    findings = _lint(
        "goal G {\n  objective:\n    x\n"
        "  uncertainty:\n    if vibes_are_off ask_human\n"
        "  output:\n    result\n}\n"
    )
    flagged = [f for f in findings if f.rule_id == "IF003"]
    assert flagged and flagged[0].level == "info"


def test_judged_verification_rule_is_informational() -> None:
    findings = _lint(
        "goal G {\n  objective:\n    x\n"
        "  verify:\n    the answer must be tasteful\n"
        "  output:\n    result\n}\n"
    )
    assert any(f.rule_id == "IF004" for f in findings)


def test_diagnose_example_has_no_lint_warnings() -> None:
    findings = lint_program(parse_file("examples/diagnose.iflow"))
    assert not [f for f in findings if f.level == "warning"]
