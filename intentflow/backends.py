"""Cognition backends: pluggable engines that propose hypotheses for a plan.

The runtime is a phase machine; cognition is a replaceable component behind
one narrow contract: given a plan and collected evidence, return a
:class:`Proposal`. Everything else — action gating, calibration, uncertainty
rules, verification, tracing — happens *outside* the backend, so no backend
(and no model) can opt out of governance.

Backends:

* :class:`SimulatedCognition` — deterministic mock cognition. No network, no
  flakiness; used to test the language's control structure end to end and as
  the conformance reference for real backends.
* :class:`AnthropicCognition` — drives a real Claude model through the
  staged prompt plan. Requires the optional ``anthropic`` package and an
  ``ANTHROPIC_API_KEY``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
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


class AnthropicCognition:
    """Real cognition via the Claude API, behind the same contract.

    The staged prompt plan from the compiler is used as-is: the ``frame``
    step becomes the system prompt, and evidence/model/output instructions
    become the user turn. The model is asked for strict JSON so hypotheses,
    confidences, and citations flow into the same calibration, uncertainty,
    and verification machinery as simulated runs.
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
        self._client = anthropic.Anthropic()
        self._model = model
        self._max_tokens = max_tokens

    def propose(self, plan: dict[str, Any], evidence: list[dict[str, Any]]) -> Proposal:
        steps = {step["phase"]: step["instruction"] for step in plan["prompt_plan"]}
        evidence_block = json.dumps(evidence, indent=2)
        user_message = (
            f"{steps.get('evidence', '')}\n\nCollected evidence:\n{evidence_block}\n\n"
            f"{steps.get('model', '')}\n\n"
            "Respond with ONLY a JSON object of the form:\n"
            '{"hypotheses": [{"statement": str, "confidence": float,'
            ' "citations": [str]}], "proposed_fix": str}\n'
            "Cite only evidence ids that appear above."
        )
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=steps.get("frame", ""),
            messages=[{"role": "user", "content": user_message}],
        )
        text = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
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
        return Proposal(
            hypotheses=hypotheses, proposed_fix=payload.get("proposed_fix")
        )


def make_backend(name: str) -> CognitionBackend:
    """Build a backend by CLI name."""
    if name == "simulate":
        return SimulatedCognition()
    if name == "anthropic":
        return AnthropicCognition()
    raise ValueError(f"unknown backend {name!r}; expected 'simulate' or 'anthropic'")
