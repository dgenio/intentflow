"""Cassette tests: record real model replies once, replay them in CI with no
keys — exercising the real parsing and governance path."""

from __future__ import annotations

import json

import pytest

from intentflow.auditor import audit_document
from intentflow.backends import (
    Cassette,
    CassetteMiss,
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

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, system: str, user: str) -> str:
        self.calls += 1
        return json.dumps(
            {
                "hypotheses": [
                    {"statement": "OOM", "confidence": 0.82, "citations": ["E1"]}
                ],
                "proposed_fix": "raise limit. Rollback: revert.",
            }
        )


def _doc():
    return compile_program(parse_file("examples/diagnose.iflow"))


def test_record_then_replay_is_symmetric(tmp_path) -> None:
    cpath = tmp_path / "diagnose.cassette.json"
    doc = _doc()
    plan = doc["plans"][0]

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
    assert audit_document(doc, replayed)["conformant"] is True


def test_recording_backend_does_not_recall_provider_on_replay(tmp_path) -> None:
    cpath = tmp_path / "c.json"
    doc = _doc()
    plan = doc["plans"][0]
    provider = _FakeProvider()
    backend = RecordingBackend(provider, Cassette.load(cpath))
    GoalRuntime(plan, backend=backend, printer=None, workspace="examples/workspace").run()
    GoalRuntime(plan, backend=backend, printer=None, workspace="examples/workspace").run()
    assert provider.calls == 1  # second run served from the cassette


def test_replay_miss_raises(tmp_path) -> None:
    cpath = tmp_path / "empty.json"
    backend = ReplayBackend(Cassette.load(cpath))
    plan = _doc()["plans"][0]
    with pytest.raises(CassetteMiss):
        GoalRuntime(plan, backend=backend, printer=None).run()


def test_make_backend_replay_requires_cassette() -> None:
    with pytest.raises(ValueError, match="requires a cassette"):
        make_backend("replay")


def test_make_backend_replay_with_cassette(tmp_path) -> None:
    cpath = tmp_path / "c.json"
    Cassette(cpath).save()
    backend = make_backend("replay", cpath)
    assert isinstance(backend, ReplayBackend)
