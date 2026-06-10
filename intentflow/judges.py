"""LLM-judge runner for ``judged`` verification rules.

Some verification rules cannot be checked mechanically — "the tone must be
maintainer-safe", "conflicting sources must be reported, not hidden". The
compiler marks these ``judged``. Without a judge the runtime records them as
*skipped* (never silently passed). A :class:`Judge` lets the runtime actually
evaluate them — but always in a **separate trust tier**: judged verdicts are
labelled with the judge that produced them and a rationale, and are reported
apart from machine checks so a reviewer never confuses "a program proved this"
with "a model thought this was fine".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Protocol


@dataclass
class JudgeVerdict:
    """A judge's decision on one verification rule."""

    passed: bool
    rationale: str


class Judge(Protocol):
    name: str

    def judge(self, rule: str, context: dict[str, Any]) -> JudgeVerdict:
        """Decide whether ``rule`` holds given the run ``context`` (top
        hypothesis, proposed fix, outputs, evidence summaries)."""
        ...


class SimulatedJudge:
    """A deterministic judge for tests and offline runs.

    It passes every rule by default, which keeps the trust boundary honest:
    a simulated judge cannot manufacture a meaningful verdict, so its job is
    only to exercise the *runner* deterministically. ``overrides`` maps a
    substring of a rule's text to a forced verdict, so tests can drive a
    judged failure without a model.
    """

    name = "simulate-judge"

    def __init__(
        self, default_pass: bool = True, overrides: dict[str, bool] | None = None
    ) -> None:
        self._default = default_pass
        self._overrides = overrides or {}

    def judge(self, rule: str, context: dict[str, Any]) -> JudgeVerdict:
        for needle, verdict in self._overrides.items():
            if needle.lower() in rule.lower():
                return JudgeVerdict(
                    verdict, f"[simulated] forced verdict for rule matching {needle!r}"
                )
        return JudgeVerdict(
            self._default,
            "[simulated] no machine signal; judge defaulted "
            f"to {'pass' if self._default else 'fail'}",
        )


_JUDGE_SYSTEM = (
    "You are a strict verification judge for a governed reasoning process. "
    "You are given one verification rule and the run's result. Decide whether "
    "the result satisfies the rule. Be conservative: if the result does not "
    "clearly satisfy the rule, fail it."
)


class LLMJudge:
    """A judge backed by any chat callable ``(system, user) -> text``.

    Keeping the model behind a plain callable makes the judge provider-
    agnostic and unit-testable with a fake. :func:`make_judge` wires real
    providers in; tests can pass their own callable.
    """

    name = "llm-judge"

    def __init__(self, chat: Callable[[str, str], str]) -> None:
        self._chat = chat

    def judge(self, rule: str, context: dict[str, Any]) -> JudgeVerdict:
        user = (
            f"Verification rule:\n{rule}\n\n"
            f"Run result:\n{json.dumps(context, indent=2, default=str)}\n\n"
            'Respond with ONLY a JSON object: {"passed": bool, "rationale": str}'
        )
        text = self._chat(_JUDGE_SYSTEM, user).strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[len("json"):]
            text = text.strip()
        payload = json.loads(text)
        return JudgeVerdict(
            bool(payload.get("passed", False)),
            str(payload.get("rationale", "")),
        )


def make_judge(name: str) -> Judge:
    """Build a judge by CLI name. Real judges reuse the backend providers and
    raise a clear error if their dependency or credentials are missing."""
    if name == "simulate":
        return SimulatedJudge()
    if name in ("openai", "anthropic"):
        from intentflow.backends import provider_chat

        return LLMJudge(provider_chat(name))
    raise ValueError(
        f"unknown judge {name!r}; expected one of: simulate, openai, anthropic"
    )
