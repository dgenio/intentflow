"""Runtime tests: the 13-phase machine, run statuses, verification behavior,
uncertainty control flow, and the auditable trace."""

from __future__ import annotations

import pytest

from intentflow.backends import MockBackend
from intentflow.compiler import EXECUTION_PHASES, compile_goal
from intentflow.parser import parse_file, parse_source
from intentflow.runtime import GoalRuntime, execute_program

TRIAGE = "examples/opensource_triage.iflow"


def _plan(path_or_source: str) -> dict:
    if path_or_source.endswith(".iflow"):
        program = parse_file(path_or_source)
    else:
        program = parse_source(path_or_source)
    return compile_goal(program.goals[0], program.source_name).to_dict()


def _run(path_or_source: str, **kwargs) -> dict:
    return GoalRuntime(_plan(path_or_source), printer=None, **kwargs).run()


@pytest.fixture(scope="module")
def triage_result() -> dict:
    return GoalRuntime(_plan(TRIAGE), printer=None).run()


# -- statuses ---------------------------------------------------------------


def test_flagship_example_completes(triage_result: dict) -> None:
    assert triage_result["status"] == "completed"
    assert triage_result["verification"]["passed"] is True
    assert triage_result["escalations"] == []


def test_needs_human_when_confidence_below_threshold() -> None:
    # production_diagnosis declares `if confidence < 0.7 ask_human`; the
    # simulator's calibrated confidence is 0.676.
    result = _run("examples/production_diagnosis.iflow")
    assert result["status"] == "needs_human"
    assert result["escalations"]
    assert "confidence" in result["escalations"][0]["reason"]


def test_blocked_when_security_risk_rule_fires() -> None:
    # high_risk_deploy allows deploy_change ungated -> risk profile high ->
    # `if security_risk block_action` fires.
    result = _run("examples/high_risk_deploy.iflow")
    assert result["status"] == "blocked"
    events = [e["event"] for e in result["trace"]]
    assert "action_blocked_by_policy" in events


def test_backend_error_when_backend_raises() -> None:
    result = _run(TRIAGE, backend=MockBackend(RuntimeError("provider down")))
    assert result["status"] == "backend_error"
    assert "provider down" in result["backend_error"]
    assert result["outputs"] == {}


def test_backend_error_when_reply_is_not_json() -> None:
    result = _run(TRIAGE, backend=MockBackend("complete gibberish"))
    assert result["status"] == "backend_error"
    assert "not a JSON object" in result["backend_error"]
    phases = {p["name"]: p["status"] for p in result["phases"]}
    assert phases["parse_output"] == "failed"
    assert phases["verify_output"] == "skipped"


def test_failed_verification_on_low_confidence() -> None:
    # confidence 0.2 calibrates to 0.26: the `check confidence >= 0.65`
    # machine check fails AND ask_human fires; blocked/needs_human wins over
    # failed_verification per the documented precedence.
    backend = MockBackend(
        {
            "output": {
                "summary": "s", "likely_cause": None, "confidence": 0.2,
                "suggested_response": "r", "proposed_labels": ["bug"],
            },
            "confidence": 0.2,
            "citations": ["E1"],
        }
    )
    result = _run(TRIAGE, backend=backend)
    assert result["status"] == "needs_human"
    assert result["verification"]["passed"] is False


def test_failed_verification_is_never_reported_as_completed() -> None:
    # A goal with a failing machine check but no uncertainty escalation.
    src = (
        "goal G {\n  objective:\n    x\n"
        "  evidence:\n    require logs\n    require config\n"
        "  verify:\n    require cites_evidence\n"
        "  output:\n    answer: string\n}\n"
    )
    backend = MockBackend(
        {"output": {"answer": "a"}, "confidence": 0.9, "citations": []}
    )
    result = _run(src, backend=backend)
    assert result["status"] == "failed_verification"
    checks = {c["rule"]: c["status"] for c in result["verification"]["checks"]}
    assert checks["require cites_evidence"] == "fail"


def test_failed_validation_via_execute_program() -> None:
    program = parse_source("goal G {\n  output:\n    a: string\n}\n")
    result = execute_program(program)
    assert result["status"] == "failed_validation"
    assert result["backend"] is None
    assert any(d["code"] == "IFLOW001" for d in result["diagnostics"])
    assert [p["name"] for p in result["phases"]] == ["parse", "analyze"]
    assert result["phases"][-1]["status"] == "failed"


def test_execute_program_runs_all_phases() -> None:
    result = execute_program(parse_file(TRIAGE))
    assert result["status"] == "completed"
    assert [p["name"] for p in result["phases"]] == list(EXECUTION_PHASES)
    assert all(p["status"] == "completed" for p in result["phases"])


def test_execute_program_unknown_goal_raises() -> None:
    with pytest.raises(ValueError, match="unknown goal"):
        execute_program(parse_file(TRIAGE), "Nope")


# -- outputs and schema -------------------------------------------------------


def test_outputs_match_typed_schema(triage_result: dict) -> None:
    outputs = triage_result["outputs"]
    assert set(outputs) == {
        "summary", "likely_cause", "confidence", "suggested_response",
        "proposed_labels",
    }
    assert isinstance(outputs["summary"], str)
    assert isinstance(outputs["proposed_labels"], list)
    # The declared confidence output carries the *calibrated* value.
    assert outputs["confidence"] == triage_result["confidence"]["calibrated"]


def test_confidence_is_calibrated_before_rules_fire(triage_result: dict) -> None:
    confidence = triage_result["confidence"]
    assert confidence["raw"] == 0.72
    assert confidence["calibrated"] == 0.676  # shrinkage toward 0.5, factor 0.8


