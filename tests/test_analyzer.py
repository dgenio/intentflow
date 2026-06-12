"""Analyzer tests: coded diagnostics with severity, position, suggestion."""

from __future__ import annotations

from intentflow.analyzer import analyze_program, errors_in, warnings_in
from intentflow.parser import parse_file, parse_source


def _codes(source: str) -> dict[str, str]:
    """Map diagnostic code -> severity for inline source."""
    return {d.code: d.severity for d in analyze_program(parse_source(source))}


GOOD = """\
goal G {
  objective:
    do the thing

  evidence:
    require logs
    require config

  actions:
    allow read_logs

  verify:
    require cites_evidence
    check confidence >= 0.6

  uncertainty:
    if confidence < 0.6 ask_human

  output:
    answer: string
    confidence: number
}
"""


def test_well_formed_goal_has_no_errors_or_warnings() -> None:
    diagnostics = analyze_program(parse_source(GOOD))
    assert errors_in(diagnostics) == []
    assert warnings_in(diagnostics) == []


def test_missing_objective_is_iflow001() -> None:
    codes = _codes("goal G {\n  output:\n    a: string\n}\n")
    assert codes.get("IFLOW001") == "error"


def test_missing_output_schema_is_iflow002() -> None:
    codes = _codes("goal G {\n  objective:\n    x\n}\n")
    assert codes.get("IFLOW002") == "warning"


def test_confidence_gate_without_confidence_output_is_iflow003() -> None:
    src = (
        "goal G {\n  objective:\n    x\n"
        "  uncertainty:\n    if confidence < 0.5 ask_human\n"
        "  output:\n    answer: string\n}\n"
    )
    assert _codes(src).get("IFLOW003") == "warning"


def test_duplicate_output_field_is_iflow004() -> None:
    src = (
        "goal G {\n  objective:\n    x\n"
        "  output:\n    a: string\n    a: number\n}\n"
    )
    assert _codes(src).get("IFLOW004") == "error"


def test_invalid_output_type_is_iflow005() -> None:
    src = "goal G {\n  objective:\n    x\n  output:\n    a: blob\n}\n"
    assert _codes(src).get("IFLOW005") == "error"


def test_conflicting_action_policies_is_iflow006() -> None:
    src = (
        "goal G {\n  objective:\n    x\n"
        "  actions:\n    allow deploy_change\n    deny deploy_change\n"
        "  output:\n    a: string\n}\n"
    )
    assert _codes(src).get("IFLOW006") == "error"


def test_gated_and_denied_action_is_iflow006() -> None:
    src = (
        "goal G {\n  objective:\n    x\n"
        "  actions:\n    require_approval post_comment\n    deny post_comment\n"
        "  output:\n    a: string\n}\n"
    )
    assert _codes(src).get("IFLOW006") == "error"


def test_verification_metric_referencing_unknown_output_is_iflow007() -> None:
    src = (
        "goal G {\n  objective:\n    x\n"
        "  verify:\n    check accuracy >= 0.5\n"
        "  output:\n    answer: string\n}\n"
    )
    assert _codes(src).get("IFLOW007") == "warning"


def test_verification_metric_matching_output_field_is_fine() -> None:
    src = (
        "goal G {\n  objective:\n    x\n"
        "  verify:\n    check accuracy >= 0.5\n"
        "  output:\n    accuracy: number\n}\n"
    )
    assert "IFLOW007" not in _codes(src)


def test_unknown_uncertainty_signal_is_iflow008() -> None:
    src = (
        "goal G {\n  objective:\n    x\n"
        "  uncertainty:\n    if vibes_are_off ask_human\n"
        "  output:\n    a: string\n}\n"
    )
    assert _codes(src).get("IFLOW008") == "warning"


def test_single_evidence_source_is_iflow009() -> None:
    src = (
        "goal G {\n  objective:\n    x\n"
        "  evidence:\n    require logs\n"
        "  output:\n    a: string\n}\n"
    )
    assert _codes(src).get("IFLOW009") == "warning"


def test_side_effect_action_without_approval_is_iflow010() -> None:
    src = (
        "goal G {\n  objective:\n    x\n"
        "  actions:\n    allow post_comment\n"
        "  output:\n    a: string\n}\n"
    )
    assert _codes(src).get("IFLOW010") == "warning"


def test_gated_side_effect_action_is_not_flagged() -> None:
    src = (
        "goal G {\n  objective:\n    x\n"
        "  actions:\n    require_approval post_comment\n"
        "  output:\n    a: string\n}\n"
    )
    assert "IFLOW010" not in _codes(src)


def test_overly_broad_action_is_iflow011() -> None:
    src = (
        "goal G {\n  objective:\n    x\n"
        "  actions:\n    allow execute_code\n"
        "  output:\n    a: string\n}\n"
    )
    assert _codes(src).get("IFLOW011") == "warning"


