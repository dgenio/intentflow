"""Cognition backends: pluggable engines that propose hypotheses for a plan.

The runtime is a phase machine; cognition is a replaceable component behind
one narrow contract: given a plan and collected evidence, return a
:class:`Proposal`. Everything else — action gating, calibration, uncertainty
rules, verification, tracing — happens *outside* the backend, so no backend
(and no model) can opt out of governance.

Backends:

* :class:`SimulatedCognition` (``SimulatorBackend``) — deterministic mock
  cognition. No network, no flakiness; used to test the language's control
  structure end to end and as the conformance reference for real backends.
* :class:`AnthropicCognition` — drives a real Claude model through the
  staged prompt plan. Requires the optional ``anthropic`` package and an
  ``ANTHROPIC_API_KEY``.
* :class:`OpenAICompatibleCognition` (``OpenAICompatibleBackend``) — drives
  any OpenAI-compatible chat-completions endpoint (OpenAI, Azure, local
  servers such as vLLM/Ollama-with-OpenAI-shim). Configured purely through
  environment variables so tests never need a real key.

The contract is deliberately provider-agnostic: a backend turns the compiled
prompt plan into a model call and returns a :class:`Proposal`. Adding a new
provider (Anthropic, OpenAI-compatible, or a local model) is one class; none
of them can opt out of the governance that surrounds them.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass
class Hypothesis:
    """A candidate explanation with self-reported (raw) confidence.

    ``confidence`` starts equal to ``raw_confidence``; the runtime replaces
    it with a calibrated value before any uncertainty rule fires.
    """

    hypothesis_id: str
    statement: str
    raw_confidence: float
    confidence: float
    citations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.hypothesis_id,
            "statement": self.statement,
            "raw_confidence": round(self.raw_confidence, 3),
            "confidence": round(self.confidence, 3),
            "citations": list(self.citations),
        }


@dataclass
class Proposal:
    """What a cognition backend returns: hypotheses plus a remediation text
    that machine verification checks (e.g. ``requires_phrase``) run against."""

    hypotheses: list[Hypothesis]
    proposed_fix: str | None = None


class CognitionBackend(Protocol):
    name: str

    def propose(self, plan: dict[str, Any], evidence: list[dict[str, Any]]) -> Proposal:
        """Propose hypotheses grounded in the collected evidence."""
        ...


#: Deterministic raw confidences for simulated hypotheses, in order. The
#: first two are close together on purpose so 'competing hypotheses'
#: uncertainty rules have something to react to in demos and tests.
_MOCK_CONFIDENCES: tuple[float, ...] = (0.68, 0.61, 0.34, 0.22)


class SimulatedCognition:
    """Deterministic mock cognition: one hypothesis per evidence item."""

    name = "simulate"

    def propose(self, plan: dict[str, Any], evidence: list[dict[str, Any]]) -> Proposal:
        sources = evidence or [{"id": None, "source": "general reasoning"}]
        hypotheses: list[Hypothesis] = []
        count = max(1, min(len(sources), len(_MOCK_CONFIDENCES)))
        for i in range(count):
            source = sources[i % len(sources)]
            raw = _MOCK_CONFIDENCES[i]
            hypotheses.append(
                Hypothesis(
                    hypothesis_id=f"H{i + 1}",
                    statement=(
                        "[simulated] the objective is most plausibly explained "
                        f"by signals found in {source['source']}"
                    ),
                    raw_confidence=raw,
                    confidence=raw,
                    citations=[source["id"]] if source["id"] else [],
                )
            )
        top = hypotheses[0]
        return Proposal(
            hypotheses=hypotheses,
            proposed_fix=(
                f"[simulated] apply targeted fix for {top.hypothesis_id}. "
                "Rollback: revert to last known good config/commit."
            ),
        )


#: The strict JSON shape every real backend asks the model to emit, so the
#: result flows into the same calibration/uncertainty/verification machinery.
_RESPONSE_SCHEMA_INSTRUCTION = (
    "Respond with ONLY a JSON object of the form:\n"
    '{"hypotheses": [{"statement": str, "confidence": float, '
    '"citations": [str]}], "proposed_fix": str}\n'
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
    steps = {step["phase"]: step["instruction"] for step in plan["prompt_plan"]}
    system = steps.get("system", "")
    evidence_json = json.dumps(evidence, indent=2)
    user_parts = [
        steps.get("objective", ""),
        steps.get("evidence", ""),
        f"Collected evidence:\n{evidence_json}",
        steps.get("actions_allowed", ""),
        steps.get("actions_denied", ""),
        steps.get("verify", ""),
        steps.get("uncertainty", ""),
        steps.get("output", ""),
        _RESPONSE_SCHEMA_INSTRUCTION,
    ]
    user = "\n\n".join(part for part in user_parts if part)
    return system, user


def parse_model_json(
    text: str, evidence: list[dict[str, Any]]
) -> Proposal:
    """Parse a model's JSON reply into a :class:`Proposal`, clamping
    confidences to [0, 1] and dropping citations to evidence ids that were
    never collected."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[len("json"):]
        text = text.strip()
    payload = json.loads(text)
    valid_ids = {item["id"] for item in evidence}
    hypotheses = []
    for i, hyp in enumerate(payload.get("hypotheses", []), start=1):
        raw = min(1.0, max(0.0, float(hyp.get("confidence", 0.0))))
        hypotheses.append(
            Hypothesis(
                hypothesis_id=f"H{i}",
                statement=str(hyp.get("statement", "")),
                raw_confidence=raw,
                confidence=raw,
                citations=[c for c in hyp.get("citations", []) if c in valid_ids],
            )
        )
    return Proposal(hypotheses=hypotheses, proposed_fix=payload.get("proposed_fix"))