def test_schema_violation_fails_verification() -> None:
    backend = MockBackend(
        {
            "output": {
                "summary": 123,  # wrong type
                "confidence": 0.9,
                "suggested_response": "r",
                "proposed_labels": ["a"],
            },
            "confidence": 0.9,
            "citations": ["E1"],
        }
    )
    result = _run(TRIAGE, backend=backend)
    assert result["status"] == "failed_verification"
    schema_check = result["verification"]["checks"][0]
    assert schema_check["id"] == "V0"
    assert schema_check["status"] == "fail"
    assert "summary" in schema_check["note"]


def test_missing_optional_field_is_filled_with_null() -> None:
    backend = MockBackend(
        {
            "output": {
                "summary": "s", "confidence": 0.9,
                "suggested_response": "r", "proposed_labels": ["a"],
                # likely_cause (string?) omitted on purpose
            },
            "confidence": 0.9,
            "citations": ["E1"],
        }
    )
    result = _run(TRIAGE, backend=backend)
    assert result["outputs"]["likely_cause"] is None
    assert result["verification"]["checks"][0]["status"] == "pass"


def test_undeclared_output_fields_are_dropped() -> None:
    backend = MockBackend(
        {
            "output": {
                "summary": "s", "likely_cause": None, "confidence": 0.9,
                "suggested_response": "r", "proposed_labels": ["a"],
                "extra_field": "should vanish",
            },
            "confidence": 0.9,
            "citations": ["E1"],
        }
    )
    result = _run(TRIAGE, backend=backend)
    assert "extra_field" not in result["outputs"]
    assert any(e["event"] == "extra_fields_dropped" for e in result["trace"])


def test_dangling_citations_are_dropped_and_traced() -> None:
    backend = MockBackend(
        {
            "output": {
                "summary": "s", "likely_cause": None, "confidence": 0.9,
                "suggested_response": "r", "proposed_labels": ["a"],
            },
            "confidence": 0.9,
            "citations": ["E1", "E99"],
        }
    )
    result = _run(TRIAGE, backend=backend)
    assert result["citations"] == ["E1"]
    dropped = [e for e in result["trace"] if e["event"] == "citations_dropped"]
    assert dropped and dropped[0]["detail"]["citations"] == ["E99"]


# -- evidence and signals ------------------------------------------------------


def test_evidence_is_collected_for_required_and_optional(triage_result: dict) -> None:
    sources = [e["source"] for e in triage_result["evidence"]]
    assert sources == ["issue_body", "comments", "repo_context", "related_issues"]
    assert all(e["id"].startswith("E") for e in triage_result["evidence"])


def test_blocked_evidence_sets_missing_evidence_signal() -> None:
    # The goal requires logs but does not allow read_logs: with a workspace
    # in play the gate blocks the tool and the goal does NOT get the data.
    src = (
        "goal Locked {\n  objective:\n    diagnose without log access\n"
        "  evidence:\n    require logs\n    require config\n"
        "  actions:\n    allow inspect_code\n"
        "  uncertainty:\n    if missing_evidence ask_human\n"
        "  output:\n    root_cause: string\n}\n"
    )
    result = GoalRuntime(
        _plan(src), printer=None, workspace="examples/workspace"
    ).run()
    assert result["uncertainty"]["signals"]["missing_evidence"] is True
    assert result["status"] == "needs_human"
    blocked = [e for e in result["trace"] if e["event"] == "action_blocked"]
    assert blocked and blocked[0]["detail"]["action"] == "read_logs"
    # The blocked source is not silently replaced with simulated content.
    assert [e["source"] for e in result["evidence"]] == ["config"]


def test_distrusted_sources_trace_order_is_deterministic() -> None:
    src = (
        "goal G {\n  objective:\n    x\n"
        "  evidence:\n    require logs\n    distrust b_source\n    distrust a_source\n"
        "  output:\n    answer: string\n}\n"
    )
    result = _run(src)
    noted = [
        e["detail"]["source"]
        for e in result["trace"]
        if e["event"] == "source_distrusted"
    ]
    assert noted == ["b_source", "a_source"]  # declaration order, not set order


# -- trace ---------------------------------------------------------------------


def test_trace_covers_all_canonical_phases(triage_result: dict) -> None:
    started = [
        e["phase"] for e in triage_result["trace"] if e["event"] == "phase_started"
    ]
    assert started == list(EXECUTION_PHASES)
    seqs = [event["seq"] for event in triage_result["trace"]]
    assert seqs == sorted(seqs)  # append-only, ordered


def test_messages_are_recorded(triage_result: dict) -> None:
    assert "TriageGitHubIssue" in triage_result["messages"]["system"]
    assert "Objective:" in triage_result["messages"]["user"]
    built = [e for e in triage_result["trace"] if e["event"] == "messages_built"]
    assert built and built[0]["detail"]["system_chars"] > 0


def test_backend_response_is_recorded(triage_result: dict) -> None:
    response = triage_result["backend_response"]
    assert response["model"] == "intentflow-simulator"
    assert response["finish_reason"] == "stop"


def test_summary_is_flat_and_complete(triage_result: dict) -> None:
    summary = triage_result["summary"]
    assert summary["status"] == "completed"
    assert summary["verification_status"] == "passed"
    assert summary["uncertainty_status"] == "clear"
    assert summary["trace_id"] == triage_result["trace_id"]


def test_runtime_is_deterministic() -> None:
    first = _run(TRIAGE)
    second = _run(TRIAGE)
    assert first == second
