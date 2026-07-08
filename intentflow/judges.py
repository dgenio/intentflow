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
from pathlib import Path
from typing import Any, Callable, Protocol

from intentflow.backends import try_parse_json
from intentflow.reliability import RetryPolicy


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

    def __init__(
        self,
        chat: Callable[[str, str], str],
        *,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._chat = chat
        # A judge call is a network call like any other: bound it and fail
        # closed. Real judges get a retrying policy; injected fakes get none.
        self._retry = retry_policy or RetryPolicy.disabled()

    def judge(self, rule: str, context: dict[str, Any]) -> JudgeVerdict:
        user = (
            f"Verification rule:\n{rule}\n\n"
            f"Run result:\n{json.dumps(context, indent=2, default=str)}\n\n"
            'Respond with ONLY a JSON object: {"passed": bool, "rationale": str}'
        )
        text = self._retry.run(
            lambda: self._chat(_JUDGE_SYSTEM, user), describe="judge"
        )
        payload = try_parse_json(text)
        if payload is None:
            # Fail closed: a judge whose reply we cannot parse has not cleared
            # the rule, and the system prompt already tells it to be
            # conservative. Never treat unparseable output as a pass, and never
            # crash the run over it.
            return JudgeVerdict(
                False,
                "judge reply was not valid JSON; failing the rule closed "
                f"(reply began: {text.strip()[:80]!r})",
            )
        return JudgeVerdict(
            bool(payload.get("passed", False)),
            str(payload.get("rationale", "")),
        )


def make_judge(name: str, cassette: str | Path | None = None) -> Judge:
    """Build a judge by CLI name. Real judges reuse the backend providers and
    raise a clear error if their dependency or credentials are missing.

    ``replay`` answers judged rules from a recorded ``cassette`` (no key). For
    a real judge, passing ``cassette`` records its replies for later replay.
    """
    from intentflow.backends import (
        Cassette,
        RecordingChat,
        ReplayChat,
        provider_chat,
    )

    if name == "simulate":
        return SimulatedJudge()
    if name == "replay":
        if cassette is None:
            raise ValueError("the 'replay' judge requires a cassette path")
        return LLMJudge(ReplayChat(Cassette.load(cassette)))
    if name in ("openai", "anthropic"):
        chat = provider_chat(name)
        if cassette is not None:
            chat = RecordingChat(chat, Cassette.load(cassette))
        return LLMJudge(chat, retry_policy=RetryPolicy.from_env())
    raise ValueError(
        f"unknown judge {name!r}; expected one of: simulate, openai, anthropic, replay"
    )
