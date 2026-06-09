"""Runtime for compiled IntentFlow execution plans.

The runtime is an explicit phase machine. Cognition is a pluggable backend
(:mod:`intentflow.backends`); everything that makes the process *governed*
lives here, outside the model:

* evidence collection runs through the :class:`~intentflow.tools.ActionGate`,
  so a tool the goal does not allow cannot run, full stop;
* raw model confidence is calibrated before any uncertainty rule fires;
* uncertainty actions (``ask_human``, ``run_discriminating_test``) are
  control flow with trace records;
* verification executes the *typed* checks the compiler emitted — machine
  checks are evaluated, judged checks are recorded as skipped, never
  silently passed;
* every event lands in an append-only trace that ``intentflow audit`` can
  later replay against the plan.
"""

from __future__ import annotations

import hashlib
import json
import operator
from typing import Any, Callable

from intentflow.backends import CognitionBackend, Hypothesis, SimulatedCognition
from intentflow.tools import ActionDenied, ActionGate, ToolError, ToolRegistry

#: The phase order every conformant run must follow (checked by the auditor).
CANONICAL_PHASES: tuple[str, ...] = (
    "context",
    "actions",
    "evidence",
    "model",
    "uncertainty",
    "verify",
    "output",
)

#: Two hypotheses are 'competing' when their confidences are this close.
_COMPETING_MARGIN = 0.15

_OPS: dict[str, Callable[[float, float], bool]] = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
}


