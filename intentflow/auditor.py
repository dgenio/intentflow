"""Trace conformance auditing: proof-carrying agent behavior.

An IntentFlow program is a *contract*; the trace a run emits is the
*witness*. The auditor replays a result (trace + structured outputs) against
the compiled plan and checks, independently of the runtime that produced it,
that the agent stayed inside its envelope:

* ``A1`` — every invoked tool action was allowed by the plan;
* ``A2`` — every approval-gated invocation has a prior approval grant;
* ``A3`` — no denied action was ever invoked;
* ``T1`` — the trace is append-only (sequence strictly increasing from 1);
* ``T2`` — phases ran in canonical order;
* ``E1`` — every hypothesis citation points at collected evidence;
* ``U1`` — every uncertainty rule in the plan was evaluated or recorded;
* ``V1`` — every verification rule in the plan was checked, and no failed
  machine check was dropped from the result;
* ``O1`` — the produced outputs are exactly the declared output contract.

Because the auditor needs only the plan (recompiled from source) and the
result JSON, a third party can verify conformance without trusting the
runtime, the backend, or the model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from intentflow.runtime import CANONICAL_PHASES


@dataclass
class Violation:
    code: str
    message: str


def _check_trace_integrity(trace: list[dict[str, Any]]) -> list[Violation]:
    violations: list[Violation] = []
    seqs = [event["seq"] for event in trace]
    if seqs != list(range(1, len(seqs) + 1)):
        violations.append(
            Violation("T1", "trace sequence numbers are not contiguous from 1")
        )
    started = [event["phase"] for event in trace if event["event"] == "phase_started"]
    expected = [phase for phase in CANONICAL_PHASES if phase in started]
    if started != expected:
        violations.append(
            Violation(
                "T2",
                f"phases ran out of canonical order: {started} (expected {expected})",
            )
        )
    return violations


def _check_action_governance(
    plan: dict[str, Any], trace: list[dict[str, Any]]
) -> list[Violation]:
    violations: list[Violation] = []
    allowed = set(plan["actions"]["allowed"])
    gated = set(plan["actions"]["approval_required"])
    denied = set(plan["actions"]["denied"])
    granted: set[str] = set()
    for event in trace:
        action = event["detail"].get("action")
        if event["event"] == "approval_granted":
            granted.add(action)
        if event["event"] != "tool_invoked":
            continue
        if action in denied:
            violations.append(
                Violation("A3", f"denied action {action!r} was invoked")
            )
        elif action in gated:
            if action not in granted:
                violations.append(
                    Violation(
                        "A2",
                        f"approval-gated action {action!r} invoked without a "
                        "prior approval grant",
                    )
                )
        elif action not in allowed:
            violations.append(
                Violation(
                    "A1", f"action {action!r} invoked but not allowed by the plan"
                )
            )
    return violations


def _check_evidence_citations(result: dict[str, Any]) -> list[Violation]:
    evidence_ids = {item["id"] for item in result.get("evidence", [])}
    violations: list[Violation] = []
    for hyp in result.get("hypotheses", []):
        dangling = [c for c in hyp.get("citations", []) if c not in evidence_ids]
        if dangling:
            violations.append(
                Violation(
                    "E1",
                    f"hypothesis {hyp['id']} cites evidence that was never "
                    f"collected: {', '.join(dangling)}",
                )
            )
    return violations


def _check_uncertainty_coverage(
    plan: dict[str, Any], trace: list[dict[str, Any]]
) -> list[Violation]:
    evaluated = {
        event["detail"].get("condition")
        for event in trace
        if event["event"] in ("rule_evaluated", "rule_not_simulated", "rule_skipped")
    }
    return [
        Violation(
            "U1",
            f"uncertainty rule 'if {rule['condition']} {rule['action']}' was "
            "never evaluated or recorded",
        )
        for rule in plan["uncertainty_policy"]
        if rule["condition"] not in evaluated
    ]


def _check_verification_coverage(
    plan: dict[str, Any], result: dict[str, Any], trace: list[dict[str, Any]]
) -> list[Violation]:
    violations: list[Violation] = []
    checked = {
        event["detail"].get("id")
        for event in trace
        if event["event"] == "check_evaluated"
    }
    for rule in plan["verification"]:
        if rule["id"] not in checked:
            violations.append(
                Violation("V1", f"verification rule {rule['id']} was never checked")
            )
    failed_in_trace = {
        event["detail"]["id"]
        for event in trace
        if event["event"] == "check_evaluated" and event["detail"].get("status") == "fail"
    }
    reported = {
        check["id"]: check["status"]
        for check in result.get("verification", {}).get("checks", [])
    }
    for rule_id in failed_in_trace:
        if reported.get(rule_id) != "fail":
            violations.append(
                Violation(
                    "V1",
                    f"check {rule_id} failed in the trace but the result does "
                    "not report the failure",
                )
            )
    claimed_passed = result.get("verification", {}).get("passed")
    actually_passed = all(status != "fail" for status in reported.values())
    if claimed_passed is not None and claimed_passed != actually_passed:
        violations.append(
            Violation(
                "V1",
                "the result's verification 'passed' flag contradicts its own checks",
            )
        )
    return violations


def _check_output_contract(plan: dict[str, Any], result: dict[str, Any]) -> list[Violation]:
    declared = list(plan["outputs"])
    produced = list(result.get("outputs", {}))
    if produced != declared:
        return [
            Violation(
                "O1",
                f"outputs {produced} do not match the declared contract {declared}",
            )
        ]
    return []


def audit_result(plan: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Audit one goal result against its compiled plan."""
    trace = result.get("trace", [])
    violations = (
        _check_trace_integrity(trace)
        + _check_action_governance(plan, trace)
        + _check_evidence_citations(result)
        + _check_uncertainty_coverage(plan, trace)
        + _check_verification_coverage(plan, result, trace)
        + _check_output_contract(plan, result)
    )
    return {
        "goal": plan["goal"],
        "conformant": not violations,
        "violations": [{"code": v.code, "message": v.message} for v in violations],
    }


def audit_document(document: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Audit a result file (single goal or pipeline) against a compiled
    document. Returns an aggregate report."""
    plans = {plan["goal"]: plan for plan in document["plans"]}
    if "pipeline" in result:
        reports = []
        for stage in result["stages"]:
            plan = plans.get(stage["goal"])
            if plan is None:
                reports.append(
                    {
                        "goal": stage["goal"],
                        "conformant": False,
                        "violations": [
                            {
                                "code": "P1",
                                "message": f"no plan for stage goal {stage['goal']!r}",
                            }
                        ],
                    }
                )
                continue
            reports.append(audit_result(plan, stage))
        return {
            "pipeline": result["pipeline"],
            "conformant": all(r["conformant"] for r in reports),
            "stages": reports,
        }
    plan = plans.get(result.get("goal"))
    if plan is None:
        return {
            "goal": result.get("goal"),
            "conformant": False,
            "violations": [
                {
                    "code": "P1",
                    "message": f"no plan for goal {result.get('goal')!r} in source",
                }
            ],
        }
    return audit_result(plan, result)
