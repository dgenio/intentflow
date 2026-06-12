"""Runtime for compiled IntentFlow execution plans.

The runtime is an explicit phase machine. Every run moves through the same
canonical phases (embedded in the plan as ``execution_phases``):

    parse -> analyze -> compile -> prepare_context -> collect_evidence ->
    build_messages -> call_backend -> parse_output -> verify_output ->
    apply_uncertainty_policy -> enforce_action_policy -> finalize -> trace

Cognition is a pluggable backend (:mod:`intentflow.backends`); everything
that makes the process *governed* lives here, outside the model:

* evidence collection runs through the :class:`~intentflow.tools.ActionGate`,
  so a tool the goal does not allow cannot run — the goal gets a traced
  ``action_blocked`` and a ``missing_evidence`` signal, not the data;
* raw model confidence is calibrated before any uncertainty rule fires;
* uncertainty actions (``ask_human``, ``block_action``) are control flow
  that decides the run's final status;
* verification executes the *typed* checks the compiler emitted — machine
  checks (output schema conformance, citations, thresholds) are evaluated,
  judged checks are recorded as skipped unless a judge is configured, and a
  failed verification can never be reported as success;
* every event lands in an append-only, hash-chained trace that
  ``intentflow audit`` can later replay against the plan.

A run always ends in exactly one status:

* ``completed``           — output produced, verification passed
* ``needs_human``         — an uncertainty rule escalated to a human
* ``blocked``             — policy blocked the action (``block_action``)
* ``failed_validation``   — analyzer errors; nothing was executed
* ``failed_verification`` — output produced but a machine check failed
* ``backend_error``       — the backend failed or returned unusable output
"""

from __future__ import annotations

import hashlib
import hmac
import json
import operator
from typing import Any, Callable

from intentflow.backends import (
    BackendError,
    BackendResponse,
    CognitionBackend,
    SimulatedCognition,
    assemble_messages,
)
from intentflow.compiler import EXECUTION_PHASES
from intentflow.judges import Judge
from intentflow.tools import ActionDenied, ActionGate, Approver, ToolError, ToolRegistry

#: The phase order every conformant run must follow (checked by the auditor).
CANONICAL_PHASES: tuple[str, ...] = EXECUTION_PHASES

#: Statuses a run can end in.
RUN_STATUSES: tuple[str, ...] = (
    "completed",
    "needs_human",
    "blocked",
    "failed_validation",
    "failed_verification",
    "backend_error",
)

_OPS: dict[str, Callable[[float, float], bool]] = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
}


#: The first link of every trace hash chain (no prior event).
GENESIS_HASH = "0" * 64

#: Keys that make up an event's *core* — the part that is hash-chained. The
#: ``hash``/``prev_hash`` links and presentation-only tags (e.g. ``stage``)
#: are excluded so the chain is stable across serialization and pipelining.
_CORE_KEYS = ("seq", "phase", "event", "detail")


def _event_core(event: dict[str, Any]) -> dict[str, Any]:
    return {k: event.get(k) for k in _CORE_KEYS}


