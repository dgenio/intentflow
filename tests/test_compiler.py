"""Compiler tests: plan shape, typed output schema, risk profile, prompt
plan, and verification classification."""

from __future__ import annotations

import pytest

from intentflow.compiler import (
    PLAN_VERSION,
    CompileError,
    classify_verification,
    compile_goal,
    compile_program,
    extract_uncertainty,
    parse_output_field,
)
from intentflow.parser import parse_file, parse_source

PLAN_KEYS = {
    "plan_version",
    "goal",
    "objective",
    "metadata",
    "context_policy",
    "evidence_policy",
    "action_policy",
    "model_directives",
    "verification_policy",
    "uncertainty_policy",
    "calibration",
    "output_schema",
    "risk_profile",
    "trace_policy",
    "prompt_plan",
    "execution_phases",
}


@pytest.fixture()
def triage_plan() -> dict:
    program = parse_file("examples/opensource_triage.iflow")
    return compile_goal(program.goals[0], program.source_name).to_dict()


def test_plan_has_expected_shape(triage_plan: dict) -> None:
    assert set(triage_plan) == PLAN_KEYS
    assert triage_plan["plan_version"] == PLAN_VERSION
    assert triage_plan["goal"] == "TriageGitHubIssue"
    assert "triage" in triage_plan["objective"]
    assert triage_plan["trace_policy"]["enabled"] is True


def test_document_has_versioning_and_source_hash() -> None:
    program = parse_file("examples/opensource_triage.iflow")
    document = compile_program(program)
    assert document["plan_version"] == PLAN_VERSION
    assert document["intentflow_version"]
    assert len(document["source_hash"]) == 64
    assert document["source"].endswith("opensource_triage.iflow")
    assert len(document["goals"]) == 1


def test_compile_is_stable() -> None:
    program = parse_file("examples/opensource_triage.iflow")
    assert compile_program(program) == compile_program(program)


def test_evidence_policy_separates_stances(triage_plan: dict) -> None:
    policy = triage_plan["evidence_policy"]
    assert policy["required"] == ["issue_body", "comments", "repo_context"]
    assert policy["optional"] == ["related_issues"]
    assert policy["distrusted"] == ["unsupported_claims"]


def test_action_policy_groups_modes(triage_plan: dict) -> None:
    policy = triage_plan["action_policy"]
    assert policy["allowed"] == ["read_issue", "search_repo", "draft_comment"]
    assert policy["approval_required"] == ["post_comment"]
    assert policy["denied"] == ["close_issue"]


def test_metadata_is_lowered(triage_plan: dict) -> None:
    assert triage_plan["metadata"]["description"] == "governed open-source issue triage"
    assert triage_plan["metadata"]["owner"] == "maintainers"


def test_output_schema_is_typed(triage_plan: dict) -> None:
    fields = {f["name"]: f for f in triage_plan["output_schema"]["fields"]}
    assert fields["summary"]["base"] == "string"
    assert fields["likely_cause"]["optional"] is True
    assert fields["confidence"]["base"] == "number"
    assert fields["suggested_response"]["base"] == "markdown"
    assert fields["proposed_labels"]["base"] == "list"
    assert fields["proposed_labels"]["item_type"] == "string"


def test_output_field_parsing_covers_all_types() -> None:
    for type_text, base, item, optional in [
        ("string", "string", None, False),
        ("string?", "string", None, True),
        ("number", "number", None, False),
        ("boolean?", "boolean", None, True),
        ("markdown", "markdown", None, False),
        ("list[string]", "list", "string", False),
        ("list[number]", "list", "number", False),
        ("object?", "object", None, True),
    ]:
        field = parse_output_field(f"x: {type_text}", 1)
        assert (field.base, field.item_type, field.optional) == (base, item, optional)


def test_invalid_output_type_is_a_compile_error() -> None:
    with pytest.raises(CompileError, match="invalid output type"):
        parse_output_field("x: blob", 3)


def test_bare_output_field_defaults_to_string() -> None:
    field = parse_output_field("answer", 1)
    assert field.type == "string" and field.base == "string"


def test_uncertainty_rule_extraction() -> None:
    program = parse_file("examples/opensource_triage.iflow")
    rules = extract_uncertainty(program.goals[0])
    assert len(rules) == 3
    threshold = rules[0]
    assert threshold.condition.kind == "threshold"
    assert threshold.condition.metric == "confidence"
    assert threshold.condition.op == "<"
    assert threshold.condition.threshold == 0.65
    assert threshold.action.name == "ask_human"
    assert threshold.action.primitive is True
    signal = rules[1]
    assert signal.condition.kind == "signal"
    assert signal.condition.signal == "missing_evidence"
    block = rules[2]
    assert block.condition.signal == "security_risk"
    assert block.action.name == "block_action"


