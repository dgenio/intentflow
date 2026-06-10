"""Cognition backends: pluggable engines behind one narrow contract.

The runtime is a phase machine; cognition is a replaceable component. A
backend receives the compiled plan, the collected evidence, and the
assembled (system, user) messages, and returns a :class:`BackendResponse`:
the raw model text, any parsed JSON, the model name, latency, token usage,
and finish reason. Everything that makes the process *governed* — action
gating, calibration, uncertainty rules, verification, tracing — happens
outside the backend, so no backend (and no model) can opt out of governance.

Backends:

* :class:`SimulatedCognition` (``simulate``) — deterministic mock cognition.
  No network, no flakiness; it honors the goal's typed output schema so the
  whole pipeline (parse -> verify -> trace) is testable end to end.
* :class:`MockBackend` (``mock``) — canned responses or raised errors, for
  tests that need to drive specific runtime paths.
* :class:`AnthropicCognition` (``anthropic``) — a real Claude model.
* :class:`OpenAICompatibleCognition` (``openai``) — any OpenAI-compatible
  chat-completions endpoint (OpenAI, Azure, vLLM, Ollama-with-shim),
  configured purely through environment variables. It requests structured
  JSON output (``response_format``) when the endpoint supports it.
* :class:`ReplayBackend` (``replay``) — answers from a recorded cassette,
  never the network.

No test requires network access or API keys.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass
class BackendResponse:
    """What a cognition backend returns for one call."""

    raw_text: str
    parsed: dict[str, Any] | None
    model: str
    latency_ms: float
    usage: dict[str, int] | None = None
    finish_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CognitionBackend(Protocol):
    name: str

    def respond(
        self,
        plan: dict[str, Any],
        evidence: list[dict[str, Any]],
        system: str,
        user: str,
    ) -> BackendResponse:
        """Produce a response for the assembled messages."""
        ...


class BackendError(RuntimeError):
    """A backend failed to produce a response (network, provider, etc.)."""


def strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[len("json"):]
        text = text.strip()
    return text


def try_parse_json(text: str) -> dict[str, Any] | None:
    """Best-effort parse of a model reply into a JSON object."""
    try:
        payload = json.loads(strip_code_fences(text))
    except (json.JSONDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


#: The strict JSON shape every backend asks the model to emit, so the result
#: flows into the same verification/uncertainty machinery.
RESPONSE_SCHEMA_INSTRUCTION = (
    "Respond with ONLY a JSON object of the form:\n"
    '{"output": {<the declared output fields>}, "confidence": float, '
    '"citations": [str], "notes": str}\n'
    "Cite only evidence ids that appear above."
)


def assemble_messages(
    plan: dict[str, Any], evidence: list[dict[str, Any]]
) -> tuple[str, str]:
    """Turn the compiled prompt plan into a (system, user) message pair.

    The system message is the plan's ``system`` block; the user message
    concatenates the remaining governed blocks (objective, evidence, allowed
    and denied actions, verification, uncertainty, output) with the collected
    evidence inlined. Keeping the blocks separate up to this point is the
    point: each governance concern was an inspectable unit before it became a
    prompt.
    """
    blocks = {
        block["phase"]: block["instruction"]
        for block in plan["prompt_plan"]["blocks"]
    }
    system = blocks.get("system", "")
    evidence_json = json.dumps(evidence, indent=2)
    user_parts = [
        blocks.get("objective", ""),
        blocks.get("evidence", ""),
        f"Collected evidence:\n{evidence_json}",
        blocks.get("actions_allowed", ""),
        blocks.get("actions_denied", ""),
        blocks.get("verify", ""),
        blocks.get("uncertainty", ""),
        blocks.get("output", ""),
        RESPONSE_SCHEMA_INSTRUCTION,
    ]
    user = "\n\n".join(part for part in user_parts if part)
    return system, user


# ---------------------------------------------------------------------------
# Simulated cognition (the default backend)
# ---------------------------------------------------------------------------

#: The deterministic raw confidence the simulator reports.
SIMULATED_CONFIDENCE = 0.72


def _simulated_field_value(
    field: dict[str, Any], sources: list[str], citations: list[str]
) -> Any:
    """A deterministic, type-conformant value for one output field."""
    name, base = field["name"], field["base"]
    grounding = ", ".join(sources) if sources else "general reasoning"
    if base == "number":
        return SIMULATED_CONFIDENCE if name == "confidence" else 1.0
    if base == "boolean":
        return False
    remediation_field = any(
        token in name for token in ("fix", "response", "remediation", "recommendation")
    )
    if base == "markdown":
        text = (
            f"**[simulated]** {name.replace('_', ' ')} grounded in {grounding} "
            f"(citing {', '.join(citations) or 'no evidence'})."
        )
        if remediation_field:
            text += " Rollback: revert to the last known good state."
        return text
    if base == "list":
        if field.get("item_type") == "number":
            return [1.0]
        return [f"simulated-{name.replace('_', '-')}"]
    if base == "object":
        return {"note": f"[simulated] {name} derived from {grounding}"}
    text = f"[simulated] {name.replace('_', ' ')} based on {grounding}"
    if remediation_field:
        text += ". Rollback: revert to the last known good state."
    return text


class SimulatedCognition:
    """Deterministic mock cognition honoring the goal's typed output schema."""

    name = "simulate"
    model_name = "intentflow-simulator"

    def respond(
        self,
        plan: dict[str, Any],
        evidence: list[dict[str, Any]],
        system: str,
        user: str,
    ) -> BackendResponse:
        citations = [item["id"] for item in evidence if item.get("id")]
        sources = [item["source"] for item in evidence]
        output = {
            field["name"]: _simulated_field_value(field, sources, citations)
            for field in plan["output_schema"]["fields"]
        }
        payload = {
            "output": output,
            "confidence": SIMULATED_CONFIDENCE,
            "citations": citations,
            "notes": (
                "[simulated] deterministic response; confidence and content "
                "do not reflect real reasoning"
            ),
        }
        raw = json.dumps(payload, indent=2)
        return BackendResponse(
            raw_text=raw,
            parsed=payload,
            model=self.model_name,
            latency_ms=0.0,
            usage={
                "input_tokens": (len(system) + len(user)) // 4,
                "output_tokens": len(raw) // 4,
            },
            finish_reason="stop",
        )