def link_hash(prev_hash: str, event: dict[str, Any]) -> str:
    """The hash that chains ``event`` to its predecessor.

    ``sha256(prev_hash || canonical(core))`` — so any edit, deletion, or
    reordering is detected when the chain is recomputed (unless a forger also
    recomputes every downstream link; see :class:`Trace`). Canonicalization is
    JSON with sorted keys, so the chain survives a round-trip through disk.
    """
    payload = prev_hash + json.dumps(
        _event_core(event), sort_keys=True, default=str
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Trace:
    """An auditable, append-only, hash-chained record of a run.

    Each event carries ``prev_hash`` and ``hash`` forming a chain rooted at
    :data:`GENESIS_HASH`. Recomputing the chain detects accidental corruption,
    truncation, and reordering without the program. The links live *inside* the
    trace, though, so a motivated forger can edit an event and recompute every
    downstream hash — the bare chain is integrity, not authenticity. Sealing
    the root out of band closes that gap: with a signing key, ``seal()`` adds an
    HMAC over the root so anyone holding the key can *detect* (not prevent)
    edits, even to runs they did not execute.
    """

    def __init__(self, sign_key: bytes | None = None) -> None:
        self.events: list[dict[str, Any]] = []
        self._prev = GENESIS_HASH
        self._sign_key = sign_key

    def record(self, phase: str, event: str, detail: dict[str, Any] | None = None) -> None:
        entry = {
            "seq": len(self.events) + 1,
            "phase": phase,
            "event": event,
            "detail": detail or {},
        }
        entry["prev_hash"] = self._prev
        entry["hash"] = link_hash(self._prev, entry)
        self._prev = entry["hash"]
        self.events.append(entry)

    def to_list(self) -> list[dict[str, Any]]:
        return list(self.events)

    def seal(self) -> dict[str, Any]:
        """A compact, verifiable summary of the chain: algorithm, length,
        root hash, and (if a key was supplied) an HMAC signature over it."""
        signature = None
        if self._sign_key is not None:
            signature = hmac.new(
                self._sign_key, self._prev.encode("utf-8"), hashlib.sha256
            ).hexdigest()
        return {
            "algo": "sha256-chain",
            "length": len(self.events),
            "root": self._prev,
            "signature": signature,
        }


def calibrate(raw: float, policy: dict[str, Any]) -> float:
    """Map raw self-reported confidence to calibrated confidence."""
    if policy.get("method") == "shrinkage":
        midpoint = policy.get("midpoint", 0.5)
        factor = policy.get("factor", 0.8)
        return round(midpoint + (raw - midpoint) * factor, 4)
    return raw


def _type_conforms(value: Any, field: dict[str, Any]) -> bool:
    """Does ``value`` conform to one output-schema field?"""
    if value is None:
        return bool(field.get("optional"))
    base = field["base"]
    if base in ("string", "markdown"):
        return isinstance(value, str)
    if base == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if base == "boolean":
        return isinstance(value, bool)
    if base == "object":
        return isinstance(value, dict)
    if base == "list":
        if not isinstance(value, list):
            return False
        if field.get("item_type") == "number":
            return all(
                isinstance(v, (int, float)) and not isinstance(v, bool) for v in value
            )
        return all(isinstance(v, str) for v in value)
    return True


class GoalRuntime:
    """Executes one compiled execution-plan dict for a single goal."""

    def __init__(
        self,
        plan: dict[str, Any],
        backend: CognitionBackend | None = None,
        printer: Callable[[str], None] | None = None,
        workspace: str | None = None,
        approved_actions: set[str] | None = None,
        seed_evidence: list[dict[str, Any]] | None = None,
        judge: Judge | None = None,
        approver: Approver | None = None,
        registry: ToolRegistry | None = None,
        sign_key: bytes | None = None,
        pre_phases: list[dict[str, Any]] | None = None,
        diagnostics: list[dict[str, Any]] | None = None,
    ) -> None:
        self.plan = plan
        self.backend = backend or SimulatedCognition()
        self.trace = Trace(sign_key=sign_key)
        self.gate = ActionGate(
            plan["action_policy"],
            trace=self.trace,
            approved=approved_actions,
            approver=approver,
        )
        if registry is not None:
            self.registry = registry
        elif workspace:
            self.registry = ToolRegistry.builtin(workspace)
        else:
            self.registry = None
        self.judge = judge
        self.seed_evidence = {item["source"]: item for item in (seed_evidence or [])}
        self._printer = printer
        self.diagnostics = diagnostics or []
        self.pre_phases = pre_phases or [
            {"name": name, "status": "completed", "detail": "performed by caller"}
            for name in ("parse", "analyze", "compile")
        ]
        # -- run state -----------------------------------------------------
        self.phases: list[dict[str, Any]] = []
        self.evidence: list[dict[str, Any]] = []
        self.messages: dict[str, str] = {}
        self.response: BackendResponse | None = None
        self.outputs: dict[str, Any] = {}
        self.citations: list[str] = []
        self.raw_confidence: float | None = None
        self.confidence: float | None = None
        self.signals: dict[str, bool] = {}
        self.escalations: list[dict[str, Any]] = []
        self.uncertainty_decisions: list[dict[str, Any]] = []
        self._status_hints: set[str] = set()
        self._backend_error: str | None = None

    # -- helpers ----------------------------------------------------------

    def _say(self, text: str) -> None:
        if self._printer is not None:
            self._printer(text)

    def _phase(self, name: str, title: str) -> None:
        self._say(f"\n=== phase: {name} — {title} ===")
        self.trace.record(name, "phase_started", {"title": title})

    def _phase_done(self, name: str, status: str = "completed", detail: str = "") -> None:
        self.phases.append({"name": name, "status": status, "detail": detail})

    # -- entry point --------------------------------------------------------

    def run(self) -> dict[str, Any]:
        for pre in self.pre_phases:
            self.trace.record(
                pre["name"], "phase_started", {"title": pre.get("detail", "")}
            )
            self.phases.append(dict(pre))
        self.trace.record(
            self.pre_phases[-1]["name"],
            "run_started",
            {"goal": self.plan["goal"], "backend": self.backend.name},
        )
        self._say(
            f"IntentFlow run: goal '{self.plan['goal']}' (backend: {self.backend.name})"
        )
        self._say(f"objective: {self.plan['objective']}")

        self._prepare_context()
        self._collect_evidence()
        self._build_messages()
        backend_ok = self._call_backend()
        if backend_ok:
            parsed_ok = self._parse_output()
        else:
            parsed_ok = False
        if parsed_ok:
            verification = self._verify_output()
            self._apply_uncertainty_policy()
        else:
            verification = self._skip_verification()
        self._enforce_action_policy()
        return self._finalize(verification)

    # -- phases -----------------------------------------------------------

    def _prepare_context(self) -> None:
        self._phase("prepare_context", "apply context/memory policy")
        policy = self.plan["context_policy"]
        if policy.get("max_tokens"):
            self._say(f"  context budget: {policy['max_tokens']} tokens")
        for item in policy.get("prefer", []):
            self._say(f"  prioritizing in context: {item}")
        for item in policy.get("preserve", []):
            self._say(f"  pinned (never evicted): {item}")
        self.trace.record("prepare_context", "policy_applied", policy)
        self._phase_done("prepare_context")

    def _collect_evidence(self) -> None:
        self._phase("collect_evidence", "collect required evidence through the gate")
        policy = self.plan["evidence_policy"]
        distrusted = set(policy["distrusted"])
        missing: list[str] = []
        index = 1
        for source in policy["required"]:
            item = self._collect_one(f"E{index}", source, "require", distrusted)
            index += 1
            if item["origin"] == "blocked":
                missing.append(source)
                self._say(f"  BLOCKED: required source {source!r} (policy denied the tool)")
            elif item["origin"] == "missing":
                missing.append(source)
                self._say(f"  MISSING: required source {source!r} (tool failed)")
            else:
                self.evidence.append(item)
                self._say(
                    f"  collected {item['id']} from {source} (origin: {item['origin']})"
                )
            self.trace.record("collect_evidence", "evidence_collected", item)
        for source in policy["optional"]:
            item = self._collect_one(f"E{index}", source, "optional", distrusted)
            if item["origin"] in ("blocked", "missing"):
                self._say(f"  optional source {source!r} unavailable; continuing")
                self.trace.record("collect_evidence", "evidence_unavailable", item)
                continue
            index += 1
            self.evidence.append(item)
            self._say(f"  collected {item['id']} from {source} (optional)")
            self.trace.record("collect_evidence", "evidence_collected", item)
        for source in dict.fromkeys(policy["distrusted"]):
            self._say(f"  distrusted source noted: {source} (will not be sole support)")
            self.trace.record("collect_evidence", "source_distrusted", {"source": source})
        self.signals["missing_evidence"] = bool(missing)
        if missing:
            self.trace.record(
                "collect_evidence", "missing_evidence", {"sources": missing}
            )
        if not self.evidence and not policy["required"]:
            self._say("  warning: no required evidence declared")
            self.trace.record("collect_evidence", "no_evidence_required", {})
        self._phase_done(
            "collect_evidence",
            detail=f"{len(self.evidence)} item(s), {len(missing)} missing",
        )

    def _collect_one(
        self, evidence_id: str, source: str, stance: str, distrusted: set[str]
    ) -> dict[str, Any]:
        base = {
            "id": evidence_id,
            "source": source,
            "stance": stance,
            "trusted": source not in distrusted,
        }
        if source in self.seed_evidence:
            seeded = self.seed_evidence[source]
            return {**base, "summary": seeded["summary"], "origin": seeded["origin"]}
        if self.registry is not None:
            tool = self.registry.tool_for_source(source)
            if tool is not None:
                try:
                    content = self.gate.invoke(tool.action, tool.handler, source)
                    return {**base, "summary": content, "origin": f"tool:{tool.action}"}
                except ActionDenied:
                    return {**base, "summary": None, "origin": "blocked"}
                except ToolError as exc:
                    self.trace.record(
                        "collect_evidence",
                        "tool_failed",
                        {"source": source, "error": str(exc)},
                    )
                    return {**base, "summary": None, "origin": "missing"}
            if stance == "require":
                # A workspace is in play but nothing serves this source.
                return {**base, "summary": None, "origin": "missing"}
            return {**base, "summary": None, "origin": "missing"}
        return {
            **base,
            "summary": f"[simulated] evidence collected from '{source}'",
            "origin": "simulated",
        }

    def _build_messages(self) -> None:
        self._phase("build_messages", "assemble the staged prompt plan")
        system, user = assemble_messages(self.plan, self.evidence)
        self.messages = {"system": system, "user": user}
        record_prompts = self.plan.get("trace_policy", {}).get("record_prompts", True)
        detail: dict[str, Any] = {
            "system_chars": len(system),
            "user_chars": len(user),
            "blocks": [b["phase"] for b in self.plan["prompt_plan"]["blocks"]],
        }
        if record_prompts:
            detail["system"] = system
            detail["user"] = user
        self.trace.record("build_messages", "messages_built", detail)
        self._say(f"  system: {len(system)} chars, user: {len(user)} chars")
        self._phase_done("build_messages")

    def _call_backend(self) -> bool:
        self._phase("call_backend", f"invoke cognition (backend: {self.backend.name})")
        try:
            self.response = self.backend.respond(
                self.plan, self.evidence, self.messages["system"], self.messages["user"]
            )
        except Exception as exc:
            self._backend_error = str(exc)
            self._say(f"  backend error: {exc}")
            self.trace.record("call_backend", "backend_failed", {"error": str(exc)})
            self._phase_done("call_backend", "failed", str(exc))
            return False
        self.trace.record(
            "call_backend",
            "backend_responded",
            {
                "model": self.response.model,
                "latency_ms": self.response.latency_ms,
                "usage": self.response.usage,
                "finish_reason": self.response.finish_reason,
                "raw_chars": len(self.response.raw_text),
            },
        )
        self._say(
            f"  model: {self.response.model}, latency: {self.response.latency_ms}ms"
        )
        self._phase_done("call_backend")
        return True

    def _parse_output(self) -> bool:
        self._phase("parse_output", "parse and normalize the model's reply")
        payload = self.response.parsed if self.response else None
        if payload is None:
            self._backend_error = "backend reply is not a JSON object"
            self.trace.record(
                "parse_output",
                "parse_failed",
                {"raw_prefix": (self.response.raw_text[:200] if self.response else "")},
            )
            self._say("  could not parse the backend reply as JSON")
            self._phase_done("parse_output", "failed", self._backend_error)
            return False
        raw_output = payload.get("output")
        self.outputs = dict(raw_output) if isinstance(raw_output, dict) else {}

        # Citations: drop ids that point at evidence never collected. The
        # trace keeps the dropped ones; the result stays conformant.
        valid_ids = {item["id"] for item in self.evidence}
        raw_citations = payload.get("citations") or []
        if isinstance(raw_citations, str):
            raw_citations = [raw_citations]
        cited = [str(c) for c in raw_citations]
        self.citations = [c for c in cited if c in valid_ids]
        dropped = [c for c in cited if c not in valid_ids]
        if dropped:
            self.trace.record(
                "parse_output", "citations_dropped", {"citations": dropped}
            )
            self._say(f"  dropped citations to uncollected evidence: {dropped}")

        # Confidence: clamp, then calibrate before any rule fires.
        try:
            raw_conf = float(payload.get("confidence"))
        except (TypeError, ValueError):
            raw_conf = None
        if raw_conf is not None:
            self.raw_confidence = min(1.0, max(0.0, raw_conf))
            self.confidence = calibrate(self.raw_confidence, self.plan["calibration"])
            self._say(
                f"  confidence: raw={self.raw_confidence:.2f} "
                f"calibrated={self.confidence:.2f}"
            )
        declared = {f["name"] for f in self.plan["output_schema"]["fields"]}
        if "confidence" in declared and self.confidence is not None:
            self.outputs["confidence"] = self.confidence
        extras = [k for k in self.outputs if k not in declared]
        for key in extras:
            del self.outputs[key]
        if extras:
            self.trace.record("parse_output", "extra_fields_dropped", {"fields": extras})
        self.trace.record(
            "parse_output",
            "output_parsed",
            {
                "fields": sorted(self.outputs),
                "citations": self.citations,
                "raw_confidence": self.raw_confidence,
                "calibrated_confidence": self.confidence,
            },
        )
        self._phase_done("parse_output")
        return True

    # -- verification ------------------------------------------------------

    def _skip_verification(self) -> dict[str, Any]:
        self._phase("verify_output", "skipped (no output to verify)")
        self._phase_done("verify_output", "skipped", "no parsed output")
        self.phases.append(
            {"name": "apply_uncertainty_policy", "status": "skipped",
             "detail": "no parsed output"}
        )
        self.trace.record(
            "apply_uncertainty_policy", "phase_started", {"title": "skipped"}
        )
        return {"passed": False, "checks": [], "tiers": {}}

    def _verify_output(self) -> dict[str, Any]:
        which = f"judge: {self.judge.name}" if self.judge else "machine checks only"
        self._phase("verify_output", f"run verification checklist ({which})")
        checks: list[dict[str, Any]] = [self._schema_check()]
        for rule in self.plan["verification_policy"]["rules"]:
            status, note, judged_by = self._evaluate_check(rule)
            entry = {
                "id": rule["rule_id"],
                "rule": rule["description"],
                "mode": rule["check"]["mode"],
                "status": status,
                "note": note,
            }
            if judged_by is not None:
                entry["judged_by"] = judged_by
            checks.append(entry)
        for check in checks:
            label = f" via {check['judged_by']}" if check.get("judged_by") else ""
            self._say(f"  {check['id']} [{check['status'].upper()}]{label} {check['rule']}")
            # Record a snapshot, not the live dict: the trace must stay an
            # independent witness of what happened at this moment.
            self.trace.record("verify_output", "check_evaluated", dict(check))

        passed = all(c["status"] != "fail" for c in checks)
        # Keep the two trust tiers visible and separate: a machine check is a
        # proof; a judged check is a model's opinion. They are reported apart
        # so neither is mistaken for the other.
        tiers = {
            tier: self._tier_summary(checks, tier) for tier in ("machine", "judged")
        }
        self.trace.record(
            "verify_output", "checklist_completed", {"passed": passed, "tiers": tiers}
        )
        self._phase_done("verify_output", detail="passed" if passed else "failed")
        return {"passed": passed, "checks": checks, "tiers": tiers}

    def _schema_check(self) -> dict[str, Any]:
        """The implicit machine check V0: outputs conform to the schema."""
        problems: list[str] = []
        for field in self.plan["output_schema"]["fields"]:
            name = field["name"]
            if name not in self.outputs:
                if field.get("optional"):
                    self.outputs[name] = None
                    continue
                problems.append(f"missing required field {name!r}")
                continue
            if not _type_conforms(self.outputs[name], field):
                problems.append(
                    f"field {name!r} is not of type {field['type']!r} "
                    f"(got {type(self.outputs[name]).__name__})"
                )
        status = "fail" if problems else "pass"
        note = "; ".join(problems) if problems else "all output fields conform to the schema"
        return {
            "id": "V0",
            "rule": "output conforms to the declared schema",
            "mode": "machine",
            "status": status,
            "note": note,
        }

    @staticmethod
    def _tier_summary(checks: list[dict[str, Any]], tier: str) -> dict[str, Any]:
        members = [c for c in checks if c["mode"] == tier]
        return {
            "total": len(members),
            "passed": sum(c["status"] == "pass" for c in members),
            "failed": sum(c["status"] == "fail" for c in members),
            "skipped": sum(c["status"] == "skipped" for c in members),
        }

    def _text_corpus(self) -> str:
        """All textual output, for phrase checks."""
        parts = [v for v in self.outputs.values() if isinstance(v, str)]
        if self.response and self.response.parsed:
            notes = self.response.parsed.get("notes")
            if isinstance(notes, str):
                parts.append(notes)
        return "\n".join(parts).lower()

    def _evaluate_check(self, rule: dict[str, Any]) -> tuple[str, str, str | None]:
        check = rule["check"]
        kind = check["kind"]
        if kind == "cites_evidence":
            if not self.evidence:
                return "fail", "no evidence was collected to cite", None
            if not self.citations:
                return "fail", "result cites no collected evidence", None
            return "pass", f"result cites collected evidence: {', '.join(self.citations)}", None
        if kind == "requires_phrase":
            phrase = check["arg"]
            if phrase in self._text_corpus():
                return "pass", f"output includes required phrase '{phrase}'", None
            return "fail", f"output missing required phrase '{phrase}'", None
        if kind == "threshold_check":
            metric, op, value = check["metric"], check["op"], check["value"]
            observed = self._metric_value(metric)
            if observed is None:
                return "skipped", f"metric {metric!r} not evaluable for this run", None
            ok = _OPS[op](observed, value)
            note = f"{metric} {observed:.2f} {op} {value}"
            return ("pass" if ok else "fail"), note, None
        # Judged rule: run the LLM judge if one is configured (separate trust
        # tier). With no judge, record as skipped — never silently passed.
        if self.judge is not None:
            verdict = self.judge.judge(rule["description"], self._judge_context())
            return ("pass" if verdict.passed else "fail"), verdict.rationale, self.judge.name
        return "skipped", "judged rule; no judge configured (recorded, not evaluated)", None

    def _metric_value(self, metric: str) -> float | None:
        if metric == "confidence":
            return self.confidence
        value = self.outputs.get(metric)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        return None

    def _judge_context(self) -> dict[str, Any]:
        return {
            "objective": self.plan["objective"],
            "outputs": self.outputs,
            "confidence": self.confidence,
            "citations": self.citations,
            "evidence": [
                {"id": e["id"], "source": e["source"], "summary": e.get("summary")}
                for e in self.evidence
            ],
        }

    # -- uncertainty -------------------------------------------------------

    def _apply_uncertainty_policy(self) -> None:
        self._phase(
            "apply_uncertainty_policy",
            "apply uncertainty policy (calibrated confidence + signals)",
        )
        for rule in self.plan["uncertainty_policy"]["rules"]:
            condition = rule["condition"]
            if condition["kind"] == "threshold":
                self._apply_threshold_rule(rule)
            else:
                self._apply_signal_rule(rule)
        self._phase_done(
            "apply_uncertainty_policy",
            detail=f"{len(self.escalations)} escalation(s)",
        )

    def _decision(
        self, rule: dict[str, Any], evaluable: bool, triggered: bool, observed: Any = None
    ) -> None:
        decision = {
            "condition": rule["condition"]["text"],
            "action": rule["action"]["name"],
            "evaluable": evaluable,
            "triggered": triggered,
            "observed": observed,
        }
        self.uncertainty_decisions.append(decision)
        event = "rule_evaluated" if evaluable else "rule_not_evaluable"
        self.trace.record("apply_uncertainty_policy", event, decision)

    def _apply_threshold_rule(self, rule: dict[str, Any]) -> None:
        condition = rule["condition"]
        observed = self._metric_value(condition["metric"])
        if observed is None:
            self._say(f"  rule '{condition['text']}': metric not evaluable, recorded")
            self._decision(rule, evaluable=False, triggered=False)
            return
        triggered = _OPS[condition["op"]](observed, condition["threshold"])
        self._say(
            f"  rule 'if {condition['text']} -> {rule['action']['name']}': "
            f"observed {condition['metric']}={observed:.2f}, "
            f"{'TRIGGERED' if triggered else 'not triggered'}"
        )
        self._decision(rule, evaluable=True, triggered=triggered, observed=round(observed, 3))
        if triggered:
            self._execute_uncertainty_action(rule["action"]["name"], condition["text"])

    def _signal_value(self, signal: str) -> bool | None:
        """Evaluate a known symbolic signal, or None when not evaluable."""
        if signal == "missing_evidence":
            return self.signals.get("missing_evidence", False)
        if signal == "security_risk":
            flagged = bool(
                self.response
                and self.response.parsed
                and self.response.parsed.get("security_risk") is True
            )
            return flagged or self.plan["risk_profile"]["level"] == "high"
        if signal == "competing_hypotheses":
            if self.response and self.response.parsed is not None:
                alternatives = self.response.parsed.get("alternatives")
                if isinstance(alternatives, list):
                    return len(alternatives) >= 1
            return None
        return None

    def _apply_signal_rule(self, rule: dict[str, Any]) -> None:
        condition = rule["condition"]
        value = self._signal_value(condition.get("signal") or "")
        if value is None:
            self._say(
                f"  rule 'if {condition['text']} -> {rule['action']['name']}': "
                "signal has no evaluator, recorded for audit"
            )
            self._decision(rule, evaluable=False, triggered=False)
            return
        self._say(
            f"  rule 'if {condition['text']} -> {rule['action']['name']}': "
            f"{'TRIGGERED' if value else 'not triggered'}"
        )
        self._decision(rule, evaluable=True, triggered=value, observed=value)
        if value:
            self._execute_uncertainty_action(rule["action"]["name"], condition["text"])

    def _execute_uncertainty_action(self, action: str, condition: str) -> None:
        if action == "ask_human":
            escalation = {
                "reason": condition,
                "question": (
                    f"Uncertainty condition '{condition}' holds for goal "
                    f"'{self.plan['goal']}'. A human must review before the "
                    "result is acted on."
                ),
            }
            self.escalations.append(escalation)
            self._status_hints.add("needs_human")
            self._say("    -> escalated to human (run status will be needs_human)")
            self.trace.record("apply_uncertainty_policy", "human_escalation", escalation)
        elif action == "block_action":
            block = {"reason": condition, "action": "block_action"}
            self.escalations.append(block)
            self._status_hints.add("blocked")
            self._say("    -> BLOCKED by policy (run status will be blocked)")
            self.trace.record("apply_uncertainty_policy", "action_blocked_by_policy", block)
        else:
            self._say(f"    -> action '{action}' recorded (no executor in this runtime)")
            self.trace.record(
                "apply_uncertainty_policy",
                "action_recorded",
                {"action": action, "reason": condition},
            )

    # -- action policy -------------------------------------------------------

    def _enforce_action_policy(self) -> None:
        """Summarize every gate decision made during the run, and re-assert
        (defense in depth) that no denied action was ever invoked."""
        self._phase("enforce_action_policy", "review action gate decisions")
        denied = set(self.plan["action_policy"]["denied"])
        invoked, blocked, approved = [], [], []
        for event in self.trace.to_list():
            detail = event.get("detail", {})
            if event["event"] == "tool_invoked":
                invoked.append(detail.get("action"))
            elif event["event"] in ("action_blocked", "approval_denied"):
                blocked.append(
                    {"action": detail.get("action"), "reason": detail.get("reason")}
                )
            elif event["event"] == "approval_granted":
                approved.append(detail.get("action"))
        violations = [a for a in invoked if a in denied]
        self.action_decisions = {
            "invoked": invoked,
            "blocked": blocked,
            "approved": approved,
            "denied_by_plan": sorted(denied),
            "violations": violations,
        }
        self.trace.record(
            "enforce_action_policy", "policy_reviewed", self.action_decisions
        )
        if violations:  # the gate makes this unreachable, but never trust one layer
            self._status_hints.add("blocked")
            self._phase_done("enforce_action_policy", "failed", "denied action ran")
            return
        self._say(
            f"  invoked: {invoked or '(none)'}; blocked: "
            f"{[b['action'] for b in blocked] or '(none)'}"
        )
        self._phase_done("enforce_action_policy")

    # -- finalize ------------------------------------------------------------

    def _resolve_status(self, verification: dict[str, Any]) -> str:
        if self._backend_error is not None:
            return "backend_error"
        if "blocked" in self._status_hints:
            return "blocked"
        if "needs_human" in self._status_hints:
            return "needs_human"
        if not verification["passed"]:
            return "failed_verification"
        return "completed"

    def _finalize(self, verification: dict[str, Any]) -> dict[str, Any]:
        self._phase("finalize", "resolve final status and assemble the result")
        status = self._resolve_status(verification)
        self.trace.record("finalize", "status_resolved", {"status": status})
        self._phase_done("finalize", detail=status)

        self._phase("trace", "seal the trace")
        self.trace.record(
            "trace", "run_completed", {"status": status, "goal": self.plan["goal"]}
        )
        self._phase_done("trace")

        trace_events = self.trace.to_list()
        summary = self._summarize(status, verification, trace_events)
        self._say(f"\nrun status: {status}")
        return {
            "goal": self.plan["goal"],
            "backend": self.backend.name,
            "model": self.response.model if self.response else None,
            "status": status,
            "phases": self.phases,
            "diagnostics": self.diagnostics,
            "messages": self.messages,
            "evidence": self.evidence,
            "backend_response": self.response.to_dict() if self.response else None,
            "backend_error": self._backend_error,
            "outputs": self.outputs,
            "citations": self.citations,
            "confidence": {
                "raw": self.raw_confidence,
                "calibrated": self.confidence,
            },
            "verification": verification,
            "uncertainty": {
                "signals": self.signals,
                "decisions": self.uncertainty_decisions,
            },
            "action_decisions": getattr(self, "action_decisions", {}),
            "escalations": self.escalations,
            "summary": summary,
            "trace_id": summary["trace_id"],
            "trace": trace_events,
            "trace_chain": self.trace.seal(),
        }

    def _summarize(
        self,
        status: str,
        verification: dict[str, Any],
        trace_events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """A flat, human-first summary of the run. ``trace_id`` is a
        deterministic hash of the plan and trace so identical runs produce
        identical ids (the wall-clock timestamp lives only in the saved trace
        artifact)."""
        requested = [
            e["detail"]["action"] for e in trace_events if e["event"] == "tool_invoked"
        ]
        blocked = [
            {"action": e["detail"].get("action"), "reason": e["detail"].get("reason")}
            for e in trace_events
            if e["event"] in ("action_blocked", "approval_denied")
        ]
        digest = hashlib.sha256(
            json.dumps(
                {"plan": self.plan, "trace": trace_events},
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        ).hexdigest()[:16]
        return {
            "trace_id": digest,
            "status": status,
            "confidence": self.confidence,
            "verification_status": "passed" if verification["passed"] else "failed",
            "uncertainty_status": "escalated" if self.escalations else "clear",
            "actions_requested": requested,
            "actions_blocked": blocked,
            "escalation_count": len(self.escalations),
        }


#: Backwards-compatible alias (the runtime is no longer simulation-only).
SimulationRuntime = GoalRuntime


def execute_program(
    program,
    goal: str | None = None,
    *,
    backend: CognitionBackend | None = None,
    printer: Callable[[str], None] | None = None,
    workspace: str | None = None,
    approved_actions: set[str] | None = None,
    judge: Judge | None = None,
    approver: Approver | None = None,
    registry: ToolRegistry | None = None,
    sign_key: bytes | None = None,
) -> dict[str, Any]:
    """Run one goal of a parsed program through *all* canonical phases:
    analyze, compile, then the runtime phases. Returns a result whose status
    is ``failed_validation`` (with diagnostics) when the analyzer finds
    errors, without invoking any backend."""
    from intentflow.analyzer import analyze_program, errors_in
    from intentflow.compiler import CompileError, compile_program

    diagnostics = analyze_program(program)
    diag_dicts = [d.to_dict() for d in diagnostics]
    pre = [{"name": "parse", "status": "completed", "detail": program.source_name}]
    errors = errors_in(diagnostics)
    if errors:
        pre.append(
            {"name": "analyze", "status": "failed", "detail": f"{len(errors)} error(s)"}
        )
        return _validation_failure(program, diag_dicts, pre)
    pre.append(
        {"name": "analyze", "status": "completed",
         "detail": f"{len(diagnostics)} diagnostic(s), 0 errors"}
    )
    try:
        document = compile_program(program)
    except CompileError as exc:
        pre.append({"name": "compile", "status": "failed", "detail": str(exc)})
        return _validation_failure(program, diag_dicts, pre)
    pre.append({"name": "compile", "status": "completed", "detail": ""})

    plans = {p["goal"]: p for p in document["goals"]}
    if goal is None:
        plan = document["goals"][0]
    elif goal in plans:
        plan = plans[goal]
    else:
        raise ValueError(f"unknown goal {goal!r}; available: {sorted(plans)}")
    runtime = GoalRuntime(
        plan,
        backend=backend,
        printer=printer,
        workspace=workspace,
        approved_actions=approved_actions,
        judge=judge,
        approver=approver,
        registry=registry,
        sign_key=sign_key,
        pre_phases=pre,
        diagnostics=diag_dicts,
    )
    return runtime.run()


def _validation_failure(
    program, diagnostics: list[dict[str, Any]], phases: list[dict[str, Any]]
) -> dict[str, Any]:
    goal_name = program.goals[0].name if program.goals else None
    return {
        "goal": goal_name,
        "backend": None,
        "model": None,
        "status": "failed_validation",
        "phases": phases,
        "diagnostics": diagnostics,
        "messages": {},
        "evidence": [],
        "backend_response": None,
        "backend_error": None,
        "outputs": {},
        "citations": [],
        "confidence": {"raw": None, "calibrated": None},
        "verification": {"passed": False, "checks": [], "tiers": {}},
        "uncertainty": {"signals": {}, "decisions": []},
        "action_decisions": {},
        "escalations": [],
        "summary": {
            "trace_id": None,
            "status": "failed_validation",
            "confidence": None,
            "verification_status": "not_run",
            "uncertainty_status": "not_run",
            "actions_requested": [],
            "actions_blocked": [],
            "escalation_count": 0,
        },
        "trace_id": None,
        "trace": [],
        "trace_chain": None,
    }


#: Statuses ordered from best to worst, for pipeline aggregation.
_STATUS_SEVERITY = {
    "completed": 0,
    "needs_human": 1,
    "failed_verification": 2,
    "blocked": 3,
    "backend_error": 4,
    "failed_validation": 5,
}


def run_pipeline(
    document: dict[str, Any],
    pipeline_name: str,
    backend: CognitionBackend | None = None,
    printer: Callable[[str], None] | None = None,
    workspace: str | None = None,
    approved_actions: set[str] | None = None,
    judge: Judge | None = None,
    approver: Approver | None = None,
    registry: ToolRegistry | None = None,
    sign_key: bytes | None = None,
) -> dict[str, Any]:
    """Run a compiled pipeline: stages execute in order, and each stage's
    structured outputs become addressable evidence (``Goal.field``) for
    later stages. Each stage keeps its own trace; the combined trace tags
    every event with its stage for end-to-end auditing. Execution stops at
    the first stage that does not complete; the pipeline takes that stage's
    status."""
    pipeline = next(
        (p for p in document["pipelines"] if p["name"] == pipeline_name), None
    )
    if pipeline is None:
        raise ValueError(f"pipeline {pipeline_name!r} not found in compiled document")
    plans = {plan["goal"]: plan for plan in document["goals"]}

    outputs_by_goal: dict[str, dict[str, Any]] = {}
    stage_results: list[dict[str, Any]] = []
    combined_trace: list[dict[str, Any]] = []
    status = "completed"

    for stage_name in pipeline["stages"]:
        plan = plans[stage_name]
        seed: list[dict[str, Any]] = []
        for source in plan["evidence_policy"]["required"]:
            origin_goal, _, field_name = source.partition(".")
            if origin_goal in outputs_by_goal and field_name in outputs_by_goal[origin_goal]:
                seed.append(
                    {
                        "source": source,
                        "summary": str(outputs_by_goal[origin_goal][field_name]),
                        "origin": f"pipeline:{origin_goal}",
                    }
                )
        if printer is not None:
            printer(f"\n##### pipeline '{pipeline_name}' stage: {stage_name} #####")
        runtime = GoalRuntime(
            plan,
            backend=backend,
            printer=printer,
            workspace=workspace,
            approved_actions=approved_actions,
            seed_evidence=seed,
            judge=judge,
            approver=approver,
            registry=registry,
            sign_key=sign_key,
        )
        result = runtime.run()
        outputs_by_goal[stage_name] = result["outputs"]
        stage_results.append(result)
        combined_trace.extend({**event, "stage": stage_name} for event in result["trace"])
        if _STATUS_SEVERITY[result["status"]] > _STATUS_SEVERITY[status]:
            status = result["status"]
        if result["status"] != "completed":
            break

    return {
        "pipeline": pipeline_name,
        "status": status,
        "stages": stage_results,
        "trace": combined_trace,
    }
