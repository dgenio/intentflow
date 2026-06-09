"""Simulation runtime for compiled IntentFlow execution plans.

No LLM API is required: every cognitive step is mocked deterministically so
that the *control structure* of the language — evidence gating, uncertainty
handling, governed actions, verification, escalation, tracing — can be
exercised, inspected and tested end to end.

The runtime is intentionally structured as explicit phases. A future
LLM-backed runtime should keep the same phase contract and trace format and
only replace the mocked cognition.
"""

from __future__ import annotations

import operator
from dataclasses import dataclass, field
from typing import Any, Callable

#: Deterministic mock confidences assigned to generated hypotheses, in order.
#: The first two are close together on purpose so that 'competing hypotheses'
#: uncertainty rules have something to react to in demos and tests.
_MOCK_CONFIDENCES: tuple[float, ...] = (0.68, 0.61, 0.34, 0.22)

#: Two hypotheses are 'competing' when their confidences are this close.
_COMPETING_MARGIN = 0.15

_OPS: dict[str, Callable[[float, float], bool]] = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
}


@dataclass
class Hypothesis:
    hypothesis_id: str
    statement: str
    confidence: float
    citations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.hypothesis_id,
            "statement": self.statement,
            "confidence": round(self.confidence, 3),
            "citations": list(self.citations),
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


class SimulationRuntime:
    """Executes one compiled :class:`~intentflow.compiler.ExecutionPlan` dict
    in simulation mode."""

    def __init__(
        self,
        plan: dict[str, Any],
        printer: Callable[[str], None] | None = print,
    ) -> None:
        self.plan = plan
        self.trace = Trace()
        self._printer = printer
        self.evidence: list[dict[str, Any]] = []
        self.hypotheses: list[Hypothesis] = []
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
            "init", "run_started", {"goal": self.plan["goal"], "mode": "simulate"}
        )
        self._say(f"IntentFlow simulation: goal '{self.plan['goal']}'")
        self._say(f"objective: {self.plan['objective']}")

        self._apply_context_policy()
        self._collect_evidence()
        self._declare_action_governance()
        self._generate_hypotheses()
        self._apply_uncertainty_policy()
        verification = self._apply_verification()
        outputs = self._produce_outputs(verification)

        self.trace.record("done", "run_completed", {"status": "completed"})
        return {
            "goal": self.plan["goal"],
            "status": "completed",
            "outputs": outputs,
            "hypotheses": [h.to_dict() for h in self.hypotheses],
            "evidence": self.evidence,
            "verification": verification,
            "escalations": self.escalations,
            "trace": self.trace.to_list(),
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

    def _collect_evidence(self) -> None:
        self._phase("evidence", "collect required evidence")
        required = self.plan["evidence"]["required"]
        distrusted = set(self.plan["evidence"]["distrusted"])
        for i, source in enumerate(required, start=1):
            item = {
                "id": f"E{i}",
                "source": source,
                "summary": f"[simulated] evidence collected from '{source}'",
                "trusted": source not in distrusted,
            }
            self.evidence.append(item)
            self._say(f"  collected {item['id']} from {source}")
            self.trace.record("evidence", "evidence_collected", item)
        for source in distrusted:
            self._say(f"  distrusted source noted: {source} (will not be sole support)")
            self.trace.record("evidence", "source_distrusted", {"source": source})
        if not self.evidence:
            self._say("  warning: no required evidence declared")
            self.trace.record("evidence", "no_evidence_required", {})

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

    def _generate_hypotheses(self) -> None:
        self._phase("model", "generate hypotheses (mocked cognition)")
        for directive in self.plan["model_directives"]:
            self._say(f"  modeling directive: {directive}")
        sources = self.evidence or [{"id": None, "source": "general reasoning"}]
        count = min(len(sources), len(_MOCK_CONFIDENCES))
        for i in range(max(count, 1)):
            source = sources[i % len(sources)]
            citations = [source["id"]] if source["id"] else []
            hyp = Hypothesis(
                hypothesis_id=f"H{i + 1}",
                statement=(
                    f"[simulated] the objective is most plausibly explained by "
                    f"signals found in {source['source']}"
                ),
                confidence=_MOCK_CONFIDENCES[i],
                citations=citations,
            )
            self.hypotheses.append(hyp)
            self._say(
                f"  {hyp.hypothesis_id}: confidence={hyp.confidence:.2f} "
                f"citations={hyp.citations or 'NONE'}"
            )
            self.trace.record("model", "hypothesis_proposed", hyp.to_dict())
        self.hypotheses.sort(key=lambda h: h.confidence, reverse=True)

    # -- uncertainty -------------------------------------------------------

    def _apply_uncertainty_policy(self) -> None:
        self._phase("uncertainty", "apply uncertainty policy")
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
                "condition has no simulator, recorded for the real runtime"
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
            top.confidence = min(0.95, top.confidence + 0.18)
            second.confidence = max(0.05, second.confidence - 0.10)
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
            self._say(f"    -> action '{action}' recorded (no simulator)")
            self.trace.record("uncertainty", "action_recorded", {"action": action})

    # -- verification ------------------------------------------------------

    def _apply_verification(self) -> dict[str, Any]:
        self._phase("verify", "run verification checklist")
        checks: list[dict[str, Any]] = []
        for rule in self.plan["verification"]:
            status, note = self._check_rule(rule["rule"])
            checks.append({"id": rule["id"], "rule": rule["rule"], "status": status, "note": note})
            self._say(f"  {rule['id']} [{status.upper()}] {rule['rule']}")
            self.trace.record("verify", "check_evaluated", checks[-1])
        passed = all(c["status"] != "fail" for c in checks)
        self.trace.record("verify", "checklist_completed", {"passed": passed})
        return {"passed": passed, "checks": checks}

    def _check_rule(self, rule_text: str) -> tuple[str, str]:
        text = rule_text.lower()
        if "cite" in text:
            uncited = [h.hypothesis_id for h in self.hypotheses if not h.citations]
            if uncited:
                return "fail", f"hypotheses without citations: {', '.join(uncited)}"
            return "pass", "every hypothesis cites at least one evidence id"
        if "rollback" in text:
            return "pass", "simulated fix includes an explicit rollback path"
        return "pass", "no simulator for this rule; assumed-pass (simulated)"

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
            return f"[simulated] no hypothesis available for '{name}'"
        confidence = round(top.confidence, 3)
        known: dict[str, Any] = {
            "root_cause": top.statement,
            "confidence": confidence,
            "recommended_fix": (
                f"[simulated] apply targeted fix for {top.hypothesis_id}. "
                "Rollback: revert to last known good config/commit."
            ),
            "risk": "low" if confidence >= 0.7 and verification["passed"] else "medium",
            "findings": [h.to_dict() for h in self.hypotheses],
            "recommendation": f"[simulated] act on {top.hypothesis_id}: {top.statement}",
            "answer": top.statement,
            "sources": [e["id"] for e in self.evidence],
            "open_questions": [
                h.statement for h in self.hypotheses[1:] if h.confidence >= 0.3
            ],
        }
        return known.get(name, f"[simulated] value for '{name}'")