def test_missing_sections_are_iflow012_013_014() -> None:
    codes = _codes("goal G {\n  objective:\n    x\n  output:\n    a: string\n}\n")
    assert codes.get("IFLOW012") == "warning"  # no verification
    assert codes.get("IFLOW013") == "warning"  # no uncertainty
    assert codes.get("IFLOW014") == "warning"  # no evidence


def test_max_tokens_bounds_are_iflow015() -> None:
    low = (
        "goal G {\n  objective:\n    x\n  context:\n    max_tokens 10\n"
        "  output:\n    a: string\n}\n"
    )
    high = (
        "goal G {\n  objective:\n    x\n  context:\n    max_tokens 9999999\n"
        "  output:\n    a: string\n}\n"
    )
    assert _codes(low).get("IFLOW015") == "warning"
    assert _codes(high).get("IFLOW015") == "warning"


def test_duplicate_goal_names_is_iflow016() -> None:
    src = (
        "goal G {\n  objective:\n    x\n}\n"
        "goal G {\n  objective:\n    y\n}\n"
    )
    assert _codes(src).get("IFLOW016") == "error"


def test_untyped_output_field_is_iflow017_info() -> None:
    src = "goal G {\n  objective:\n    x\n  output:\n    answer\n}\n"
    assert _codes(src).get("IFLOW017") == "info"


def test_undeclared_uncertainty_action_is_iflow018() -> None:
    src = (
        "goal G {\n  objective:\n    x\n"
        "  uncertainty:\n    if confidence < 0.5 reboot_server\n"
        "  output:\n    a: string\n}\n"
    )
    assert _codes(src).get("IFLOW018") == "warning"


def test_allowed_uncertainty_action_is_not_flagged() -> None:
    src = (
        "goal G {\n  objective:\n    x\n"
        "  actions:\n    allow run_canary\n"
        "  uncertainty:\n    if confidence < 0.5 run_canary\n"
        "  output:\n    a: string\n}\n"
    )
    assert "IFLOW018" not in _codes(src)


def test_out_of_range_confidence_threshold_is_iflow019() -> None:
    src = (
        "goal G {\n  objective:\n    x\n"
        "  uncertainty:\n    if confidence < 1.5 ask_human\n"
        "  output:\n    a: string\n}\n"
    )
    assert _codes(src).get("IFLOW019") == "error"


def test_malformed_statement_is_iflow020() -> None:
    src = (
        "goal G {\n  objective:\n    x\n"
        "  actions:\n    permit read_logs\n"
        "  output:\n    a: string\n}\n"
    )
    assert _codes(src).get("IFLOW020") == "error"


def test_judged_rule_is_iflow021_info() -> None:
    src = (
        "goal G {\n  objective:\n    x\n"
        "  verify:\n    require maintainer_safe_tone\n"
        "  output:\n    a: string\n}\n"
    )
    assert _codes(src).get("IFLOW021") == "info"


def test_unreachable_and_duplicate_thresholds_are_iflow022() -> None:
    unreachable = (
        "goal G {\n  objective:\n    x\n"
        "  uncertainty:\n    if confidence < 0.0 ask_human\n"
        "  output:\n    a: string\n}\n"
    )
    duplicate = (
        "goal G {\n  objective:\n    x\n"
        "  uncertainty:\n    if confidence < 0.5 ask_human\n"
        "    if confidence < 0.5 ask_human\n"
        "  output:\n    a: string\n}\n"
    )
    assert _codes(unreachable).get("IFLOW022") == "warning"
    assert _codes(duplicate).get("IFLOW022") == "warning"


def test_diagnostics_carry_position_and_suggestion() -> None:
    diagnostics = analyze_program(
        parse_source("goal G {\n  output:\n    a: string\n}\n")
    )
    missing_objective = next(d for d in diagnostics if d.code == "IFLOW001")
    assert missing_objective.line == 1
    assert missing_objective.suggestion
    rendered = missing_objective.render("x.iflow")
    assert "x.iflow:1" in rendered and "IFLOW001" in rendered


def test_flagship_example_has_no_errors_or_warnings() -> None:
    diagnostics = analyze_program(parse_file("examples/opensource_triage.iflow"))
    assert errors_in(diagnostics) == []
    assert warnings_in(diagnostics) == []


def test_all_examples_are_error_free() -> None:
    from pathlib import Path

    for path in sorted(Path("examples").glob("*.iflow")):
        diagnostics = analyze_program(parse_file(path))
        assert errors_in(diagnostics) == [], path


def test_warning_example_warns_but_does_not_error() -> None:
    diagnostics = analyze_program(parse_file("examples/research_synthesis.iflow"))
    assert errors_in(diagnostics) == []
    assert warnings_in(diagnostics), "research_synthesis should trigger warnings"
