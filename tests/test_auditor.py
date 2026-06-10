"""Auditor tests: a run's trace is a witness that can be independently
checked against the program — and tampering is detected."""

from __future__ import annotations

import copy

import pytest

from intentflow.auditor import audit_document, audit_result
from intentflow.compiler import compile_program
from intentflow.parser import parse_file
from intentflow.runtime import GoalRuntime, run_pipeline


@pytest.fixture(scope="module")
def diagnose() -> tuple[dict, dict]:
    document = compile_program(parse_file("examples/production_diagnosis.iflow"))
    plan = document["goals"][0]
    result = GoalRuntime(plan, printer=None, workspace="examples/workspace").run()
    return document, result


def test_honest_run_is_conformant(diagnose: tuple[dict, dict]) -> None:
    document, result = diagnose
    assert result["status"] == "needs_human"  # by design (confidence < 0.7)
    report = audit_document(document, result)
    assert report["conformant"] is True
    assert report["violations"] == []


def test_completed_triage_run_is_conformant() -> None:
    document = compile_program(parse_file("examples/opensource_triage.iflow"))
    result = GoalRuntime(document["goals"][0], printer=None).run()
    assert result["status"] == "completed"
    assert audit_document(document, result)["conformant"] is True


def test_invoking_a_denied_action_is_detected(diagnose: tuple[dict, dict]) -> None:
    document, result = diagnose
    tampered = copy.deepcopy(result)
    plan = copy.deepcopy(document["goals"][0])
    plan["action_policy"]["denied"].append("read_logs")
    plan["action_policy"]["allowed"].remove("read_logs")
    report = audit_result(plan, tampered)
    assert report["conformant"] is False
    assert any(v["code"] == "A3" for v in report["violations"])


def test_gated_action_without_approval_is_detected(diagnose: tuple[dict, dict]) -> None:
    document, result = diagnose
    tampered = copy.deepcopy(result)
    tampered["trace"].append(
        {
            "seq": len(tampered["trace"]) + 1,
            "phase": "collect_evidence",
            "event": "tool_invoked",
            "detail": {"action": "deploy_change"},
        }
    )
    report = audit_document(document, tampered)
    assert any(v["code"] == "A2" for v in report["violations"])


def test_dangling_citation_is_detected(diagnose: tuple[dict, dict]) -> None:
    document, result = diagnose
    tampered = copy.deepcopy(result)
    tampered["citations"] = ["E99"]
    report = audit_document(document, tampered)
    assert any(v["code"] == "E1" for v in report["violations"])


def test_dropped_uncertainty_rule_is_detected(diagnose: tuple[dict, dict]) -> None:
    document, result = diagnose
    tampered = copy.deepcopy(result)
    tampered["trace"] = [
        e
        for e in tampered["trace"]
        if not (
            e["event"] == "rule_evaluated"
            and "confidence" in str(e["detail"].get("condition"))
        )
    ]
    report = audit_document(document, tampered)
    assert any(v["code"] in ("U1", "T1") for v in report["violations"])


def test_hidden_verification_failure_is_detected(diagnose: tuple[dict, dict]) -> None:
    document, result = diagnose
    tampered = copy.deepcopy(result)
    for event in tampered["trace"]:
        if event["event"] == "check_evaluated" and event["detail"]["id"] == "V1":
            event["detail"]["status"] = "fail"
    # result still claims V1 passed -> the cover-up must be flagged
    report = audit_document(document, tampered)
    assert any(v["code"] == "V1" for v in report["violations"])


def test_status_laundering_is_detected(diagnose: tuple[dict, dict]) -> None:
    # A run that escalated cannot be re-labelled 'completed'.
    document, result = diagnose
    tampered = copy.deepcopy(result)
    tampered["status"] = "completed"
    report = audit_document(document, tampered)
    assert any(v["code"] == "S1" for v in report["violations"])


def test_undeclared_output_is_detected(diagnose: tuple[dict, dict]) -> None:
    document, result = diagnose
    tampered = copy.deepcopy(result)
    tampered["outputs"]["sneaky_extra"] = "x"
    report = audit_document(document, tampered)
    assert any(v["code"] == "O1" for v in report["violations"])


def test_missing_required_output_is_detected(diagnose: tuple[dict, dict]) -> None:
    document, result = diagnose
    tampered = copy.deepcopy(result)
    del tampered["outputs"]["risk"]
    report = audit_document(document, tampered)
    assert any(v["code"] == "O1" for v in report["violations"])


def test_broken_trace_sequence_is_detected(diagnose: tuple[dict, dict]) -> None:
    document, result = diagnose
    tampered = copy.deepcopy(result)
    del tampered["trace"][3]
    report = audit_document(document, tampered)
    assert any(v["code"] == "T1" for v in report["violations"])


def test_pipeline_results_are_audited_per_stage() -> None:
    document = compile_program(parse_file("examples/incident_pipeline.iflow"))
    result = run_pipeline(document, "IncidentResponse", printer=None)
    report = audit_document(document, result)
    assert report["conformant"] is True
    assert [s["goal"] for s in report["stages"]] == [
        "DiagnoseIncident",
        "ProposeRemediation",
    ]
