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
* ``T3`` — the trace hash chain is intact (tamper-evident standalone) and,
  if sealed/signed, the root and HMAC signature verify;
* ``E1`` — every citation in the result points at collected evidence;
* ``U1`` — every uncertainty rule in the plan was evaluated or recorded;
* ``V1`` — every verification rule in the plan was checked, and no failed
  machine check was dropped from the result;
* ``S1`` — the reported status is consistent with the trace (a failed
  verification or a human escalation cannot be reported as ``completed``);
* ``O1`` — the produced outputs match the declared output schema.

Because the auditor needs only the plan (recompiled from source) and the
result JSON, a third party can verify conformance without trusting the
runtime, the backend, or the model.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any

from intentflow.runtime import CANONICAL_PHASES, GENESIS_HASH, link_hash

#: Statuses for which the run reached verification/uncertainty phases.
_EXECUTED_STATUSES = ("completed", "needs_human", "blocked", "failed_verification")


@dataclass
class Violation:
    code: str
    message: str


def _check_trace_chain(
    trace: list[dict[str, Any]],
    chain: dict[str, Any] | None = None,
    sign_key: bytes | None = None,
) -> list[Violation]:
    """Recompute the hash chain independently and verify any seal/signature.

    This makes the trace tamper-*evident* on its own: an edited, deleted, or
    reordered event breaks the chain regardless of the plan. A valid HMAC
    signature additionally proves the trace was sealed by a key holder."""
    violations: list[Violation] = []
    prev = GENESIS_HASH
    for event in trace:
        if event.get("prev_hash") != prev:
            violations.append(
                Violation(
                    "T3",
                    f"trace hash chain broken at seq {event.get('seq')}: "
                    "prev_hash does not match the previous event",
                )
            )
            return violations
        if event.get("hash") != link_hash(prev, event):
            violations.append(
                Violation(
                    "T3",
                    f"trace event seq {event.get('seq')} has been altered "
                    "(recomputed hash does not match)",
                )
            )
            return violations
        prev = event["hash"]

    if chain is not None:
        if chain.get("root") != prev:
            violations.append(
                Violation("T3", "sealed trace root does not match the recomputed chain")
            )
        if chain.get("length") != len(trace):
            violations.append(
                Violation("T3", "sealed trace length does not match the trace")
            )
        signature = chain.get("signature")
        if signature is not None:
            if sign_key is None:
                violations.append(
                    Violation("T3", "trace is signed but no key was provided to verify it")
                )
            else:
                expected = hmac.new(sign_key, prev.encode("utf-8"), hashlib.sha256).hexdigest()
                if not hmac.compare_digest(expected, signature):
                    violations.append(Violation("T3", "trace signature is invalid"))
    return violations


def _check_trace_integrity(trace: list[dict[str, Any]]) -> list[Violation]:
    violations: list[Violation] = []
    seqs = [event["seq"] for event in trace]
    if seqs != list(range(1, len(seqs) + 1)):
        violations.append(
            Violation("T1", "trace sequence numbers are not contiguous from 1")
        )
    started = [event["phase"] for event in trace if event["event"] == "phase_started"]
    deduped: list[str] = []
    for phase in started:
        if not deduped or deduped[-1] != phase:
            deduped.append(phase)
    expected = [phase for phase in CANONICAL_PHASES if phase in deduped]
    if deduped != expected:
        violations.append(
            Violation(
                "T2",
                f"phases ran out of canonical order: {deduped} (expected {expected})",
            )
        )
    return violations


def _check_action_governance(
    plan: dict[str, Any], trace: list[dict[str, Any]]
) -> list[Violation]:
    violations: list[Violation] = []
    policy = plan["action_policy"]
    allowed = set(policy["allowed"])
    gated = set(policy["approval_required"])
    denied = set(policy["denied"])
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
    dangling = [c for c in result.get("citations", []) if c not in evidence_ids]
    if dangling:
        return [
            Violation(
                "E1",
                "result cites evidence that was never collected: "
                + ", ".join(dangling),
            )
        ]
    return []


def _check_uncertainty_coverage(
    plan: dict[str, Any], trace: list[dict[str, Any]]
) -> list[Violation]:
    evaluated = {
        event["detail"].get("condition")
        for event in trace
        if event["event"] in ("rule_evaluated", "rule_not_evaluable")
    }
    return [
        Violation(
            "U1",
            f"uncertainty rule 'if {rule['condition']['text']} "
            f"{rule['action']['name']}' was never evaluated or recorded",
        )
        for rule in plan["uncertainty_policy"]["rules"]
        if rule["condition"]["text"] not in evaluated
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
    for rule in plan["verification_policy"]["rules"]:
        if rule["rule_id"] not in checked:
            violations.append(
                Violation("V1", f"verification rule {rule['rule_id']} was never checked")
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


def _check_status_consistency(result: dict[str, Any]) -> list[Violation]:
    status = result.get("status")
    if status != "completed":
        return []
    violations: list[Violation] = []
    if result.get("verification", {}).get("passed") is False:
        violations.append(
            Violation(
                "S1",
                "status is 'completed' but verification failed; a failed "
                "verification may never be reported as success",
            )
        )
    if result.get("escalations"):
        violations.append(
            Violation(
                "S1",
                "status is 'completed' but the run recorded escalations",
            )
        )
    return violations


def _check_output_contract(plan: dict[str, Any], result: dict[str, Any]) -> list[Violation]:
    fields = plan["output_schema"]["fields"]
    declared = {f["name"] for f in fields}
    required = {f["name"] for f in fields if not f.get("optional")}
    produced = set(result.get("outputs", {}))
    violations: list[Violation] = []
    undeclared = produced - declared
    if undeclared:
        violations.append(
            Violation(
                "O1",
                f"outputs include undeclared fields: {sorted(undeclared)}",
            )
        )
    missing = required - produced
    if missing and result.get("verification", {}).get("passed"):
        violations.append(
            Violation(
                "O1",
                f"verification passed but required outputs are missing: "
                f"{sorted(missing)}",
            )
        )
    return violations


def audit_result(
    plan: dict[str, Any], result: dict[str, Any], sign_key: bytes | None = None
) -> dict[str, Any]:
    """Audit one goal result against its compiled plan."""
    status = result.get("status")
    if status == "failed_validation":
        return {
            "goal": plan["goal"],
            "conformant": True,
            "violations": [],
            "note": "run failed validation before execution; nothing to audit",
        }
    trace = result.get("trace", [])
    violations = (
        _check_trace_integrity(trace)
        + _check_trace_chain(trace, result.get("trace_chain"), sign_key)
        + _check_action_governance(plan, trace)
        + _check_evidence_citations(result)
        + _check_status_consistency(result)
        + _check_output_contract(plan, result)
    )
    if status in _EXECUTED_STATUSES:
        violations += _check_uncertainty_coverage(plan, trace)
        violations += _check_verification_coverage(plan, result, trace)
    return {
        "goal": plan["goal"],
        "conformant": not violations,
        "violations": [{"code": v.code, "message": v.message} for v in violations],
    }


def audit_document(
    document: dict[str, Any], result: dict[str, Any], sign_key: bytes | None = None
) -> dict[str, Any]:
    """Audit a result file (single goal or pipeline) against a compiled
    document. Returns an aggregate report."""
    plans = {plan["goal"]: plan for plan in document["goals"]}
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
            reports.append(audit_result(plan, stage, sign_key))
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
    return audit_result(plan, result, sign_key)
