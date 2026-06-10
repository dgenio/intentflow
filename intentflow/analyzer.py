"""Static analyzer: a real diagnostics phase between parsing and compilation.

The analyzer inspects a parsed program and produces coded diagnostics
(``IFLOW001``..) with a severity, a message, a source position, and — where
possible — a suggestion. ``intentflow validate`` is a thin wrapper around
this module, and the compiler refuses to emit a plan for a goal with
analyzer ERRORs.

Severities:

* ``error``   — the goal cannot compile / the program is contradictory.
* ``warning`` — the goal compiles but is unsafe or underspecified.
* ``info``    — advisory; something to know, not necessarily fix.

Diagnostic codes:

========== ======== =====================================================
IFLOW001   error    goal has no objective
IFLOW002   warning  goal declares no output schema
IFLOW003   warning  confidence is used in verify/uncertainty but is not
                    an output field
IFLOW004   error    duplicate output field
IFLOW005   error    invalid output type
IFLOW006   error    conflicting action policies for the same action
IFLOW007   warning  verification check references an unknown metric/output
IFLOW008   warning  uncertainty condition references an unknown signal
IFLOW009   warning  only one evidence requirement (thin evidential basis)
IFLOW010   warning  side-effect action allowed without approval gating
IFLOW011   warning  overly broad action (e.g. execute_code) allowed
                    without approval
IFLOW012   warning  no verification rules
IFLOW013   warning  no uncertainty rules
IFLOW014   warning  no evidence requirements
IFLOW015   warning  max_tokens implausibly low or high
IFLOW016   error    duplicate goal names in one program
IFLOW017   info     untyped output field (defaults to string)
IFLOW018   warning  uncertainty action is neither a primitive nor an
                    allowed/approval-gated action
IFLOW019   error    confidence threshold out of [0, 1]
IFLOW020   error    malformed statement (lowering failed)
IFLOW021   info     verification rule is judged, not machine-checkable
IFLOW022   warning  duplicate or unreachable uncertainty rule
========== ======== =====================================================
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from intentflow.actions import default_registry
from intentflow.compiler import (
    CompileError,
    extract_actions,
    extract_context,
    extract_evidence,
    extract_metadata,
    extract_objective,
    extract_output,
    extract_uncertainty,
    extract_verification,
)
from intentflow.iflow_ast import (
    Goal,
    KNOWN_SIGNALS,
    Program,
    UNCERTAINTY_PRIMITIVES,
)

#: Sane bounds for a context token budget.
MIN_MAX_TOKENS = 256
MAX_MAX_TOKENS = 200_000

SEVERITIES: tuple[str, ...] = ("error", "warning", "info")


@dataclass
class Diagnostic:
    """One analyzer finding."""

    code: str
    severity: str  # "error" | "warning" | "info"
    message: str
    line: int
    column: int | None = None
    suggestion: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def render(self, source_name: str) -> str:
        position = f"{source_name}:{self.line}"
        if self.column is not None:
            position += f":{self.column}"
        text = f"{position}: {self.severity}[{self.code}]: {self.message}"
        if self.suggestion:
            text += f"\n    suggestion: {self.suggestion}"
        return text


def _lowering_error(exc: CompileError) -> Diagnostic:
    return Diagnostic("IFLOW020", "error", exc.message, exc.line)


def _analyze_output(goal: Goal, source_name: str) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    statements = goal.statements("output")
    if not statements:
        diagnostics.append(
            Diagnostic(
                "IFLOW002",
                "warning",
                f"goal {goal.name!r} declares no output schema",
                goal.line,
                suggestion="add an 'output:' section with typed fields, "
                "e.g. 'summary: string'",
            )
        )
        return diagnostics
    try:
        schema = extract_output(goal, source_name)
    except CompileError as exc:
        return [Diagnostic("IFLOW005", "error", exc.message, exc.line)]
    seen: dict[str, int] = {}
    for field, stmt in zip(schema.fields, statements):
        if field.name in seen:
            diagnostics.append(
                Diagnostic(
                    "IFLOW004",
                    "error",
                    f"duplicate output field {field.name!r} "
                    f"(first declared on line {seen[field.name]})",
                    field.line,
                )
            )
        seen.setdefault(field.name, field.line)
        if ":" not in stmt.text:
            diagnostics.append(
                Diagnostic(
                    "IFLOW017",
                    "info",
                    f"output field {field.name!r} has no type; defaulting to string",
                    field.line,
                    suggestion=f"declare it explicitly: '{field.name}: string'",
                )
            )
    return diagnostics


def _analyze_actions(goal: Goal, source_name: str) -> list[Diagnostic]:
    try:
        rules = extract_actions(goal, source_name)
    except CompileError as exc:
        return [_lowering_error(exc)]
    diagnostics: list[Diagnostic] = []
    registry = default_registry()
    seen: dict[str, Any] = {}
    for rule in rules:
        previous = seen.get(rule.action)
        if previous is not None and previous.mode != rule.mode:
            diagnostics.append(
                Diagnostic(
                    "IFLOW006",
                    "error",
                    f"conflicting policies for action {rule.action!r}: "
                    f"{previous.mode!r} (line {previous.line}) vs {rule.mode!r}",
                    rule.line,
                    suggestion="keep exactly one policy per action",
                )
            )
        seen[rule.action] = rule
    for rule in rules:
        if rule.mode != "allow":
            continue
        spec = registry.spec_for(rule.action)
        if registry.is_overly_broad(rule.action):
            diagnostics.append(
                Diagnostic(
                    "IFLOW011",
                    "warning",
                    f"overly broad action {rule.action!r} is allowed without "
                    "approval; it can do almost anything",
                    rule.line,
                    suggestion=f"use 'require_approval {rule.action}' or a "
                    "narrower action name",
                )
            )
        elif spec.side_effect:
            diagnostics.append(
                Diagnostic(
                    "IFLOW010",
                    "warning",
                    f"action {rule.action!r} has side effects but is allowed "
                    "without approval gating",
                    rule.line,
                    suggestion=f"use 'require_approval {rule.action}'",
                )
            )
    return diagnostics


def _analyze_evidence(goal: Goal, source_name: str) -> list[Diagnostic]:
    try:
        requirements = extract_evidence(goal, source_name)
    except CompileError as exc:
        return [_lowering_error(exc)]
    required = [r for r in requirements if r.stance == "require"]
    if not required:
        return [
            Diagnostic(
                "IFLOW014",
                "warning",
                f"goal {goal.name!r} requires no evidence; results will be "
                "unsupported speculation",
                goal.line,
                suggestion="add 'require <source>' lines to the evidence section",
            )
        ]
    if len(required) == 1:
        return [
            Diagnostic(
                "IFLOW009",
                "warning",
                f"goal {goal.name!r} requires only one evidence source "
                f"({required[0].source!r}); conclusions will rest on a single basis",
                required[0].line,
                suggestion="require at least one corroborating source",
            )
        ]
    return []


def _analyze_verification(
    goal: Goal, source_name: str, output_fields: set[str]
) -> list[Diagnostic]:
    rules = extract_verification(goal)
    if not rules:
        return [
            Diagnostic(
                "IFLOW012",
                "warning",
                f"goal {goal.name!r} declares no verification rules",
                goal.line,
                suggestion="add a 'verify:' section (e.g. 'require cites_evidence')",
            )
        ]
    diagnostics: list[Diagnostic] = []
    for rule in rules:
        check = rule.check
        if check["kind"] == "threshold_check":
            metric = check["metric"]
            if metric != "confidence" and metric not in output_fields:
                diagnostics.append(
                    Diagnostic(
                        "IFLOW007",
                        "warning",
                        f"verification check references {metric!r}, which is "
                        "neither 'confidence' nor a declared output field",
                        rule.line,
                        suggestion=f"declare '{metric}: number' in the output "
                        "section or check 'confidence'",
                    )
                )
            if metric == "confidence" and not 0.0 <= check["value"] <= 1.0:
                diagnostics.append(
                    Diagnostic(
                        "IFLOW019",
                        "error",
                        f"confidence threshold {check['value']} out of range [0, 1]",
                        rule.line,
                    )
                )
        elif check["mode"] == "judged":
            diagnostics.append(
                Diagnostic(
                    "IFLOW021",
                    "info",
                    f"verification rule {rule.description!r} is not "
                    "machine-checkable; it needs an LLM judge (--judge) or is "
                    "recorded as skipped",
                    rule.line,
                )
            )
    return diagnostics


def _analyze_uncertainty(
    goal: Goal, source_name: str, allowed_or_gated: set[str]
) -> list[Diagnostic]:
    try:
        rules = extract_uncertainty(goal, source_name)
    except CompileError as exc:
        return [_lowering_error(exc)]
    if not rules:
        return [
            Diagnostic(
                "IFLOW013",
                "warning",
                f"goal {goal.name!r} declares no uncertainty rules; it will "
                "never escalate, no matter how unsure the result is",
                goal.line,
                suggestion="add e.g. 'if confidence < 0.7 ask_human'",
            )
        ]
    diagnostics: list[Diagnostic] = []
    seen: set[tuple[str, str]] = set()
    for rule in rules:
        condition, action = rule.condition, rule.action
        key = (condition.text, action.name)
        if key in seen:
            diagnostics.append(
                Diagnostic(
                    "IFLOW022",
                    "warning",
                    f"duplicate uncertainty rule 'if {condition.text} {action.name}'",
                    rule.line,
                )
            )
        seen.add(key)
        if condition.kind == "threshold" and condition.metric == "confidence":
            threshold = condition.threshold or 0.0
            if not 0.0 <= threshold <= 1.0:
                diagnostics.append(
                    Diagnostic(
                        "IFLOW019",
                        "error",
                        f"confidence threshold {threshold} out of range [0, 1]",
                        rule.line,
                    )
                )
            never = (condition.op == "<" and threshold == 0.0) or (
                condition.op == ">" and threshold == 1.0
            )
            always = (condition.op == ">=" and threshold == 0.0) or (
                condition.op == "<=" and threshold == 1.0
            )
            if never:
                diagnostics.append(
                    Diagnostic(
                        "IFLOW022",
                        "warning",
                        f"threshold rule 'if {condition.text}' can never trigger; "
                        "the escalation it promises is unreachable",
                        rule.line,
                    )
                )
            elif always:
                diagnostics.append(
                    Diagnostic(
                        "IFLOW022",
                        "warning",
                        f"threshold rule 'if {condition.text}' always triggers; "
                        "confidence plays no role in this escalation",
                        rule.line,
                    )
                )
        if condition.kind == "signal" and condition.signal not in KNOWN_SIGNALS:
            diagnostics.append(
                Diagnostic(
                    "IFLOW008",
                    "warning",
                    f"uncertainty condition {condition.text!r} references an "
                    "unknown signal; the runtime can only record it, never "
                    "evaluate it",
                    rule.line,
                    suggestion="known signals: " + ", ".join(KNOWN_SIGNALS),
                )
            )
        if action.name not in UNCERTAINTY_PRIMITIVES and action.name not in allowed_or_gated:
            diagnostics.append(
                Diagnostic(
                    "IFLOW018",
                    "warning",
                    f"uncertainty action {action.name!r} is neither a built-in "
                    "escalation primitive nor an allowed/approval-gated action",
                    rule.line,
                    suggestion="built-in primitives: "
                    + ", ".join(UNCERTAINTY_PRIMITIVES),
                )
            )
    return diagnostics


def _analyze_confidence_usage(goal: Goal, source_name: str) -> list[Diagnostic]:
    """IFLOW003: confidence is checked but never promised as an output."""
    try:
        output_names = set(extract_output(goal, source_name).field_names())
        verification = extract_verification(goal)
        uncertainty = extract_uncertainty(goal, source_name)
    except CompileError:
        return []  # reported elsewhere
    uses_confidence = any(
        r.check.get("kind") == "threshold_check" and r.check.get("metric") == "confidence"
        for r in verification
    ) or any(
        r.condition.kind == "threshold" and r.condition.metric == "confidence"
        for r in uncertainty
    )
    if uses_confidence and "confidence" not in output_names and output_names:
        line = goal.sections["output"].line if "output" in goal.sections else goal.line
        return [
            Diagnostic(
                "IFLOW003",
                "warning",
                f"goal {goal.name!r} gates on confidence but does not declare "
                "'confidence' as an output field",
                line,
                suggestion="add 'confidence: number' to the output section",
            )
        ]
    return []


def _analyze_context(goal: Goal, source_name: str) -> list[Diagnostic]:
    try:
        policy = extract_context(goal, source_name)
    except CompileError as exc:
        return [_lowering_error(exc)]
    if policy.max_tokens is None:
        return []
    if policy.max_tokens < MIN_MAX_TOKENS:
        line = goal.sections["context"].line
        return [
            Diagnostic(
                "IFLOW015",
                "warning",
                f"max_tokens {policy.max_tokens} is implausibly low "
                f"(< {MIN_MAX_TOKENS}); the goal cannot fit its own evidence",
                line,
            )
        ]
    if policy.max_tokens > MAX_MAX_TOKENS:
        line = goal.sections["context"].line
        return [
            Diagnostic(
                "IFLOW015",
                "warning",
                f"max_tokens {policy.max_tokens} is implausibly high "
                f"(> {MAX_MAX_TOKENS})",
                line,
            )
        ]
    return []


def analyze_goal(goal: Goal, source_name: str = "<string>") -> list[Diagnostic]:
    """Run every analyzer check against one goal."""
    diagnostics: list[Diagnostic] = []

    if not extract_objective(goal):
        diagnostics.append(
            Diagnostic(
                "IFLOW001",
                "error",
                f"goal {goal.name!r} has no objective",
                goal.line,
                suggestion="add an 'objective:' section stating what the goal "
                "is trying to achieve",
            )
        )

    try:
        extract_metadata(goal, source_name)
    except CompileError as exc:
        diagnostics.append(_lowering_error(exc))

    diagnostics.extend(_analyze_output(goal, source_name))
    diagnostics.extend(_analyze_actions(goal, source_name))
    diagnostics.extend(_analyze_evidence(goal, source_name))
    diagnostics.extend(_analyze_context(goal, source_name))

    try:
        output_fields = set(extract_output(goal, source_name).field_names())
    except CompileError:
        output_fields = set()
    diagnostics.extend(_analyze_verification(goal, source_name, output_fields))

    try:
        rules = extract_actions(goal, source_name)
        allowed_or_gated = {
            r.action for r in rules if r.mode in ("allow", "require_approval")
        }
    except CompileError:
        allowed_or_gated = set()
    diagnostics.extend(_analyze_uncertainty(goal, source_name, allowed_or_gated))
    diagnostics.extend(_analyze_confidence_usage(goal, source_name))

    return sorted(diagnostics, key=lambda d: (d.line, d.code))


def analyze_program(program: Program) -> list[Diagnostic]:
    """Run every analyzer check against a whole program."""
    diagnostics: list[Diagnostic] = []
    seen: dict[str, int] = {}
    for goal in program.goals:
        if goal.name in seen:
            diagnostics.append(
                Diagnostic(
                    "IFLOW016",
                    "error",
                    f"duplicate goal name {goal.name!r} "
                    f"(first declared on line {seen[goal.name]})",
                    goal.line,
                    suggestion="rename one of the goals",
                )
            )
        seen.setdefault(goal.name, goal.line)
    for goal in program.goals:
        diagnostics.extend(analyze_goal(goal, program.source_name))
    return diagnostics


def errors_in(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    return [d for d in diagnostics if d.severity == "error"]


def warnings_in(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    return [d for d in diagnostics if d.severity == "warning"]
