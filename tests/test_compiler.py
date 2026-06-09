"""Compiler tests: plan shape, action governance, uncertainty extraction,
and semantic validation."""

from __future__ import annotations

import pytest

from intentflow.compiler import (
    CompileError,
    compile_goal,
    compile_program,
    extract_uncertainty,
    validate_program,
)
from intentflow.parser import parse_file, parse_source

PLAN_KEYS = {
    "plan_version",
    "goal",
    "objective",
    "context_policy",
    "evidence",
    "actions",
    "model_directives",
    "verification",
    "uncertainty_policy",
    "outputs",
    "trace",
    "prompt_plan",
}


@pytest.fixture()
def diagnose_plan() -> dict:
    program = parse_file("examples/diagnose.iflow")
    return compile_goal(program.goals[0], program.source_name).to_dict()


def test_plan_has_expected_shape(diagnose_plan: dict) -> None:
    assert set(diagnose_plan) == PLAN_KEYS
    assert diagnose_plan["goal"] == "DiagnoseProductionIssue"
    assert "root cause" in diagnose_plan["objective"]
    assert diagnose_plan["outputs"] == [
        "root_cause",
        "confidence",
        "recommended_fix",
        "risk",
    ]
    assert diagnose_plan["trace"]["enabled"] is True


def test_evidence_stances_are_separated(diagnose_plan: dict) -> None:
    assert diagnose_plan["evidence"]["required"] == ["logs", "config", "recent_commits"]
    assert diagnose_plan["evidence"]["distrusted"] == ["speculation_without_sources"]


def test_approval_gated_actions(diagnose_plan: dict) -> None:
    assert diagnose_plan["actions"]["allowed"] == ["read_logs", "inspect_code"]
    assert diagnose_plan["actions"]["approval_required"] == ["deploy_change"]
    assert diagnose_plan["actions"]["denied"] == []


def test_context_policy(diagnose_plan: dict) -> None:
    assert diagnose_plan["context_policy"] == {
        "max_tokens": 12000,
        "prefer": ["recent_logs"],
        "preserve": ["user_decisions"],
    }


def test_uncertainty_rule_extraction() -> None:
    program = parse_file("examples/diagnose.iflow")
    rules = extract_uncertainty(program.goals[0])
    assert len(rules) == 2
    threshold = rules[0]
    assert threshold.kind == "threshold"
    assert threshold.metric == "confidence"
    assert threshold.op == "<"
    assert threshold.threshold == 0.7
    assert threshold.action == "ask_human"
    symbolic = rules[1]
    assert symbolic.kind == "symbolic"
    assert symbolic.condition == "competing_hypotheses remain"
    assert symbolic.action == "run_discriminating_test"


def test_prompt_plan_is_staged(diagnose_plan: dict) -> None:
    phases = [step["phase"] for step in diagnose_plan["prompt_plan"]]
    assert phases == ["frame", "evidence", "model", "verify", "output"]
    frame = diagnose_plan["prompt_plan"][0]["instruction"]
    assert "deploy_change" in frame  # approval gating is visible in the prompt


def test_verification_rules_get_ids(diagnose_plan: dict) -> None:
    ids = [rule["id"] for rule in diagnose_plan["verification"]]
    assert ids == ["V1", "V2"]


def test_compile_program_wraps_all_goals() -> None:
    program = parse_file("examples/code_review.iflow")
    document = compile_program(program)
    assert document["source"].endswith("code_review.iflow")
    assert len(document["plans"]) == 1


def test_missing_objective_fails_compilation() -> None:
    program = parse_source("goal G {\n  output:\n    result\n}\n")
    with pytest.raises(CompileError, match="no objective"):
        compile_goal(program.goals[0])


def test_unknown_action_mode_is_a_compile_error() -> None:
    source = "goal G {\n  objective:\n    x\n  actions:\n    permit read_logs\n}\n"
    program = parse_source(source)
    with pytest.raises(CompileError, match="unknown action mode 'permit'") as exc_info:
        compile_goal(program.goals[0])
    assert exc_info.value.line == 5


def test_conflicting_action_policies_are_an_error() -> None:
    source = (
        "goal G {\n  objective:\n    x\n"
        "  actions:\n    allow deploy\n    deny deploy\n}\n"
    )
    diagnostics = validate_program(parse_source(source))
    errors = [d for d in diagnostics if d.level == "error"]
    assert any("conflicting policies for action 'deploy'" in d.message for d in errors)


def test_confidence_threshold_out_of_range_is_an_error() -> None:
    source = (
        "goal G {\n  objective:\n    x\n"
        "  uncertainty:\n    if confidence < 1.5 ask_human\n}\n"
    )
    diagnostics = validate_program(parse_source(source))
    assert any("out of range" in d.message for d in diagnostics if d.level == "error")


def test_missing_evidence_and_verify_produce_warnings() -> None:
    source = "goal G {\n  objective:\n    x\n  output:\n    result\n}\n"
    diagnostics = validate_program(parse_source(source))
    warnings = {d.message for d in diagnostics if d.level == "warning"}
    assert any("no evidence requirements" in w for w in warnings)
    assert any("no verification rules" in w for w in warnings)


def test_examples_validate_cleanly() -> None:
    for name in ("diagnose", "code_review", "research_question"):
        diagnostics = validate_program(parse_file(f"examples/{name}.iflow"))
        assert not [d for d in diagnostics if d.level == "error"], name
