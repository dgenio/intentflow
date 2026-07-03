"""Backend tests: the BackendResponse contract, simulator determinism, the
mock backend, message assembly, and clear errors for missing configuration.

None of these require a real API key or network access.
"""

from __future__ import annotations

import json

import pytest

from intentflow.backends import (
    AnthropicCognition,
    BackendError,
    BackendResponse,
    MockBackend,
    OpenAICompatibleCognition,
    SimulatedCognition,
    SimulatorBackend,
    assemble_messages,
    make_backend,
    try_parse_json,
)
from intentflow.compiler import compile_goal
from intentflow.parser import parse_file
from intentflow.reliability import HTTPTimeout, RetryPolicy


class _Namespace:
    """A tiny attribute bag, standing in for an SDK response object."""

    def __init__(self, **kw) -> None:
        self.__dict__.update(kw)


class _FakeAnthropicClient:
    """Captures create() kwargs and returns an anthropic-shaped response."""

    def __init__(self, text: str = '{"output": {}, "confidence": 0.5}') -> None:
        self._text = text
        self.calls: list[dict] = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Namespace(
            content=[_Namespace(type="text", text=self._text)],
            usage=_Namespace(input_tokens=11, output_tokens=7),
            stop_reason="end_turn",
        )


class _FakeOpenAIClient:
    """Captures create() kwargs and returns an openai-shaped response."""

    def __init__(self, text: str = '{"output": {}, "confidence": 0.5}') -> None:
        self._text = text
        self.calls: list[dict] = []
        self.chat = _Namespace(completions=self)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Namespace(
            choices=[
                _Namespace(
                    message=_Namespace(content=self._text), finish_reason="stop"
                )
            ],
            usage=_Namespace(prompt_tokens=11, completion_tokens=7),
        )


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


def test_try_parse_json_strips_uppercase_json_fence() -> None:
    assert try_parse_json('```JSON\n{"a": 1}\n```') == {"a": 1}
    assert try_parse_json('```Json\n{"a": 1}\n```') == {"a": 1}


def test_try_parse_json_recovers_object_wrapped_in_prose() -> None:
    reply = 'Sure! Here is the result:\n{"a": 1, "b": [2, 3]}\nHope that helps.'
    assert try_parse_json(reply) == {"a": 1, "b": [2, 3]}


def test_try_parse_json_handles_nested_braces_and_strings() -> None:
    reply = 'noise {"outer": {"inner": "a } brace in a string"}} trailing'
    assert try_parse_json(reply) == {"outer": {"inner": "a } brace in a string"}}


def test_try_parse_json_returns_none_for_unrecoverable_text() -> None:
    assert try_parse_json("no json here at all") is None
    assert try_parse_json("{unterminated") is None


# -- real backends via injected fake clients (assemble -> call -> parse) -----


def test_anthropic_backend_assembles_calls_and_parses() -> None:
    plan = _triage_plan()
    system, user = assemble_messages(plan, EVIDENCE)
    client = _FakeAnthropicClient('{"output": {"summary": "s"}, "confidence": 0.6}')
    backend = AnthropicCognition(client=client, timeout=HTTPTimeout(read=20.0))

    response = backend.respond(plan, EVIDENCE, system, user)

    assert client.calls[0]["system"] == system
    assert client.calls[0]["messages"] == [{"role": "user", "content": user}]
    assert client.calls[0]["timeout"] == HTTPTimeout(read=20.0).as_sdk()
    assert response.parsed == {"output": {"summary": "s"}, "confidence": 0.6}
    assert response.usage == {"input_tokens": 11, "output_tokens": 7}
    assert response.finish_reason == "end_turn"
    assert response.model == "claude-sonnet-4-6"


def test_openai_backend_assembles_calls_and_parses() -> None:
    plan = _triage_plan()
    system, user = assemble_messages(plan, EVIDENCE)
    client = _FakeOpenAIClient('{"output": {"summary": "s"}, "confidence": 0.6}')
    backend = OpenAICompatibleCognition(
        model="local-model", client=client, timeout=HTTPTimeout(read=20.0)
    )

    response = backend.respond(plan, EVIDENCE, system, user)

    sent = client.calls[0]
    assert sent["model"] == "local-model"
    assert sent["messages"][0] == {"role": "system", "content": system}
    assert sent["timeout"] == HTTPTimeout(read=20.0).as_sdk()
    assert response.parsed == {"output": {"summary": "s"}, "confidence": 0.6}
    assert response.usage == {"input_tokens": 11, "output_tokens": 7}
    assert response.finish_reason == "stop"


def test_openai_backend_retries_without_response_format_when_rejected() -> None:
    plan = _triage_plan()
    system, user = assemble_messages(plan, EVIDENCE)

    class _PickyClient(_FakeOpenAIClient):
        def create(self, **kwargs):
            if "response_format" in kwargs:
                raise ValueError("response_format unsupported")
            return super().create(**kwargs)

    client = _PickyClient()
    backend = OpenAICompatibleCognition(client=client)
    response = backend.respond(plan, EVIDENCE, system, user)
    assert response.parsed is not None
    assert len(client.calls) == 1  # only the fallback call was recorded


def test_chat_backend_retries_transient_failures_then_succeeds() -> None:
    plan = _triage_plan()
    system, user = assemble_messages(plan, EVIDENCE)

    class _FlakyOnce(_FakeAnthropicClient):
        def __init__(self) -> None:
            super().__init__()
            self._raised = False

        def create(self, **kwargs):
            if not self._raised:
                self._raised = True
                raise ConnectionError("reset by peer")
            return super().create(**kwargs)

    policy = RetryPolicy(max_attempts=3, sleep=lambda _: None)
    backend = AnthropicCognition(client=_FlakyOnce(), retry_policy=policy)
    response = backend.respond(plan, EVIDENCE, system, user)
    assert response.parsed is not None


def test_chat_backend_fails_closed_after_exhausting_retries() -> None:
    plan = _triage_plan()
    system, user = assemble_messages(plan, EVIDENCE)

    class _Down(_FakeAnthropicClient):
        def create(self, **kwargs):
            raise ConnectionError("provider down")

    policy = RetryPolicy(max_attempts=2, sleep=lambda _: None)
    backend = AnthropicCognition(client=_Down(), retry_policy=policy)
    with pytest.raises(BackendError, match="failed after 2 attempt"):
        backend.respond(plan, EVIDENCE, system, user)
