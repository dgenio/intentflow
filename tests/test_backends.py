"""Backend tests: backend selection, the OpenAI-compatible backend's
missing-config error, and message assembly from the compiled prompt plan.

None of these require a real API key or network access.
"""

from __future__ import annotations

import pytest

from intentflow.backends import (
    SimulatedCognition,
    SimulatorBackend,
    assemble_messages,
    make_backend,
    parse_model_json,
)
from intentflow.compiler import compile_goal
from intentflow.parser import parse_file


def _diagnose_plan() -> dict:
    program = parse_file("examples/diagnose.iflow")
    return compile_goal(program.goals[0], program.source_name).to_dict()


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


def test_assemble_messages_uses_named_blocks() -> None:
    plan = _diagnose_plan()
    evidence = [{"id": "E1", "source": "logs", "summary": "boom"}]
    system, user = assemble_messages(plan, evidence)
    assert "DiagnoseProductionIssue" in system
    assert "Objective:" in user
    assert "Collected evidence:" in user
    assert "E1" in user
    assert "JSON object" in user


def test_parse_model_json_clamps_and_filters_citations() -> None:
    evidence = [{"id": "E1"}]
    reply = (
        '```json\n{"hypotheses": [{"statement": "x", "confidence": 1.7, '
        '"citations": ["E1", "E99"]}], "proposed_fix": "do y"}\n```'
    )
    proposal = parse_model_json(reply, evidence)
    assert proposal.proposed_fix == "do y"
    hyp = proposal.hypotheses[0]
    assert hyp.raw_confidence == 1.0  # clamped into [0, 1]
    assert hyp.citations == ["E1"]  # E99 dropped (never collected)


def test_parse_model_json_normalizes_nonlist_citations() -> None:
    evidence = [{"id": "E1"}]
    # A model returning a bare string must not be iterated character-by-character.
    string_cite = parse_model_json(
        '{"hypotheses": [{"statement": "x", "confidence": 0.5, "citations": "E1"}]}',
        evidence,
    )
    assert string_cite.hypotheses[0].citations == ["E1"]
    # null / missing citations normalize to an empty list.
    null_cite = parse_model_json(
        '{"hypotheses": [{"statement": "x", "confidence": 0.5, "citations": null}]}',
        evidence,
    )
    assert null_cite.hypotheses[0].citations == []
