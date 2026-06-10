"""`intentflow explain`: translate an ``.iflow`` program into plain English.

The point of the language is that governance is *program text*. This module
renders that text the way a reviewer would read it aloud: what the goal is
trying to do, what evidence it demands, what it may/may not do, what needs a
human, how it checks itself, and what it promises to produce.
"""

from __future__ import annotations

from typing import Any

from intentflow.compiler import (
    extract_actions,
    extract_evidence,
    extract_metadata,
    extract_objective,
    extract_output,
    extract_uncertainty,
    extract_verification,
)
from intentflow.iflow_ast import (
    ActionPolicy,
    EvidencePolicy,
    Goal,
    Program,
)

_ACTION_VERBS = {
    "ask_human": "stop and ask a human",
    "block_action": "refuse to act and stop the run",
    "escalate": "escalate",
    "abort": "abort the run",
    "halt": "halt the run",
    "defer": "defer the decision",
    "retry": "retry",
    "request_more_evidence": "request more evidence",
    "gather_more_evidence": "gather more evidence",
    "run_discriminating_test": "run a discriminating test",
    "present_both_views": "present both views",
}


def _humanize(name: str) -> str:
    return name.replace("_", " ")


def explain_goal(goal: Goal, source_name: str = "<string>") -> dict[str, Any]:
    """A structured plain-English explanation of one goal."""
    objective = extract_objective(goal)
    metadata = extract_metadata(goal, source_name)
    evidence = EvidencePolicy.from_requirements(extract_evidence(goal, source_name))
    actions = ActionPolicy.from_rules(extract_actions(goal, source_name))
    verification = extract_verification(goal)
    uncertainty = extract_uncertainty(goal, source_name)
    output = extract_output(goal, source_name)

    purpose = f"This goal tries to {objective}." if objective else (
        "This goal declares no objective."
    )
    if metadata.description:
        purpose += f" ({metadata.description})"

    evidence_lines: list[str] = []
    for source in evidence.required:
        evidence_lines.append(f"It must gather {_humanize(source)} before reasoning.")
    for source in evidence.optional:
        evidence_lines.append(f"It may also use {_humanize(source)} when available.")
    for source in evidence.preferred:
        evidence_lines.append(f"It prefers {_humanize(source)} when available.")
    for source in evidence.distrusted:
        evidence_lines.append(
            f"It treats {_humanize(source)} as untrusted — never the sole "
            "support for a claim."
        )
    if not evidence_lines:
        evidence_lines.append("It requires no evidence (the analyzer warns about this).")

    allowed_lines = [f"It may {_humanize(a)}." for a in actions.allowed]
    if not allowed_lines:
        allowed_lines.append("It is allowed to take no actions at all.")
    approval_lines = [
        f"It must get human approval before it can {_humanize(a)}."
        for a in actions.approval_required
    ]
    denied_lines = [
        f"It is forbidden to {_humanize(a)}, no matter what the model says."
        for a in actions.denied
    ]

    verify_lines: list[str] = []
    for rule in verification:
        check = rule.check
        if check["kind"] == "threshold_check":
            verify_lines.append(
                f"The result is rejected unless {check['metric']} "
                f"{check['op']} {check['value']} (checked by the runtime, "
                "not the model)."
            )
        elif check["kind"] == "cites_evidence":
            verify_lines.append(
                "The result is rejected unless it cites the evidence that "
                "was actually collected."
            )
        elif check["kind"] == "requires_phrase":
            verify_lines.append(
                f"The result is rejected unless it includes a "
                f"'{check['arg']}' plan."
            )
        else:
            name = check.get("name")
            label = _humanize(name) if name else rule.description
            verify_lines.append(
                f"A judge (or a human) must confirm: {label}. Without a "
                "judge this check is recorded as skipped, never assumed to pass."
            )
    if not verify_lines:
        verify_lines.append("It declares no verification rules (the analyzer warns).")

    uncertainty_lines: list[str] = []
    for rule in uncertainty:
        action_text = _ACTION_VERBS.get(
            rule.action.name, f"take the action '{rule.action.name}'"
        )
        condition = rule.condition
        if condition.kind == "threshold":
            cond_text = (
                f"its {condition.metric} is "
                f"{_OP_WORDS.get(condition.op, condition.op)} {condition.threshold}"
            )
        else:
            cond_text = f"it detects {_humanize(condition.text)}"
        uncertainty_lines.append(f"If {cond_text}, it will {action_text}.")
    if not uncertainty_lines:
        uncertainty_lines.append(
            "It has no uncertainty rules: it will never escalate, no matter "
            "how unsure it is (the analyzer warns)."
        )

    output_lines: list[str] = []
    for field in output.fields:
        optional = " (optional)" if field.optional else ""
        output_lines.append(f"{field.name}: {field.type}{optional}")
    if not output_lines:
        output_lines.append("(no output promised)")

    return {
        "goal": goal.name,
        "purpose": purpose,
        "evidence": evidence_lines,
        "allowed": allowed_lines,
        "needs_approval": approval_lines,
        "forbidden": denied_lines,
        "verification": verify_lines,
        "uncertainty": uncertainty_lines,
        "promises": output_lines,
    }


_OP_WORDS = {
    "<": "below",
    "<=": "at or below",
    ">": "above",
    ">=": "at or above",
    "==": "exactly",
}


def explain_program(program: Program) -> dict[str, Any]:
    return {
        "source": program.source_name,
        "goals": [explain_goal(g, program.source_name) for g in program.goals],
        "pipelines": [
            {
                "name": p.name,
                "explanation": "Runs "
                + " then ".join(s.goal_name for s in p.stages)
                + "; each stage's outputs become evidence for later stages.",
            }
            for p in program.pipelines
        ],
    }


def render_explanation(report: dict[str, Any]) -> str:
    """Render an explanation report as readable text."""
    lines: list[str] = []
    for goal in report["goals"]:
        lines.append(f"goal {goal['goal']}")
        lines.append(f"  {goal['purpose']}")
        sections = (
            ("evidence it requires", goal["evidence"]),
            ("what it may do", goal["allowed"]),
            ("what needs human approval", goal["needs_approval"]),
            ("what it is forbidden to do", goal["forbidden"]),
            ("how it verifies itself", goal["verification"]),
            ("when it stops or asks for help", goal["uncertainty"]),
        )
        for title, entries in sections:
            if not entries:
                continue
            lines.append(f"\n  {title}:")
            for entry in entries:
                lines.append(f"    - {entry}")
        lines.append("\n  what it promises to produce:")
        for entry in goal["promises"]:
            lines.append(f"    - {entry}")
        lines.append("")
    for pipeline in report.get("pipelines", []):
        lines.append(f"pipeline {pipeline['name']}")
        lines.append(f"  {pipeline['explanation']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
