"""Backend tests: the BackendResponse contract, simulator determinism, the
mock backend, message assembly, and clear errors for missing configuration.

None of these require a real API key or network access.
"""

from __future__ import annotations

import json

import pytest

from intentflow.backends import (
    BackendResponse,
    MockBackend,
    SimulatedCognition,
    SimulatorBackend,
    assemble_messages,
    make_backend,
    try_parse_json,
)
from intentflow.compiler import compile_goal
from intentflow.parser import parse_file


def _triage_plan() -> dict:
    program = parse_file("examples/opensource_triage.iflow")
    return compile_goal(program.goals[0], program.source_name).to_dict()


EVIDENCE = [
    {"id": "E1", "source": "issue_body", "summary": "crash on startup"},
    {"id": "E2", "source": "comments", "summary": "repro attached"},
]


def test_simulate_backend_is_the_default_factory() -> None:
    assert isinstance(make_backend("simulate"), SimulatedCognition)
    assert SimulatorBackend is SimulatedCognition


def test_unknown_backend_name_is_a_value_error() -> None:
    with pytest.raises(ValueError, match="unknown backend"):
        make_backend("telepathy")


def test_openai_backend_missing_key_raises_clear_error(monkeypatch) -> None:
    pytest.importorskip("openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        make_backend("openai")


def test_openai_backend_without_package_raises_clear_error(monkeypatch) -> None:
    import importlib

    if importlib.util.find_spec("openai") is not None:
        pytest.skip("openai is installed; cannot test the missing-package path")
    with pytest.raises(RuntimeError, match="pip install"):
        make_backend("openai")


def test_simulator_returns_a_full_backend_response() -> None:
    plan = _triage_plan()
    system, user = assemble_messages(plan, EVIDENCE)
    response = SimulatedCognition().respond(plan, EVIDENCE, system, user)
    assert isinstance(response, BackendResponse)
    assert response.model == "intentflow-simulator"
    assert response.finish_reason == "stop"
    assert response.latency_ms == 0.0
    assert response.usage["input_tokens"] > 0
    assert json.loads(response.raw_text) == response.parsed


def test_simulator_honors_the_typed_output_schema() -> None:
    plan = _triage_plan()
    system, user = assemble_messages(plan, EVIDENCE)
    parsed = SimulatedCognition().respond(plan, EVIDENCE, system, user).parsed
    output = parsed["output"]
    assert set(output) == {
        "summary", "likely_cause", "confidence", "suggested_response",
        "proposed_labels",
    }
    assert isinstance(output["summary"], str)
    assert isinstance(output["confidence"], float)
    assert isinstance(output["proposed_labels"], list)
    assert all(isinstance(x, str) for x in output["proposed_labels"])
    assert parsed["citations"] == ["E1", "E2"]
    assert 0.0 <= parsed["confidence"] <= 1.0


def test_simulator_is_deterministic() -> None:
    plan = _triage_plan()
    system, user = assemble_messages(plan, EVIDENCE)
    first = SimulatedCognition().respond(plan, EVIDENCE, system, user)
    second = SimulatedCognition().respond(plan, EVIDENCE, system, user)
    assert first == second


def test_mock_backend_returns_canned_reply() -> None:
    reply = {"output": {"answer": "42"}, "confidence": 0.9, "citations": []}
    backend = MockBackend(reply)
    response = backend.respond({}, [], "sys", "usr")
    assert response.parsed == reply
    assert backend.calls == [("sys", "usr")]


def test_mock_backend_can_raise() -> None:
    backend = MockBackend(RuntimeError("provider down"))
    with pytest.raises(RuntimeError, match="provider down"):
        backend.respond({}, [], "s", "u")


def test_assemble_messages_uses_named_blocks() -> None:
    plan = _triage_plan()
    system, user = assemble_messages(plan, EVIDENCE)
    assert "TriageGitHubIssue" in system
    assert "Objective:" in user
    assert "Collected evidence:" in user
    assert "E1" in user
    assert "JSON object" in user
    assert "close_issue" in user  # denied actions are part of the interaction


def test_try_parse_json_strips_code_fences() -> None:
    assert try_parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert try_parse_json('{"a": 1}') == {"a": 1}
    assert try_parse_json("not json at all") is None
    assert try_parse_json("[1, 2]") is None  # must be an object
