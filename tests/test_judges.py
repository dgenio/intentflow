"""Judge tests: the LLM-judge runner for 'judged' verification rules, and the
separate trust tier it produces."""

from __future__ import annotations

import pytest

from intentflow.compiler import compile_goal
from intentflow.judges import JudgeVerdict, LLMJudge, SimulatedJudge, make_judge
from intentflow.parser import parse_source
from intentflow.runtime import GoalRuntime

JUDGED_SRC = (
    "goal G {\n  objective:\n    answer well\n"
    "  evidence:\n    require notes\n"
    "  verify:\n    the answer must be tasteful\n"
    "  output:\n    answer: string\n}\n"
)


def _run(judge=None) -> dict:
    plan = compile_goal(parse_source(JUDGED_SRC).goals[0]).to_dict()
    return GoalRuntime(plan, printer=None, judge=judge).run()


def _judged_check(result: dict) -> dict:
    return next(
        c for c in result["verification"]["checks"] if c["mode"] == "judged"
    )


def test_simulated_judge_passes_by_default() -> None:
    verdict = SimulatedJudge().judge("anything", {})
    assert verdict.passed is True
    assert isinstance(verdict.rationale, str)


def test_simulated_judge_overrides_force_a_verdict() -> None:
    judge = SimulatedJudge(overrides={"tasteful": False})
    assert judge.judge("the answer must be tasteful", {}).passed is False
    assert judge.judge("unrelated rule", {}).passed is True


def test_llm_judge_parses_fenced_json() -> None:
    def fake_chat(system: str, user: str) -> str:
        assert "verification rule" in user.lower()
        return '```json\n{"passed": false, "rationale": "tone is off"}\n```'

    verdict = LLMJudge(fake_chat).judge("be nice", {})
    assert verdict == JudgeVerdict(False, "tone is off")


def test_without_judge_judged_rules_are_skipped_not_passed() -> None:
    result = _run(judge=None)
    check = _judged_check(result)
    assert check["status"] == "skipped"
    assert "judged_by" not in check
    # A skipped judged rule does not block completion...
    assert result["verification"]["passed"] is True


def test_judge_can_pass_a_judged_rule() -> None:
    result = _run(judge=SimulatedJudge(default_pass=True))
    check = _judged_check(result)
    assert check["status"] == "pass"
    assert check["judged_by"] == "simulate-judge"
    assert result["verification"]["passed"] is True


def test_judge_can_fail_a_judged_rule_and_fail_the_run() -> None:
    result = _run(judge=SimulatedJudge(overrides={"tasteful": False}))
    check = _judged_check(result)
    assert check["status"] == "fail"
    assert result["verification"]["passed"] is False
    assert result["status"] == "failed_verification"


def test_verification_keeps_machine_and_judged_tiers_separate() -> None:
    # A goal with one machine check (cite) and one judged check (plus the
    # implicit V0 schema machine check).
    src = (
        "goal G {\n  objective:\n    x\n  evidence:\n    require notes\n"
        "  verify:\n    require cites_evidence\n    must be tasteful\n"
        "  output:\n    answer: string\n}\n"
    )
    plan = compile_goal(parse_source(src).goals[0]).to_dict()
    result = GoalRuntime(plan, printer=None, judge=SimulatedJudge()).run()
    tiers = result["verification"]["tiers"]
    assert tiers["machine"]["total"] == 2  # V0 schema + cites_evidence
    assert tiers["judged"]["total"] == 1
    assert tiers["judged"]["passed"] == 1


def test_make_judge_unknown_name_errors() -> None:
    with pytest.raises(ValueError, match="unknown judge"):
        make_judge("oracle")


def test_judged_verdict_is_recorded_in_trace() -> None:
    result = _run(judge=SimulatedJudge())
    judged_events = [
        e for e in result["trace"]
        if e["event"] == "check_evaluated" and e["detail"].get("judged_by")
    ]
    assert judged_events and judged_events[0]["detail"]["judged_by"] == "simulate-judge"