class Trace:
    """An auditable, append-only record of everything the runtime did."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def record(self, phase: str, event: str, detail: dict[str, Any] | None = None) -> None:
        self.events.append(
            {
                "seq": len(self.events) + 1,
                "phase": phase,
                "event": event,
                "detail": detail or {},
            }
        )

    def to_list(self) -> list[dict[str, Any]]:
        return list(self.events)


def calibrate(raw: float, policy: dict[str, Any]) -> float:
    """Map raw self-reported confidence to calibrated confidence."""
    if policy.get("method") == "shrinkage":
        midpoint = policy.get("midpoint", 0.5)
        factor = policy.get("factor", 0.8)
        return round(midpoint + (raw - midpoint) * factor, 4)
    return raw


class GoalRuntime:
    """Executes one compiled execution-plan dict for a single goal."""

    def __init__(
        self,
        plan: dict[str, Any],
        backend: CognitionBackend | None = None,
        printer: Callable[[str], None] | None = print,
        workspace: str | None = None,
        approved_actions: set[str] | None = None,
        seed_evidence: list[dict[str, Any]] | None = None,
    ) -> None:
        self.plan = plan
        self.backend = backend or SimulatedCognition()
        self.trace = Trace()
        self.gate = ActionGate(plan["actions"], trace=self.trace, approved=approved_actions)
        self.registry = ToolRegistry.builtin(workspace) if workspace else None
        self.seed_evidence = {item["source"]: item for item in (seed_evidence or [])}
        self._printer = printer
        self.evidence: list[dict[str, Any]] = []
        self.hypotheses: list[Hypothesis] = []
        self.proposed_fix: str | None = None
        self.escalations: list[dict[str, Any]] = []

    # -- helpers ----------------------------------------------------------

    def _say(self, text: str) -> None:
        if self._printer is not None:
            self._printer(text)

    def _phase(self, name: str, title: str) -> None:
        self._say(f"\n=== phase: {name} — {title} ===")
        self.trace.record(name, "phase_started", {"title": title})

    def _top(self) -> Hypothesis | None:
        return self.hypotheses[0] if self.hypotheses else None

    # -- phases -----------------------------------------------------------

    def run(self) -> dict[str, Any]:
        self.trace.record(
            "init",
            "run_started",
            {"goal": self.plan["goal"], "backend": self.backend.name},
        )
        self._say(
            f"IntentFlow run: goal '{self.plan['goal']}' (backend: {self.backend.name})"
        )
        self._say(f"objective: {self.plan['objective']}")

        self._apply_context_policy()
        self._declare_action_governance()
        self._collect_evidence()
        self._generate_hypotheses()
        self._apply_uncertainty_policy()
        verification = self._apply_verification()
        outputs = self._produce_outputs(verification)

        self.trace.record("done", "run_completed", {"status": "completed"})
        trace_events = self.trace.to_list()
        summary = self._summarize(verification, trace_events)
        return {
            "goal": self.plan["goal"],
            "backend": self.backend.name,
            "status": "completed",
            "outputs": outputs,
            "summary": summary,
            "trace_id": summary["trace_id"],
            "hypotheses": [h.to_dict() for h in self.hypotheses],
            "evidence": self.evidence,
            "verification": verification,
            "escalations": self.escalations,
            "trace": trace_events,
        }

    def _summarize(
        self, verification: dict[str, Any], trace_events: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """A flat, human-first summary of the run: what was decided, which
        actions ran, which were blocked. ``trace_id`` is a deterministic hash
        of the plan and trace so identical runs produce identical ids (the
        wall-clock timestamp lives only in the saved trace artifact)."""
        requested = [
            e["detail"]["action"]
            for e in trace_events
            if e["event"] == "tool_invoked"
        ]
        blocked = [
            {"action": e["detail"].get("action"), "reason": e["detail"].get("reason")}
            for e in trace_events
            if e["event"] in ("action_blocked", "approval_denied")
        ]
        top = self._top()
        digest = hashlib.sha256(
            json.dumps(
                {"plan": self.plan, "trace": trace_events},
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        ).hexdigest()[:16]
        return {
            "trace_id": digest,
            "confidence": round(top.confidence, 3) if top else None,
            "verification_status": "passed" if verification["passed"] else "failed",
            "uncertainty_status": "escalated" if self.escalations else "clear",
            "actions_requested": requested,
            "actions_blocked": blocked,
            "escalation_count": len(self.escalations),
        }

    def _apply_context_policy(self) -> None:
        self._phase("context", "apply context/memory policy")
        policy = self.plan["context_policy"]
        if policy.get("max_tokens"):
            self._say(f"  context budget: {policy['max_tokens']} tokens")
        for item in policy.get("prefer", []):
            self._say(f"  prioritizing in context: {item}")
        for item in policy.get("preserve", []):
            self._say(f"  pinned (never evicted): {item}")
        self.trace.record("context", "policy_applied", policy)

    def _declare_action_governance(self) -> None:
        self._phase("actions", "establish action governance")
        actions = self.plan["actions"]
        for action in actions["allowed"]:
            self._say(f"  allowed: {action}")
        for action in actions["approval_required"]:
            self._say(f"  approval-gated: {action} (human approval required before use)")
        for action in actions["denied"]:
            self._say(f"  denied: {action}")
        self.trace.record("actions", "governance_established", actions)

    def _collect_evidence(self) -> None:
        self._phase("evidence", "collect required evidence")
        distrusted = self.plan["evidence"]["distrusted"]
        distrusted_set = set(distrusted)
        for i, source in enumerate(self.plan["evidence"]["required"], start=1):
            item = self._collect_one(f"E{i}", source, distrusted_set)
            self.evidence.append(item)
            self._say(f"  collected {item['id']} from {source} (origin: {item['origin']})")
            self.trace.record("evidence", "evidence_collected", item)
        # Iterate the list (not a set) so trace order is deterministic.
        for source in dict.fromkeys(distrusted):
            self._say(f"  distrusted source noted: {source} (will not be sole support)")
            self.trace.record("evidence", "source_distrusted", {"source": source})
        if not self.evidence:
            self._say("  warning: no required evidence declared")
            self.trace.record("evidence", "no_evidence_required", {})

    def _collect_one(
        self, evidence_id: str, source: str, distrusted: set[str]
    ) -> dict[str, Any]:
        base = {
            "id": evidence_id,
            "source": source,
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
                except ActionDenied as exc:
                    self._say(f"  BLOCKED: {exc} (falling back to simulated evidence)")
                except ToolError as exc:
                    self.trace.record(
                        "evidence",
                        "tool_failed",
                        {"source": source, "error": str(exc)},
                    )
                    self._say(f"  tool failed for {source}: {exc} (simulated fallback)")
        return {
            **base,
            "summary": f"[simulated] evidence collected from '{source}'",
            "origin": "simulated",
        }

    def _generate_hypotheses(self) -> None:
        self._phase("model", f"generate hypotheses (backend: {self.backend.name})")
        for directive in self.plan["model_directives"]:
            self._say(f"  modeling directive: {directive}")
        proposal = self.backend.propose(self.plan, self.evidence)
        self.proposed_fix = proposal.proposed_fix
        policy = self.plan["calibration"]
        for hyp in proposal.hypotheses:
            hyp.confidence = calibrate(hyp.raw_confidence, policy)
            self.hypotheses.append(hyp)
            self._say(
                f"  {hyp.hypothesis_id}: raw={hyp.raw_confidence:.2f} "
                f"calibrated={hyp.confidence:.2f} citations={hyp.citations or 'NONE'}"
            )
            self.trace.record("model", "hypothesis_proposed", hyp.to_dict())
        self.hypotheses.sort(key=lambda h: h.confidence, reverse=True)
        if self.proposed_fix:
            self.trace.record("model", "fix_proposed", {"text": self.proposed_fix})

    # -- uncertainty -------------------------------------------------------

    def _apply_uncertainty_policy(self) -> None:
        self._phase("uncertainty", "apply uncertainty policy (calibrated confidence)")
        for rule in self.plan["uncertainty_policy"]:
            if rule["kind"] == "threshold":
                self._apply_threshold_rule(rule)
            else:
                self._apply_symbolic_rule(rule)

    def _apply_threshold_rule(self, rule: dict[str, Any]) -> None:
        top = self._top()
        if rule["metric"] != "confidence" or top is None:
            self._say(f"  rule '{rule['condition']}': metric not evaluable, skipped")
            self.trace.record("uncertainty", "rule_skipped", rule)
            return
        triggered = _OPS[rule["op"]](top.confidence, rule["threshold"])
        self._say(
            f"  rule 'if {rule['condition']} -> {rule['action']}': "
            f"top confidence={top.confidence:.2f}, "
            f"{'TRIGGERED' if triggered else 'not triggered'}"
        )
        self.trace.record(
            "uncertainty",
            "rule_evaluated",
            {**rule, "observed": round(top.confidence, 3), "triggered": triggered},
        )
        if triggered:
            self._execute_uncertainty_action(rule["action"], rule["condition"])

    def _apply_symbolic_rule(self, rule: dict[str, Any]) -> None:
        if "competing_hypotheses" in rule["condition"]:
            competing = (
                len(self.hypotheses) >= 2
                and self.hypotheses[0].confidence - self.hypotheses[1].confidence
                < _COMPETING_MARGIN
            )
            self._say(
                f"  rule 'if {rule['condition']} -> {rule['action']}': "
                f"{'TRIGGERED' if competing else 'not triggered'}"
            )
            self.trace.record(
                "uncertainty", "rule_evaluated", {**rule, "triggered": competing}
            )
            if competing:
                self._execute_uncertainty_action(rule["action"], rule["condition"])
        else:
            self._say(
                f"  rule 'if {rule['condition']} -> {rule['action']}': "
                "condition has no evaluator, recorded for audit"
            )
            self.trace.record("uncertainty", "rule_not_simulated", rule)

    def _execute_uncertainty_action(self, action: str, condition: str) -> None:
        if action == "ask_human":
            escalation = {
                "reason": condition,
                "question": "Confidence below policy threshold; proceed with top hypothesis?",
                "response": "[simulated human] approved: proceed, but flag result as reviewed",
            }
            self.escalations.append(escalation)
            self._say("    -> escalated to human (simulated approval received)")
            self.trace.record("uncertainty", "human_escalation", escalation)
        elif action == "run_discriminating_test" and len(self.hypotheses) >= 2:
            top, second = self.hypotheses[0], self.hypotheses[1]
            top.confidence = min(0.95, round(top.confidence + 0.18, 4))
            second.confidence = max(0.05, round(second.confidence - 0.10, 4))
            detail = {
                "test": f"[simulated] discriminating test between {top.hypothesis_id} "
                f"and {second.hypothesis_id}",
                "outcome": f"{top.hypothesis_id} supported",
                "new_confidences": {
                    top.hypothesis_id: round(top.confidence, 3),
                    second.hypothesis_id: round(second.confidence, 3),
                },
            }
            self.hypotheses.sort(key=lambda h: h.confidence, reverse=True)
            self._say(f"    -> ran discriminating test: {detail['outcome']}")
            self.trace.record("uncertainty", "discriminating_test", detail)
        else:
            self._say(f"    -> action '{action}' recorded (no evaluator)")
            self.trace.record("uncertainty", "action_recorded", {"action": action})

    # -- verification ------------------------------------------------------

    def _apply_verification(self) -> dict[str, Any]:
        self._phase("verify", "run verification checklist")
        checks: list[dict[str, Any]] = []
        for rule in self.plan["verification"]:
            status, note = self._evaluate_check(rule["check"])
            checks.append(
                {
                    "id": rule["id"],
                    "rule": rule["rule"],
                    "mode": rule["check"]["mode"],
                    "status": status,
                    "note": note,
                }
            )
            self._say(f"  {rule['id']} [{status.upper()}] {rule['rule']}")
            # Record a snapshot, not the live dict: the trace must stay an
            # independent witness of what happened at this moment.
            self.trace.record("verify", "check_evaluated", dict(checks[-1]))
        passed = all(c["status"] != "fail" for c in checks)
        self.trace.record("verify", "checklist_completed", {"passed": passed})
        return {"passed": passed, "checks": checks}

    def _evaluate_check(self, check: dict[str, str]) -> tuple[str, str]:
        kind = check["kind"]
        if kind == "cites_evidence":
            evidence_ids = {e["id"] for e in self.evidence}
            bad = [
                h.hypothesis_id
                for h in self.hypotheses
                if not h.citations or not set(h.citations) <= evidence_ids
            ]
            if bad:
                return "fail", f"hypotheses without valid citations: {', '.join(bad)}"
            return "pass", "every hypothesis cites collected evidence ids"
        if kind == "requires_phrase":
            phrase = check["arg"]
            if self.proposed_fix and phrase in self.proposed_fix.lower():
                return "pass", f"proposal includes required phrase '{phrase}'"
            return "fail", f"proposal missing required phrase '{phrase}'"
        if kind == "threshold_check":
            metric, op, value = check["metric"], check["op"], check["value"]
            top = self._top()
            if metric != "confidence" or top is None:
                return "skipped", f"metric '{metric}' not evaluable by the runtime"
            ok = _OPS[op](top.confidence, value)
            note = f"confidence {top.confidence:.2f} {op} {value}"
            return ("pass" if ok else "fail"), note
        # Judged rules need an LLM judge; recording them as skipped keeps the
        # trust boundary honest — they are never silently assumed to pass.
        return "skipped", "judged rule; requires an LLM judge (recorded, not evaluated)"

    # -- output ------------------------------------------------------------

    def _produce_outputs(self, verification: dict[str, Any]) -> dict[str, Any]:
        self._phase("output", "produce structured result")
        top = self._top()
        outputs: dict[str, Any] = {}
        for raw_field in self.plan["outputs"]:
            outputs[raw_field] = self._output_value(raw_field, top, verification)
            self._say(f"  {raw_field}: {outputs[raw_field]}")
        self.trace.record("output", "outputs_produced", outputs)
        return outputs

    def _output_value(
        self, name: str, top: Hypothesis | None, verification: dict[str, Any]
    ) -> Any:
        if top is None:
            return f"no hypothesis available for '{name}'"
        confidence = round(top.confidence, 3)
        known: dict[str, Any] = {
            "root_cause": top.statement,
            "confidence": confidence,
            "recommended_fix": self.proposed_fix
            or f"act on {top.hypothesis_id}: {top.statement}",
            "risk": "low" if confidence >= 0.7 and verification["passed"] else "medium",
            "findings": [h.to_dict() for h in self.hypotheses],
            "recommendation": f"act on {top.hypothesis_id}: {top.statement}",
            "answer": top.statement,
            "sources": [e["id"] for e in self.evidence],
            "open_questions": [
                h.statement for h in self.hypotheses[1:] if h.confidence >= 0.3
            ],
            "summary": f"[simulated] {top.statement}",
            "likely_cause": top.statement,
            "suggested_response": self.proposed_fix
            or f"Thanks for the report — based on {top.hypothesis_id}, {top.statement}",
            "proposed_labels": ["needs-triage"]
            + (["needs-reproduction"] if confidence < 0.7 else ["confirmed"]),
        }
        return known.get(name, f"[unmapped] value for '{name}'")


#: Backwards-compatible alias (the runtime is no longer simulation-only).
SimulationRuntime = GoalRuntime


def run_pipeline(
    document: dict[str, Any],
    pipeline_name: str,
    backend: CognitionBackend | None = None,
    printer: Callable[[str], None] | None = print,
    workspace: str | None = None,
    approved_actions: set[str] | None = None,
) -> dict[str, Any]:
    """Run a compiled pipeline: stages execute in order, and each stage's
    structured outputs become addressable evidence (``Goal.field``) for
    later stages. Each stage keeps its own trace; the combined trace tags
    every event with its stage for end-to-end auditing."""
    pipeline = next(
        (p for p in document["pipelines"] if p["name"] == pipeline_name), None
    )
    if pipeline is None:
        raise ValueError(f"pipeline {pipeline_name!r} not found in compiled document")
    plans = {plan["goal"]: plan for plan in document["plans"]}

    outputs_by_goal: dict[str, dict[str, Any]] = {}
    stage_results: list[dict[str, Any]] = []
    combined_trace: list[dict[str, Any]] = []

    for stage_name in pipeline["stages"]:
        plan = plans[stage_name]
        seed: list[dict[str, Any]] = []
        for source in plan["evidence"]["required"]:
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
        )
        result = runtime.run()
        outputs_by_goal[stage_name] = result["outputs"]
        stage_results.append(result)
        combined_trace.extend({**event, "stage": stage_name} for event in result["trace"])

    return {
        "pipeline": pipeline_name,
        "status": "completed",
        "stages": stage_results,
        "trace": combined_trace,
    }