class MockBackend:
    """A backend for tests: returns canned responses or raises.

    ``reply`` may be a dict (serialized to JSON), a raw string, or an
    exception instance (raised on call). A list of replies is consumed one
    per call.
    """

    name = "mock"

    def __init__(self, reply: Any = None, model: str = "mock-model") -> None:
        self._replies = list(reply) if isinstance(reply, list) else [reply]
        self._model = model
        self.calls: list[tuple[str, str]] = []

    def respond(
        self,
        plan: dict[str, Any],
        evidence: list[dict[str, Any]],
        system: str,
        user: str,
    ) -> BackendResponse:
        self.calls.append((system, user))
        reply = self._replies.pop(0) if len(self._replies) > 1 else self._replies[0]
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, dict):
            raw = json.dumps(reply)
            parsed: dict[str, Any] | None = reply
        else:
            raw = str(reply or "")
            parsed = try_parse_json(raw)
        return BackendResponse(
            raw_text=raw,
            parsed=parsed,
            model=self._model,
            latency_ms=0.0,
            usage=None,
            finish_reason="stop",
        )


# ---------------------------------------------------------------------------
# Real backends (chat-based)
# ---------------------------------------------------------------------------


class _ChatBackend:
    """Shared ``respond`` for backends built around ``complete(system, user)``.

    Subclasses set ``model_name`` and may fill ``last_usage`` /
    ``last_finish_reason`` inside ``complete``.
    """

    name = "chat"
    model_name = "unknown"
    last_usage: dict[str, int] | None = None
    last_finish_reason: str | None = None

    def complete(self, system: str, user: str) -> str:  # pragma: no cover - abstract
        raise NotImplementedError

    def respond(
        self,
        plan: dict[str, Any],
        evidence: list[dict[str, Any]],
        system: str,
        user: str,
    ) -> BackendResponse:
        start = time.perf_counter()
        try:
            text = self.complete(system, user)
        except (NotImplementedError, BackendError):
            raise
        except Exception as exc:  # provider/network errors become BackendError
            raise BackendError(f"backend {self.name!r} failed: {exc}") from exc
        latency = (time.perf_counter() - start) * 1000.0
        return BackendResponse(
            raw_text=text,
            parsed=try_parse_json(text),
            model=self.model_name,
            latency_ms=round(latency, 2),
            usage=self.last_usage,
            finish_reason=self.last_finish_reason,
        )