class AnthropicCognition:
    """Real cognition via the Claude API, behind the same contract.

    The compiled prompt plan's ``system`` block becomes the system prompt;
    the remaining governed blocks become the user turn. The model is asked
    for strict JSON so hypotheses, confidences, and citations flow into the
    same calibration, uncertainty, and verification machinery as simulated
    runs.
    """

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
        self._max_tokens = max_tokens

    def complete(self, system: str, user: str) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(
            block.text for block in response.content if block.type == "text"
        )

    def propose(self, plan: dict[str, Any], evidence: list[dict[str, Any]]) -> Proposal:
        system, user_message = assemble_messages(plan, evidence)
        return parse_model_json(self.complete(system, user_message), evidence)


class OpenAICompatibleCognition:
    """Real cognition via any OpenAI-compatible chat-completions endpoint.

    Configured entirely through the environment so nothing here needs a key
    at import or construction time in tests until a call is actually made:

    * ``OPENAI_API_KEY``  — required to make a request (clear error if absent)
    * ``OPENAI_BASE_URL`` — optional; point at Azure, vLLM, Ollama, etc.
    * ``OPENAI_MODEL``    — optional; defaults to ``gpt-4o-mini``

    The same staged prompt plan drives the call, and the reply is parsed into
    the same :class:`Proposal` shape, so governance is identical to every
    other backend.
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
        self._max_tokens = max_tokens

    def complete(self, system: str, user: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            max_tokens=self._max_tokens,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content or ""

    def propose(self, plan: dict[str, Any], evidence: list[dict[str, Any]]) -> Proposal:
        system, user_message = assemble_messages(plan, evidence)
        return parse_model_json(self.complete(system, user_message), evidence)


def provider_chat(name: str) -> "Any":
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

    Cassettes let the OpenAI/Anthropic *parsing and governance* path be tested
    in CI with real recorded responses and no API key: record once against a
    live (or fake) provider, replay deterministically thereafter.
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


class ReplayBackend:
    """A cognition backend that answers from a cassette — never the network.

    Used in tests/CI to exercise the real parsing and governance path against
    recorded responses without any credentials.
    """

    name = "replay"

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

    def propose(self, plan: dict[str, Any], evidence: list[dict[str, Any]]) -> Proposal:
        system, user = assemble_messages(plan, evidence)
        return parse_model_json(self.complete(system, user), evidence)


class RecordingBackend:
    """Wrap any backend with a ``complete`` method, persisting every raw reply
    to a cassette (replaying recorded ones to stay deterministic)."""

    def __init__(self, inner: Any, cassette: Cassette) -> None:
        self._inner = inner
        self._cassette = cassette
        self.name = f"record:{getattr(inner, 'name', 'backend')}"

    def complete(self, system: str, user: str) -> str:
        cached = self._cassette.get(system, user)
        if cached is not None:
            return cached
        reply = self._inner.complete(system, user)
        self._cassette.put(system, user, reply)
        self._cassette.save()
        return reply

    def propose(self, plan: dict[str, Any], evidence: list[dict[str, Any]]) -> Proposal:
        system, user = assemble_messages(plan, evidence)
        return parse_model_json(self.complete(system, user), evidence)


#: Discoverability aliases matching the conceptual backend names.
SimulatorBackend = SimulatedCognition
OpenAICompatibleBackend = OpenAICompatibleCognition

#: Backends selectable from the CLI's ``--backend`` flag.
BACKENDS: dict[str, type] = {
    "simulate": SimulatedCognition,
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
