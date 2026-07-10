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

Two structural, plan-level codes cover inputs the auditor cannot verify:

* ``P1`` — no plan exists for the goal/stage named in the result;
* ``P2`` — the plan or result declares a format version this auditor does not
  support, so a conformance verdict would be unreliable (see
  ``docs/formats.md`` for the versioning policy).

Because the auditor needs only the plan (recompiled from source) and the
result JSON, a third party can verify conformance without trusting the
runtime, the backend, or the model.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any

from intentflow.compiler import PLAN_FORMAT_VERSION
from intentflow.trace import (
    TRACE_FORMAT_VERSION,
    CANONICAL_PHASES,
    GENESIS_HASH,
    Event,
    link_hash,
)

#: Plan format versions this auditor can verify. Pre-1.0 the policy is
#: exact-match: a minor bump may change plan semantics, so an out-of-range plan
#: is reported (P2) rather than audited on optimistic assumptions.
SUPPORTED_PLAN_FORMATS = frozenset({PLAN_FORMAT_VERSION})

#: Result/trace (witness) format versions this auditor can verify. Same
#: exact-match policy as plans, tracked independently.
SUPPORTED_TRACE_FORMATS = frozenset({TRACE_FORMAT_VERSION})

#: Statuses for which the run reached verification/uncertainty phases.
_EXECUTED_STATUSES = ("completed", "needs_human", "blocked", "failed_verification")


@dataclass
class Violation:
    code: str
    message: str


def _verify_hmac_signature(
    entry: dict[str, Any],
    root: str,
    sign_key: bytes | None,
    keys: dict[str, bytes] | None,
) -> Violation | None:
    """Verify one ``hmac-sha256`` seal signature entry. Returns a ``T3``
    Violation, or ``None`` if it verifies. Key material is never echoed; a
    ``key_id`` is an identifier, not a secret, so it may appear in messages."""
    key_id = entry.get("key_id")
    if key_id is not None:
        key = (keys or {}).get(key_id)
        if key is None:
            return Violation("T3", f"trace signed with unknown key id {key_id!r}")
    else:
        key = sign_key
        if key is None:
            return Violation("T3", "trace is signed but no key was provided to verify it")
    expected = hmac.new(key, root.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, str(entry.get("signature", ""))):
        which = f" (key id {key_id!r})" if key_id is not None else ""
        return Violation("T3", f"trace signature is invalid{which}")
    return None


def _verify_ed25519_signature(
    entry: dict[str, Any],
    root: str,
    verifiers: "dict[str | None, bytes] | None",
) -> Violation | None:
    """Verify one ``ed25519`` seal signature entry against a *trusted* public
    key supplied out of band (never the key embedded in the entry, which a
    forger controls). ``verifiers`` maps ``key_id`` to trusted public-key bytes.
    Returns a ``T3`` Violation, or ``None`` if it verifies."""
    verifiers = verifiers or {}
    key_id = entry.get("key_id")
    # A named key (by key_id) takes precedence; the default trusted key (stored
    # under None, e.g. a single IFLOW_TRACE_PUBLIC_KEY) verifies any seal.
    public_key = verifiers.get(key_id) if key_id is not None else None
    if public_key is None:
        public_key = verifiers.get(None)
    if public_key is None:
        which = f" for key id {key_id!r}" if key_id is not None else ""
        return Violation(
            "T3", f"trace has an ed25519 signature but no trusted public key was provided{which}"
        )
    # Lazy import: the public-key backend needs `cryptography` (optional extra),
    # so it is only imported when an ed25519 signature is actually verified.
    from intentflow.signing import verify_root

    if not verify_root(root, str(entry.get("signature", "")), public_key):
        which = f" (key id {key_id!r})" if key_id is not None else ""
        return Violation("T3", f"trace ed25519 signature is invalid{which}")
    return None


def _check_trace_chain(
    trace: list[dict[str, Any]],
    chain: dict[str, Any] | None = None,
    sign_key: bytes | None = None,
    keys: dict[str, bytes] | None = None,
    verifiers: "dict[str, bytes] | None" = None,
    require_signed: bool = False,
) -> list[Violation]:
    """Recompute the hash chain independently and verify any seal signatures.

    This makes the trace tamper-*evident* on its own: an edited, deleted, or
    reordered event breaks the chain regardless of the plan. A valid signature
    additionally proves the trace was sealed by a key holder. HMAC signatures
    are verified with ``sign_key`` (the default, keyless case) or a named key
    from ``keys`` (selected by the entry's ``key_id``, so rotation keeps old
    witnesses verifiable); Ed25519 signatures are verified with public keys from
    ``verifiers`` (see :mod:`intentflow.signing`).

    The bare chain proves *integrity*, not *authenticity*: a forger can edit an
    event, recompute every downstream link, and drop the seal's ``signatures``
    list, leaving a chain-valid but unsigned witness. By default such a witness
    is conformant (sealing is opt-in). ``require_signed`` closes that downgrade
    path: when set, a witness with no signature that verifies against the
    supplied keys is a ``T3`` violation, so a stripped or absent seal is
    detected rather than silently accepted."""
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
        verified = 0
        for entry in chain.get("signatures", []):
            algo = entry.get("algo")
            if algo == "hmac-sha256":
                v = _verify_hmac_signature(entry, prev, sign_key, keys)
            elif algo == "ed25519":
                v = _verify_ed25519_signature(entry, prev, verifiers)
            else:
                v = Violation("T3", f"trace has an unknown signature algorithm {algo!r}")
            if v is not None:
                violations.append(v)
            else:
                verified += 1
        if require_signed and verified == 0:
            violations.append(
                Violation(
                    "T3",
                    "trace has no signature that verifies against the supplied "
                    "keys, but a signed witness was required",
                )
            )
    return violations


