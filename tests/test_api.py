"""Embedding API tests: load and run programs from Python, and register
Python functions as governed actions."""

from __future__ import annotations

import pytest

import intentflow
from intentflow import load, load_source
from intentflow.auditor import audit_document


DIAGNOSE = "examples/diagnose.iflow"


def test_load_file_and_run() -> None:
    program = load(DIAGNOSE)
    assert program.goal_names() == ["DiagnoseProductionIssue"]
    result = program.run(backend="simulate")
    assert result["status"] == "completed"
    assert set(result["outputs"]) == {
        "root_cause", "confidence", "recommended_fix", "risk",
    }


def test_load_source_inline() -> None:
    program = load_source(
        "goal G {\n  objective:\n    x\n  output:\n    answer\n}\n", name="inline"
    )
    assert program.source_name == "inline"
    result = program.run()
    assert result["status"] == "completed"
    assert "answer" in result["outputs"]


def test_validate_compile_inspect_surface() -> None:
    program = load(DIAGNOSE)
    assert [d for d in program.validate() if d.level == "error"] == []
    assert program.compile()["plans"][0]["goal"] == "DiagnoseProductionIssue"
    assert program.inspect()["goals"][0]["approval_gated_actions"] == ["deploy_change"]


def test_run_unknown_goal_errors() -> None:
    with pytest.raises(ValueError, match="unknown goal"):
        load(DIAGNOSE).run(goal="Nope")


def test_registered_python_tool_runs_through_the_gate() -> None:
    calls = []

    def lookup(source: str) -> str:
        calls.append(source)
        return "user is on the enterprise plan"

    src = (
        "goal ResolveTicket {\n  objective:\n    resolve the ticket\n"
        "  evidence:\n    require user_record\n"
        "  actions:\n    allow lookup_user\n"
        "  output:\n    answer\n}\n"
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
    # it regardless of registration, falling back to simulated evidence.
    src = (
        "goal Locked {\n  objective:\n    x\n"
        "  evidence:\n    require user_record\n"
        "  actions:\n    allow something_else\n"
        "  output:\n    answer\n}\n"
    )
    program = load_source(src).register_tool(
        "lookup_user", serves=("user_record",), handler=lookup
    )
    result = program.run()
    assert result["evidence"][0]["origin"] == "simulated"
    assert any(e["event"] == "action_blocked" for e in result["trace"])


def test_run_with_judge_and_signed_trace_audits() -> None:
    program = load(DIAGNOSE)
    document = program.compile()
    result = program.run(
        workspace="examples/workspace", judge="simulate", sign_key=b"k"
    )
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
                 "WebhookApprover", "Cassette", "ReplayBackend"):
        assert hasattr(intentflow, name)
