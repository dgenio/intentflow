"""Static analysis for IntentFlow programs.

Lint runs on the cognitive IR, before any model is invoked. This is where a
*language* earns its keep over a config schema: the rules below reason about
the interaction of policies — actions vs verification, threshold ordering,
checkability of rules — not just the shape of fields.

Rules:

* ``IF001`` — a destructive-looking action is allowed without approval
  gating and no verification rule mentions it.
* ``IF002`` — an uncertainty threshold can never trigger (or duplicates an
  earlier rule), so the escalation it promises is unreachable.
* ``IF003`` — a symbolic uncertainty condition has no runtime evaluator; it
  will only ever be recorded, never acted on.
* ``IF004`` — a verification rule is judged (not machine-checkable); it
  will be recorded as skipped, not enforced.
"""

from __future__ import annotations

from dataclasses import dataclass

from intentflow.compiler import (
    DESTRUCTIVE_TOKENS,
    classify_verification,
    extract_actions,
    extract_uncertainty,
    extract_verification,
)
from intentflow.iflow_ast import Goal, Program

#: Symbolic uncertainty conditions the runtime knows how to evaluate.
EVALUABLE_CONDITIONS: tuple[str, ...] = ("competing_hypotheses",)


@dataclass
class Finding:
    rule_id: str
    level: str  # "warning" | "info"
    message: str
    line: int


def _lint_actions(goal: Goal) -> list[Finding]:
    findings: list[Finding] = []
    verify_text = " ".join(r.description.lower() for r in extract_verification(goal))
    for policy in extract_actions(goal):
        if policy.mode != "allow":
            continue
        if not any(token in policy.action.lower() for token in DESTRUCTIVE_TOKENS):
            continue
        if policy.action.lower() in verify_text:
            continue
        findings.append(
            Finding(
                "IF001",
                "warning",
                f"destructive-looking action {policy.action!r} is allowed without "
                "approval gating and no verification rule mentions it; consider "
                f"'require_approval {policy.action}' or a verify rule",
                policy.line,
            )
        )
    return findings


def _lint_uncertainty(goal: Goal) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for rule in extract_uncertainty(goal):
        key = (rule.condition, rule.action)
        if key in seen:
            findings.append(
                Finding(
                    "IF002",
                    "warning",
                    f"duplicate uncertainty rule 'if {rule.condition} {rule.action}'",
                    rule.line,
                )
            )
        seen.add(key)
        if rule.kind == "threshold" and rule.metric == "confidence":
            never = (rule.op == "<" and rule.threshold == 0.0) or (
                rule.op == ">" and rule.threshold == 1.0
            )
            always = (rule.op == ">=" and rule.threshold == 0.0) or (
                rule.op == "<=" and rule.threshold == 1.0
            )
            if never:
                findings.append(
                    Finding(
                        "IF002",
                        "warning",
                        f"threshold rule 'if {rule.condition}' can never trigger; "
                        "the escalation it promises is unreachable",
                        rule.line,
                    )
                )
            elif always:
                findings.append(
                    Finding(
                        "IF002",
                        "warning",
                        f"threshold rule 'if {rule.condition}' always triggers; "
                        "confidence plays no role in this escalation",
                        rule.line,
                    )
                )
        if rule.kind == "symbolic" and not any(
            token in rule.condition for token in EVALUABLE_CONDITIONS
        ):
            findings.append(
                Finding(
                    "IF003",
                    "info",
                    f"symbolic condition {rule.condition!r} has no runtime "
                    "evaluator; it will be recorded but never acted on",
                    rule.line,
                )
            )
    return findings


def _lint_verification(goal: Goal) -> list[Finding]:
    findings: list[Finding] = []
    for rule in extract_verification(goal):
        check = classify_verification(rule.description)
        if check["mode"] == "judged":
            findings.append(
                Finding(
                    "IF004",
                    "info",
                    f"verification rule {rule.description!r} is not "
                    "machine-checkable; it will be recorded as skipped, "
                    "not enforced",
                    rule.line,
                )
            )
    return findings


def lint_goal(goal: Goal) -> list[Finding]:
    findings = _lint_actions(goal) + _lint_uncertainty(goal) + _lint_verification(goal)
    return sorted(findings, key=lambda f: f.line)


def lint_program(program: Program) -> list[Finding]:
    findings: list[Finding] = []
    for goal in program.goals:
        findings.extend(lint_goal(goal))
    return findings
