"""Cassette tests: record real model replies once, replay them in CI with no
keys — exercising the real parsing and governance path."""

from __future__ import annotations

import json

from intentflow.auditor import audit_document
from intentflow.backends import (
    Cassette,
    RecordingBackend,
    ReplayBackend,
    make_backend,
)
from intentflow.compiler import compile_program
from intentflow.parser import parse_file
from intentflow.runtime import GoalRuntime


class _FakeProvider:
    """Stands in for a real OpenAI/Anthropic backend (has .complete)."""

    name = "fake"
    model_name = "fake-model"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, system: str, user: str) -> str:
        self.calls += 1
        return json.dumps(
            {
                "output": {
                    "root_cause": "OOM from unbounded retry queue",
                    "confidence": 0.82,
                    "recommended_fix": "cap the queue. Rollback: revert.",
                    "risk": "low",
                },
                "confidence": 0.82,
                "citations": ["E1"],
            }
        )


def _doc():
    return compile_program(parse_file("examples/production_diagnosis.iflow"))


def test_record_then_replay_is_symmetric(tmp_path) -> None:
    cpath = tmp_path / "diagnose.cassette.json"
    doc = _doc()
    plan = doc["goals"][0]

    provider = _FakeProvider()
    rec = RecordingBackend(provider, Cassette.load(cpath))
    recorded = GoalRuntime(plan, backend=rec, printer=None,
                           workspace="examples/workspace").run()
    assert provider.calls == 1
    assert cpath.is_file()

    replay = ReplayBackend(Cassette.load(cpath))
    replayed = GoalRuntime(plan, backend=replay, printer=None,
                           workspace="examples/workspace").run()
    assert replayed["outputs"] == recorded["outputs"]
    assert replayed["status"] == recorded["status"]
    assert audit_document(doc, replayed)["conformant"] is True


def test_recording_backend_does_not_recall_provider_on_replay(tmp_path) -> None:
    cpath = tmp_path / "c.json"
    doc = _doc()
    plan = doc["goals"][0]
    provider = _FakeProvider()
    backend = RecordingBackend(provider, Cassette.load(cpath))
    GoalRuntime(plan, backend=backend, printer=None, workspace="examples/workspace").run()
    GoalRuntime(plan, backend=backend, printer=None, workspace="examples/workspace").run()
    assert provider.calls == 1  # second run served from the cassette


def test_replay_miss_is_a_backend_error_status(tmp_path) -> None:
    cpath = tmp_path / "empty.json"
    backend = ReplayBackend(Cassette.load(cpath))
    plan = _doc()["goals"][0]
    result = GoalRuntime(plan, backend=backend, printer=None).run()
    assert result["status"] == "backend_error"
    assert "no recorded reply" in result["backend_error"]


def test_make_backend_replay_requires_cassette() -> None:
    import pytest

    with pytest.raises(ValueError, match="requires a cassette"):
        make_backend("replay")


def test_make_backend_replay_with_cassette(tmp_path) -> None:
    cpath = tmp_path / "c.json"
    Cassette(cpath).save()
    backend = make_backend("replay", cpath)
    assert isinstance(backend, ReplayBackend)


def test_recording_backend_propagates_usage_metadata(tmp_path) -> None:
    cpath = tmp_path / "c.json"
    doc = _doc()
    plan = doc["goals"][0]
    provider = _FakeProvider()
    provider.last_usage = {"input_tokens": 42, "output_tokens": 7}
    provider.last_finish_reason = "stop"
    backend = RecordingBackend(provider, Cassette.load(cpath))
    result = GoalRuntime(plan, backend=backend, printer=None,
                         workspace="examples/workspace").run()
    assert provider.calls == 1
    assert backend.last_usage == {"input_tokens": 42, "output_tokens": 7}
    assert backend.last_finish_reason == "stop"