class AnthropicCognition(_ChatBackend):
    """Real cognition via the Claude API, behind the same contract."""

    name = "anthropic"

    def __init__(self, model: str = "claude-sonnet-4-6", max_tokens: int = 2000) -> None:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "the 'anthropic' backend requires the optional dependency: "
                "pip install 'intentflow[llm]'"
            ) from exc
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "the 'anthropic' backend requires ANTHROPIC_API_KEY to be set"
            )
        self._client = anthropic.Anthropic()
        self._model = model
        self.model_name = model
        self._max_tokens = max_tokens

    def complete(self, system: str, user: str) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        usage = getattr(response, "usage", None)
        if usage is not None:
            self.last_usage = {
                "input_tokens": getattr(usage, "input_tokens", 0),
                "output_tokens": getattr(usage, "output_tokens", 0),
            }
        self.last_finish_reason = getattr(response, "stop_reason", None)
        return "".join(
            block.text for block in response.content if block.type == "text"
        )


class OpenAICompatibleCognition(_ChatBackend):
    """Real cognition via any OpenAI-compatible chat-completions endpoint.

    Configured entirely through the environment so nothing here needs a key
    at import time:

    * ``OPENAI_API_KEY``  — required to make a request (clear error if absent)
    * ``OPENAI_BASE_URL`` — optional; point at Azure, vLLM, Ollama, etc.
    * ``OPENAI_MODEL``    — optional; defaults to ``gpt-4o-mini``

    Structured JSON output is requested via ``response_format`` when the
    endpoint supports it (falls back transparently when it does not).
    """

    name = "openai"

    def __init__(self, model: str | None = None, max_tokens: int = 2000) -> None:
        try:
            import openai  # noqa: F401
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "the 'openai' backend requires the optional dependency: "
                "pip install 'intentflow[openai]' (or: pip install openai)"
            ) from exc
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "the 'openai' backend requires OPENAI_API_KEY to be set "
                "(set OPENAI_BASE_URL/OPENAI_MODEL to target other providers)"
            )
        import openai

        self._client = openai.OpenAI(
            api_key=api_key, base_url=os.environ.get("OPENAI_BASE_URL") or None
        )
        self._model = model or os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"
        self.model_name = self._model
        self._max_tokens = max_tokens

    def complete(self, system: str, user: str) -> str:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                max_tokens=self._max_tokens,
                response_format={"type": "json_object"},
                messages=messages,
            )
        except Exception:
            # Some OpenAI-compatible servers reject response_format; retry
            # without it before giving up.
            response = self._client.chat.completions.create(
                model=self._model, max_tokens=self._max_tokens, messages=messages
            )
        usage = getattr(response, "usage", None)
        if usage is not None:
            self.last_usage = {
                "input_tokens": getattr(usage, "prompt_tokens", 0),
                "output_tokens": getattr(usage, "completion_tokens", 0),
            }
        choice = response.choices[0]
        self.last_finish_reason = getattr(choice, "finish_reason", None)
        return choice.message.content or ""


def provider_chat(name: str) -> Any:
    """Return a ``(system, user) -> text`` callable for a real provider,
    reused by the LLM judge. Raises the provider's clear error if it is not
    configured."""
    backend = make_backend(name)
    complete = getattr(backend, "complete", None)
    if complete is None:
        raise ValueError(f"backend {name!r} does not support chat completion")
    return complete


