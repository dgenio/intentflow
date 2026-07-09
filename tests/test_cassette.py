"""Cassette tests: record real model replies once, replay them in CI with no
keys — exercising the real parsing and governance path."""

from __future__ import annotations

import json

import pytest

from intentflow.auditor import audit_document
from intentflow.backends import (
    Cassette,
    RecordingBackend,
    RecordingChat,
    ReplayBackend,
    ReplayChat,
    make_backend,
)
from intentflow.backends import SimulatedCognition
from intentflow.compiler import compile_goal, compile_program
from intentflow.judges import LLMJudge, make_judge
from intentflow.parser import parse_file, parse_source
from intentflow.runtime import GoalRuntime

_JUDGED_SRC = (
    "goal G {\n  objective:\n    answer well\n"
    "  evidence:\n    require notes\n"
    "  verify:\n    the answer must be tasteful\n"
    "  output:\n    answer: string\n}\n"
)


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
    with pytest.raises(ValueError, match="requires a cassette"):
        make_backend("replay")


def test_make_backend_replay_with_cassette(tmp_path) -> None:
    cpath = tmp_path / "c.json"
    Cassette(cpath).save()
    backend = make_backend("replay", cpath)
    assert isinstance(backend, ReplayBackend)


def test_judge_record_then_replay_is_symmetric(tmp_path) -> None:
    cpath = tmp_path / "judge.cassette.json"
    reply = '{"passed": true, "rationale": "recorded verdict"}'
    calls = {"n": 0}

    def real_chat(system: str, user: str) -> str:
        calls["n"] += 1
        return reply

    recorded = LLMJudge(RecordingChat(real_chat, Cassette.load(cpath))).judge("r", {})
    assert calls["n"] == 1
    assert cpath.is_file()

    replayed = LLMJudge(ReplayChat(Cassette.load(cpath))).judge("r", {})
    assert replayed == recorded
    assert calls["n"] == 1  # the real judge was not called again on replay


def test_backend_and_judge_share_one_cassette(tmp_path) -> None:
    # A single cassette records both the cognition reply and the judge reply;
    # their request fingerprints never collide, so replay reproduces both.
    cpath = tmp_path / "shared.cassette.json"
    plan = compile_goal(parse_source(_JUDGED_SRC).goals[0]).to_dict()
    judge_reply = '{"passed": true, "rationale": "recorded"}'

    cass = Cassette.load(cpath)
    recorded = GoalRuntime(
        plan,
        backend=RecordingBackend(SimulatedCognition(), cass),
        judge=LLMJudge(RecordingChat(lambda s, u: judge_reply, cass)),
        printer=None,
    ).run()
    # One cassette file now holds a backend entry and a judge entry.
    assert len(Cassette.load(cpath).entries) == 2

    cass2 = Cassette.load(cpath)
    replayed = GoalRuntime(
        plan,
        backend=ReplayBackend(cass2),
        judge=LLMJudge(ReplayChat(cass2)),
        printer=None,
    ).run()
    assert replayed["outputs"] == recorded["outputs"]
    assert replayed["status"] == recorded["status"]
    assert replayed["verification"]["passed"] == recorded["verification"]["passed"]


def test_judge_replay_miss_is_reported_as_a_backend_error(tmp_path) -> None:
    # ReplayChat raises CassetteMiss; the judge's (disabled) retry policy wraps
    # it into BackendError, exactly as the ReplayBackend path does. The
    # explanatory message is preserved either way.
    from intentflow.backends import BackendError

    cpath = tmp_path / "empty.json"
    Cassette(cpath).save()
    with pytest.raises(BackendError, match="no recorded judge reply"):
        LLMJudge(ReplayChat(Cassette.load(cpath))).judge("unseen rule", {})


def test_make_judge_replay_reads_a_recorded_judge_cassette(tmp_path) -> None:
    cpath = tmp_path / "judge.json"
    rule, context = "be tasteful", {"outputs": {"answer": "hi"}}

    # Record a real judge's reply, then replay it through make_judge("replay").
    recording = LLMJudge(
        RecordingChat(
            lambda s, u: '{"passed": false, "rationale": "no"}',
            Cassette.load(cpath),
        )
    )
    recorded = recording.judge(rule, context)

    replayed = make_judge("replay", str(cpath)).judge(rule, context)
    assert replayed == recorded
    assert replayed.passed is False


def test_api_threads_run_cassette_to_the_judge(tmp_path) -> None:
    # Regression: IntentFlowProgram.run must thread its `cassette` to the judge,
    # exactly as it does for the backend, so a run is replayable (cognition +
    # verdicts). Before the fix `_judge` dropped the cassette, so `judge="replay"`
    # raised "the 'replay' judge requires a cassette path" even when one was
    # supplied. Now the cassette reaches the replay judge: with no recorded
    # verdict it misses on the rule (fail-closed BackendError) instead.
    from intentflow.api import IntentFlowProgram
    from intentflow.backends import BackendError

    cpath = tmp_path / "empty-judge.cassette.json"
    Cassette(cpath).save()  # a real cassette, but without this run's verdict
    program = IntentFlowProgram(parse_source(_JUDGED_SRC))

    with pytest.raises(BackendError, match="no recorded judge reply"):
        program.run(backend="simulate", judge="replay", cassette=cpath)


def test_recording_backend_propagates_usage_metadata(tmp_path) -> None:
    cpath = tmp_path / "c.json"
    doc = _doc()
    plan = doc["goals"][0]
    provider = _FakeProvider()
    provider.last_usage = {"input_tokens": 42, "output_tokens": 7}
    provider.last_finish_reason = "stop"
    backend = RecordingBackend(provider, Cassette.load(cpath))
    GoalRuntime(plan, backend=backend, printer=None,
                workspace="examples/workspace").run()
    assert provider.calls == 1
    assert backend.last_usage == {"input_tokens": 42, "output_tokens": 7}
    assert backend.last_finish_reason == "stop"
