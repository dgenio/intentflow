"""Regression tests for fail-closed mandatory verification semantics (#160)."""

from __future__ import annotations

from copy import deepcopy

from intentflow.auditor import audit_result
from intentflow.backends import MockBackend
from intentflow.compiler import compile_goal
from intentflow.parser import parse_source
from intentflow.runtime import GoalRuntime


_SOURCE = """goal VerifyMe {
  objective:
    produce an answer
  evidence:
    require logs
  output:
    answer: string
}
"""


def _plan() -> dict:
    program = parse_source(_SOURCE)
    return compile_goal(program.goals[0], program.source_name).to_dict()


def _backend() -> MockBackend:
    return MockBackend(
        {
            "output": {"answer": "ok"},
            "confidence": 0.9,
            "citations": ["E1"],
        }
    )


def _with_rule(plan: dict, *, mode: str, kind: str, **check_fields: object) -> dict:
    plan["verification_policy"]["rules"] = [
        {
            "rule_id": "V1",
            "description": "mandatory regression rule",
            "check": {"mode": mode, "kind": kind, **check_fields},
        }
    ]
    return plan


def test_unevaluable_machine_check_makes_verification_incomplete() -> None:
    plan = _with_rule(
        _plan(),
        mode="machine",
        kind="threshold_check",
        metric="missing_metric",
        op=">=",
        value=0.5,
    )

    result = GoalRuntime(plan, backend=_backend()).run()

    assert result["status"] == "failed_verification"
    assert result["verification"]["passed"] is False
    assert result["verification"]["status"] == "incomplete"
    assert result["verification"]["checks"][1]["status"] == "skipped"
    assert result["summary"]["verification_status"] == "incomplete"


def test_judged_rule_without_judge_makes_verification_incomplete() -> None:
    plan = _with_rule(_plan(), mode="judged", kind="judged")

    result = GoalRuntime(plan, backend=_backend()).run()

    assert result["status"] == "failed_verification"
    assert result["verification"]["passed"] is False
    assert result["verification"]["status"] == "incomplete"
    assert result["verification"]["checks"][1]["status"] == "skipped"


def test_judge_exception_fails_closed_and_is_witnessed() -> None:
    class BrokenJudge:
        name = "broken-judge"

        def judge(self, rule: str, context: dict) -> object:
            raise RuntimeError("judge unavailable")

    plan = _with_rule(_plan(), mode="judged", kind="judged")
    result = GoalRuntime(plan, backend=_backend(), judge=BrokenJudge()).run()

    check = result["verification"]["checks"][1]
    assert result["status"] == "failed_verification"
    assert result["verification"]["status"] == "incomplete"
    assert check["status"] == "skipped"
    assert "RuntimeError" in check["note"]
    witnessed = [
        event["detail"]
        for event in result["trace"]
        if event["event"] == "check_evaluated" and event["detail"].get("id") == "V1"
    ]
    assert witnessed and witnessed[0]["status"] == "skipped"


def test_auditor_rejects_skipped_check_relabelled_as_success() -> None:
    plan = _with_rule(_plan(), mode="judged", kind="judged")
    result = GoalRuntime(plan, backend=_backend()).run()
    assert audit_result(plan, result)["conformant"] is True

    tampered = deepcopy(result)
    tampered["status"] = "completed"
    tampered["verification"]["passed"] = True
    tampered["verification"]["status"] = "passed"
    tampered["verification"]["checks"][1]["status"] = "pass"

    report = audit_result(plan, tampered)
    assert report["conformant"] is False
    assert any(v["code"] in {"V1", "S1"} for v in report["violations"])