def test_prompt_plan_is_staged(triage_plan: dict) -> None:
    blocks = triage_plan["prompt_plan"]["blocks"]
    assert [b["phase"] for b in blocks] == [
        "system",
        "objective",
        "evidence",
        "actions_allowed",
        "actions_denied",
        "verify",
        "uncertainty",
        "output",
    ]
    by_phase = {b["phase"]: b["instruction"] for b in blocks}
    assert "post_comment" in by_phase["actions_allowed"]
    assert "close_issue" in by_phase["actions_denied"]
    assert "proposed_labels (list[string])" in by_phase["output"]
    assert blocks[0]["role"] == "system"


def test_execution_phases_are_embedded(triage_plan: dict) -> None:
    assert triage_plan["execution_phases"][0] == "parse"
    assert triage_plan["execution_phases"][-1] == "trace"
    assert "verify_output" in triage_plan["execution_phases"]


def test_risk_profile_medium_for_gated_side_effects(triage_plan: dict) -> None:
    risk = triage_plan["risk_profile"]
    assert risk["level"] == "medium"
    assert risk["approval_required"] == ["post_comment"]
    assert risk["blocked_actions"] == ["close_issue"]
    assert "post_comment" in risk["side_effect_actions"]


def test_risk_profile_high_for_ungated_side_effects() -> None:
    program = parse_file("examples/high_risk_deploy.iflow")
    plan = compile_goal(program.goals[0], program.source_name).to_dict()
    risk = plan["risk_profile"]
    assert risk["level"] == "high"
    assert any("deploy_change" in c for c in risk["missing_safety_controls"])


def test_risk_profile_low_for_read_only_goals() -> None:
    src = (
        "goal G {\n  objective:\n    x\n"
        "  evidence:\n    require logs\n    require config\n"
        "  actions:\n    allow read_logs\n"
        "  verify:\n    require cites_evidence\n"
        "  uncertainty:\n    if confidence < 0.5 ask_human\n"
        "  output:\n    answer: string\n    confidence: number\n}\n"
    )
    plan = compile_goal(parse_source(src).goals[0]).to_dict()
    assert plan["risk_profile"]["level"] == "low"
    assert plan["risk_profile"]["missing_safety_controls"] == []


def test_citation_classifier_matches_only_whole_words() -> None:
    for rule in ("each claim must cite a source", "require citations",
                 "every finding is cited"):
        assert classify_verification(rule)["kind"] == "cites_evidence", rule
    for rule in ("be explicit about assumptions", "keep implicit state visible",
                 "do not solicit private data"):
        assert classify_verification(rule)["kind"] == "judged", rule


def test_named_require_checks_classify() -> None:
    assert classify_verification("require cites_evidence") == {
        "kind": "cites_evidence", "mode": "machine",
    }
    judged = classify_verification("require maintainer_safe_tone")
    assert judged["mode"] == "judged"
    assert judged["name"] == "maintainer_safe_tone"


def test_threshold_check_verification_is_machine_checkable() -> None:
    check = classify_verification("check confidence >= 0.7")
    assert check == {
        "kind": "threshold_check",
        "metric": "confidence",
        "op": ">=",
        "value": 0.7,
        "mode": "machine",
    }


def test_verification_rules_get_ids_and_typed_checks(triage_plan: dict) -> None:
    rules = triage_plan["verification_policy"]["rules"]
    assert [r["rule_id"] for r in rules] == ["V1", "V2", "V3", "V4"]
    assert rules[0]["check"]["kind"] == "cites_evidence"
    assert rules[1]["check"]["mode"] == "judged"
    assert rules[3]["check"]["kind"] == "threshold_check"


def test_calibration_policy_is_part_of_the_plan(triage_plan: dict) -> None:
    assert triage_plan["calibration"]["method"] == "shrinkage"


def test_missing_objective_fails_compilation_with_code() -> None:
    program = parse_source("goal G {\n  output:\n    result: string\n}\n")
    with pytest.raises(CompileError, match="IFLOW001"):
        compile_goal(program.goals[0])


def test_conflicting_action_policies_fail_compilation() -> None:
    source = (
        "goal G {\n  objective:\n    x\n"
        "  actions:\n    allow deploy\n    deny deploy\n"
        "  output:\n    a: string\n}\n"
    )
    with pytest.raises(CompileError, match="IFLOW006"):
        compile_goal(parse_source(source).goals[0])


def test_unknown_action_mode_is_a_compile_error() -> None:
    source = "goal G {\n  objective:\n    x\n  actions:\n    permit read_logs\n}\n"
    with pytest.raises(CompileError, match="unknown action mode 'permit'") as exc_info:
        compile_goal(parse_source(source).goals[0])
    assert exc_info.value.line == 5


def test_malformed_uncertainty_rule_is_a_compile_error() -> None:
    source = (
        "goal G {\n  objective:\n    x\n"
        "  uncertainty:\n    whenever unsure panic\n  output:\n    a: string\n}\n"
    )
    with pytest.raises(CompileError, match="malformed uncertainty rule"):
        compile_goal(parse_source(source).goals[0])