# ---------------------------------------------------------------------------
# Cassettes: record real model replies once, replay them forever (no keys)
# ---------------------------------------------------------------------------


class CassetteMiss(RuntimeError):
    """A replay run asked for an interaction the cassette never recorded."""


class Cassette:
    """A JSON file mapping a request fingerprint to a recorded raw reply.

    Cassettes let the real-backend *parsing and governance* path be tested in
    CI with recorded responses and no API key: record once against a live (or
    fake) provider, replay deterministically thereafter.
    """

    def __init__(self, path: str | Path, entries: dict[str, str] | None = None) -> None:
        self.path = Path(path)
        self.entries: dict[str, str] = entries or {}

    @classmethod
    def load(cls, path: str | Path) -> "Cassette":
        p = Path(path)
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            return cls(p, data.get("entries", {}))
        return cls(p, {})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"entries": self.entries}, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    @staticmethod
    def key(system: str, user: str) -> str:
        import hashlib

        return hashlib.sha256(f"{system}\x00{user}".encode("utf-8")).hexdigest()

    def get(self, system: str, user: str) -> str | None:
        return self.entries.get(self.key(system, user))

    def put(self, system: str, user: str, reply: str) -> None:
        self.entries[self.key(system, user)] = reply


class ReplayBackend(_ChatBackend):
    """A cognition backend that answers from a cassette — never the network."""

    name = "replay"
    model_name = "replay-cassette"

    def __init__(self, cassette: Cassette) -> None:
        self._cassette = cassette

    def complete(self, system: str, user: str) -> str:
        reply = self._cassette.get(system, user)
        if reply is None:
            raise CassetteMiss(
                f"no recorded reply in cassette {self._cassette.path} for this "
                "interaction; record it first with a real backend"
            )
        return reply


class RecordingBackend(_ChatBackend):
    """Wrap any backend with a ``complete`` method, persisting every raw reply
    to a cassette (replaying recorded ones to stay deterministic)."""

    def __init__(self, inner: Any, cassette: Cassette) -> None:
        self._inner = inner
        self._cassette = cassette
        self.name = f"record:{getattr(inner, 'name', 'backend')}"
        self.model_name = getattr(inner, "model_name", "unknown")

    def complete(self, system: str, user: str) -> str:
        cached = self._cassette.get(system, user)
        if cached is not None:
            return cached
        reply = self._inner.complete(system, user)
        self._cassette.put(system, user, reply)
        self._cassette.save()
        return reply


#: Discoverability aliases matching the conceptual backend names.
SimulatorBackend = SimulatedCognition
OpenAICompatibleBackend = OpenAICompatibleCognition

#: Backends selectable from the CLI's ``--backend`` flag.
BACKENDS: dict[str, type] = {
    "simulate": SimulatedCognition,
    "mock": MockBackend,
    "anthropic": AnthropicCognition,
    "openai": OpenAICompatibleCognition,
}


def make_backend(name: str, cassette: str | Path | None = None) -> CognitionBackend:
    """Build a backend by CLI name. Real backends raise a clear
    :class:`RuntimeError` if their optional dependency or credentials are
    missing — never a cryptic import or attribute error.

    ``replay`` answers from ``cassette`` (no credentials needed). For any real
    backend, passing ``cassette`` wraps it in a :class:`RecordingBackend` so
    its replies are captured for later replay.
    """
    if name == "replay":
        if cassette is None:
            raise ValueError("the 'replay' backend requires a cassette path")
        return ReplayBackend(Cassette.load(cassette))
    try:
        factory = BACKENDS[name]
    except KeyError:
        raise ValueError(
            f"unknown backend {name!r}; expected one of: "
            + ", ".join(sorted(BACKENDS) + ["replay"])
        )
    backend = factory()
    if cassette is not None and hasattr(backend, "complete"):
        return RecordingBackend(backend, Cassette.load(cassette))
    return backend