def verify_trace_stream(lines: "list[str] | str") -> dict[str, Any]:
    """Chain-verify a streamed JSONL trace (issue #82), distinguishing a
    complete run from a truncated-but-valid prefix.

    A streamed trace is a hash chain written one event per line as the run
    proceeds, so a process killed mid-run leaves a prefix that still verifies
    from genesis. Pass the file contents (a string) or a list of lines. Returns
    ``{events, complete, chain_ok, violations}``: ``complete`` is True only when
    a terminal ``run_completed`` event is present; ``chain_ok`` reports whether
    the events seen form an intact chain."""
    if isinstance(lines, str):
        raw_lines = lines.splitlines()
    else:
        raw_lines = list(lines)
    events: list[dict[str, Any]] = []
    for line in raw_lines:
        line = line.strip()
        if line:
            events.append(json.loads(line))
    violations = _check_trace_integrity(events) + _check_trace_chain(events)
    complete = any(e.get("event") == Event.RUN_COMPLETED for e in events)
    return {
        "events": len(events),
        "complete": complete,
        "chain_ok": not violations,
        "violations": [{"code": v.code, "message": v.message} for v in violations],
    }


def _check_trace_integrity(trace: list[dict[str, Any]]) -> list[Violation]:
    violations: list[Violation] = []
    seqs = [event["seq"] for event in trace]
    if seqs != list(range(1, len(seqs) + 1)):
        violations.append(
            Violation("T1", "trace sequence numbers are not contiguous from 1")
        )
    started = [event["phase"] for event in trace if event["event"] == Event.PHASE_STARTED]
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
        if event["event"] == Event.APPROVAL_GRANTED:
            granted.add(action)
        if event["event"] != Event.TOOL_INVOKED:
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
        if event["event"] in (Event.RULE_EVALUATED, Event.RULE_NOT_EVALUABLE)
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
        if event["event"] == Event.CHECK_EVALUATED
    }
    for rule in plan["verification_policy"]["rules"]:
        if rule["rule_id"] not in checked:
            violations.append(
                Violation("V1", f"verification rule {rule['rule_id']} was never checked")
            )
    failed_in_trace = {
        event["detail"]["id"]
        for event in trace
        if event["event"] == Event.CHECK_EVALUATED and event["detail"].get("status") == "fail"
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


def _check_format_versions(
    plan: dict[str, Any], result: dict[str, Any]
) -> list[Violation]:
    """Verify the plan and result declare format versions this auditor supports.

    A conformance verdict is only meaningful if the auditor understands the
    shapes it is checking. An out-of-range version is reported as ``P2`` rather
    than audited on optimistic assumptions about a format this build predates or
    postdates. See ``docs/formats.md`` for the versioning policy."""
    violations: list[Violation] = []
    plan_version = plan.get("format_version")
    if plan_version not in SUPPORTED_PLAN_FORMATS:
        violations.append(
            Violation(
                "P2",
                f"plan format version {plan_version!r} is not supported by this "
                f"auditor (supports {sorted(SUPPORTED_PLAN_FORMATS)}); "
                "re-compile with a matching IntentFlow or consult docs/formats.md",
            )
        )
    trace_version = result.get("format_version")
    if trace_version not in SUPPORTED_TRACE_FORMATS:
        violations.append(
            Violation(
                "P2",
                f"result/trace format version {trace_version!r} is not supported "
                f"by this auditor (supports {sorted(SUPPORTED_TRACE_FORMATS)}); "
                "re-run with a matching IntentFlow or consult docs/formats.md",
            )
        )
    return violations


def audit_result(
    plan: dict[str, Any],
    result: dict[str, Any],
    sign_key: bytes | None = None,
    keys: dict[str, bytes] | None = None,
    verifiers: "dict[str | None, bytes] | None" = None,
    require_signed: bool = False,
) -> dict[str, Any]:
    """Audit one goal result against its compiled plan.

    ``sign_key`` verifies a keyless HMAC seal; ``keys`` (``{key_id: key}``)
    verifies rotated, key-id'd HMAC seals; ``verifiers`` (``{key_id: public_key}``)
    verifies Ed25519 seals. ``require_signed`` rejects a witness that carries no
    verifying signature (a stripped or absent seal), closing the downgrade path.
    See ``docs/trace-signing.md``."""
    # Version compatibility gates everything else: if the auditor does not
    # understand the plan/result shape, no downstream check is trustworthy.
    version_violations = _check_format_versions(plan, result)
    if version_violations:
        return {
            "goal": plan["goal"],
            "conformant": False,
            "violations": [{"code": v.code, "message": v.message} for v in version_violations],
        }
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
        + _check_trace_chain(
            trace, result.get("trace_chain"), sign_key, keys, verifiers, require_signed
        )
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
    document: dict[str, Any],
    result: dict[str, Any],
    sign_key: bytes | None = None,
    keys: dict[str, bytes] | None = None,
    verifiers: "dict[str | None, bytes] | None" = None,
    require_signed: bool = False,
) -> dict[str, Any]:
    """Audit a result file (single goal or pipeline) against a compiled
    document. Returns an aggregate report. ``sign_key``/``keys``/``verifiers``
    supply the HMAC and Ed25519 keys used to verify any trace seal;
    ``require_signed`` rejects a witness with no verifying signature (see
    ``audit_result``)."""
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
            reports.append(
                audit_result(plan, stage, sign_key, keys, verifiers, require_signed)
            )
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
    return audit_result(plan, result, sign_key, keys, verifiers, require_signed)
