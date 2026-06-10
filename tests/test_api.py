"""Embedding API tests: load and run programs from Python, and register
Python functions as governed actions."""

from __future__ import annotations

import pytest

import intentflow
from intentflow import load, load_source
from intentflow.auditor import audit_document


TRIAGE = "examples/opensource_triage.iflow"


def test_load_file_and_run() -> None:
    program = load(TRIAGE)
    assert program.goal_names() == ["TriageGitHubIssue"]
    result = program.run(backend="simulate")
    assert result["status"] == "completed"
    assert set(result["outputs"]) == {
        "summary", "likely_cause", "confidence", "suggested_response",
        "proposed_labels",
    }


def test_load_source_inline() -> None:
    program = load_source(
        "goal G {\n  objective:\n    x\n  output:\n    answer: string\n}\n",
        name="inline",
    )
    assert program.source_name == "inline"
    result = program.run()
    assert result["status"] == "completed"
    assert "answer" in result["outputs"]


def test_validation_failure_is_a_status_not_an_exception() -> None:
    program = load_source("goal G {\n  output:\n    a: string\n}\n")
    result = program.run()
    assert result["status"] == "failed_validation"
    assert any(d["code"] == "IFLOW001" for d in result["diagnostics"])


def test_validate_compile_inspect_explain_surface() -> None:
    program = load(TRIAGE)
    diagnostics = program.validate()
    assert [d for d in diagnostics if d.severity == "error"] == []
    assert program.compile()["goals"][0]["goal"] == "TriageGitHubIssue"
    assert program.inspect()["goals"][0]["approval_gated_actions"] == ["post_comment"]
    explanation = program.explain()["goals"][0]
    assert "triage" in explanation["purpose"]


def test_run_unknown_goal_errors() -> None:
    with pytest.raises(ValueError, match="unknown goal"):
        load(TRIAGE).run(goal="Nope")


def test_registered_python_tool_runs_through_the_gate() -> None:
    calls = []

    def lookup(source: str) -> str:
        calls.append(source)
        return "user is on the enterprise plan"

    src = (
        "goal ResolveTicket {\n  objective:\n    resolve the ticket\n"
        "  evidence:\n    require user_record\n"
        "  actions:\n    allow lookup_user\n"
        "  output:\n    answer: string\n}\n"
    )
    program = load_source(src)
    program.register_tool("lookup_user", serves=("user_record",), handler=lookup)
    result = program.run()
    # The Python handler actually ran (through the gate) and produced evidence.
    assert calls == ["user_record"]
    assert result["evidence"][0]["origin"] == "tool:lookup_user"
    assert "enterprise plan" in result["evidence"][0]["summary"]


def test_registered_tool_blocked_when_not_allowed() -> None:
    def lookup(source: str) -> str:
        return "secret"

    # Goal requires the evidence but does NOT allow the action -> gate blocks
    # it regardless of registration; the evidence stays uncollected.
    src = (
        "goal Locked {\n  objective:\n    x\n"
        "  evidence:\n    require user_record\n"
        "  actions:\n    allow something_else\n"
        "  output:\n    answer: string\n}\n"
    )
    program = load_source(src).register_tool(
        "lookup_user", serves=("user_record",), handler=lookup
    )
    result = program.run()
    assert result["evidence"] == []
    assert result["uncertainty"]["signals"]["missing_evidence"] is True
    assert any(e["event"] == "action_blocked" for e in result["trace"])


def test_run_with_judge_and_signed_trace_audits() -> None:
    program = load(TRIAGE)
    document = program.compile()
    result = program.run(judge="simulate", sign_key=b"k")
    assert result["status"] == "completed"
    assert audit_document(document, result, sign_key=b"k")["conformant"] is True


def test_run_pipeline_from_python() -> None:
    program = load("examples/incident_pipeline.iflow")
    assert program.pipeline_names() == ["IncidentResponse"]
    result = program.run_pipeline("IncidentResponse")
    assert [s["goal"] for s in result["stages"]] == [
        "DiagnoseIncident", "ProposeRemediation",
    ]


def test_public_api_exports() -> None:
    for name in ("load", "load_source", "IntentFlowProgram", "Judge",
                 "WebhookApprover", "Cassette", "ReplayBackend", "MockBackend",
                 "BackendResponse", "Diagnostic", "analyze_program",
                 "execute_program", "default_registry"):
        assert hasattr(intentflow, name), name
