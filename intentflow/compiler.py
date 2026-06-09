"""Compiler: lowers the syntactic AST into the cognitive IR and emits an
execution plan.

The execution plan is the contract between the language and any runtime
(simulated today, LLM-backed later). It makes agent behavior inspectable
*before* execution: which evidence is mandatory, which actions are governed,
which checks must pass, and when control escalates to a human.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from intentflow import iflow_ast as ir
from intentflow.iflow_ast import (
    ActionPolicy,
    ContextPolicy,
    EvidenceRequirement,
    Goal,
    OutputSpec,
    Program,
    UncertaintyRule,
    VerificationRule,
)

PLAN_VERSION = "0.2.0"

_THRESHOLD_RE = re.compile(
    r"^if\s+([a-z_]+)\s*(<=|>=|<|>|==)\s*([0-9]*\.?[0-9]+)\s+(\S+)$"
)
_SYMBOLIC_RE = re.compile(r"^if\s+(.+?)\s+(\S+)$")
_MAX_TOKENS_RE = re.compile(r"^max_tokens\s+(\d+)$")


class CompileError(Exception):
    """A semantic error found while lowering the AST."""

    def __init__(self, message: str, line: int, source_name: str = "<string>") -> None:
        self.message = message
        self.line = line
        self.source_name = source_name
        super().__init__(f"{source_name}:{line}: {message}")


# ---------------------------------------------------------------------------
# Lowering: statements -> cognitive IR
# ---------------------------------------------------------------------------


def extract_objective(goal: Goal) -> str:
    """Join the objective lines into one normalized sentence."""
    lines = [s.text for s in goal.statements("objective")]
    return " ".join(lines).strip()


def extract_evidence(goal: Goal, source_name: str = "<string>") -> list[EvidenceRequirement]:
    requirements: list[EvidenceRequirement] = []
    for stmt in goal.statements("evidence"):
        parts = stmt.text.split(None, 1)
        verb = parts[0]
        if verb not in ir.EVIDENCE_STANCES:
            raise CompileError(
                f"unknown evidence stance {verb!r}; expected one of: "
                + ", ".join(ir.EVIDENCE_STANCES),
                stmt.line,
                source_name,
            )
        if len(parts) < 2:
            raise CompileError(
                f"evidence statement {stmt.text!r} is missing a source",
                stmt.line,
                source_name,
            )
        requirements.append(
            EvidenceRequirement(source=parts[1].strip(), stance=verb, line=stmt.line)
        )
    return requirements


def extract_actions(goal: Goal, source_name: str = "<string>") -> list[ActionPolicy]:
    policies: list[ActionPolicy] = []
    for stmt in goal.statements("actions"):
        parts = stmt.text.split(None, 1)
        verb = parts[0]
        if verb not in ir.ACTION_MODES:
            raise CompileError(
                f"unknown action mode {verb!r}; expected one of: "
                + ", ".join(ir.ACTION_MODES),
                stmt.line,
                source_name,
            )
        if len(parts) < 2:
            raise CompileError(
                f"action statement {stmt.text!r} is missing an action name",
                stmt.line,
                source_name,
            )
        policies.append(ActionPolicy(action=parts[1].strip(), mode=verb, line=stmt.line))
    return policies


def extract_verification(goal: Goal) -> list[VerificationRule]:
    return [
        VerificationRule(rule_id=f"V{i}", description=stmt.text, line=stmt.line)
        for i, stmt in enumerate(goal.statements("verify"), start=1)
    ]


def classify_verification(description: str) -> dict[str, str]:
    """Map a verification rule to a typed, executable check.

    ``machine`` checks are evaluated by the runtime against structured state;
    ``judged`` checks need an LLM judge and are recorded, never silently
    assumed to pass. The distinction is part of the plan because the two have
    very different trust properties.
    """
    text = description.lower()
    if "cite" in text:
        return {"kind": "cites_evidence", "mode": "machine"}
    if "rollback" in text:
        return {"kind": "requires_phrase", "arg": "rollback", "mode": "machine"}
    return {"kind": "judged", "mode": "judged"}


def extract_uncertainty(goal: Goal, source_name: str = "<string>") -> list[UncertaintyRule]:
    rules: list[UncertaintyRule] = []
    for stmt in goal.statements("uncertainty"):
        match = _THRESHOLD_RE.match(stmt.text)
        if match:
            metric, op, value, action = match.groups()
            rules.append(
                UncertaintyRule(
                    kind="threshold",
                    condition=f"{metric} {op} {value}",
                    action=action,
                    line=stmt.line,
                    metric=metric,
                    op=op,
                    threshold=float(value),
                )
            )
            continue
        match = _SYMBOLIC_RE.match(stmt.text)
        if match:
            condition, action = match.groups()
            rules.append(
                UncertaintyRule(
                    kind="symbolic",
                    condition=condition.strip(),
                    action=action,
                    line=stmt.line,
                )
            )
            continue
        raise CompileError(
            f"malformed uncertainty rule {stmt.text!r}; expected "
            "'if <metric> <op> <number> <action>' or 'if <condition> <action>'",
            stmt.line,
            source_name,
        )
    return rules


def extract_context(goal: Goal, source_name: str = "<string>") -> ContextPolicy:
    policy = ContextPolicy()
    for stmt in goal.statements("context"):
        match = _MAX_TOKENS_RE.match(stmt.text)
        if match:
            policy.max_tokens = int(match.group(1))
            continue
        parts = stmt.text.split(None, 1)
        verb = parts[0]
        if verb == "prefer" and len(parts) == 2:
            policy.prefer.append(parts[1].strip())
        elif verb == "preserve" and len(parts) == 2:
            policy.preserve.append(parts[1].strip())
        else:
            raise CompileError(
                f"unknown context directive {stmt.text!r}; expected "
                "'max_tokens N', 'prefer X' or 'preserve X'",
                stmt.line,
                source_name,
            )
    return policy


def extract_output(goal: Goal) -> OutputSpec:
    return OutputSpec(fields=[s.text for s in goal.statements("output")])


def extract_model_directives(goal: Goal) -> list[str]:
    return [s.text for s in goal.statements("model")]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@dataclass
class Diagnostic:
    level: str  # "error" | "warning"
    message: str
    line: int


def validate_goal(goal: Goal, source_name: str = "<string>") -> list[Diagnostic]:
    """Semantic checks beyond syntax. Returns diagnostics; errors make the
    goal uncompilable."""
    diagnostics: list[Diagnostic] = []

    if not extract_objective(goal):
        diagnostics.append(
            Diagnostic("error", f"goal {goal.name!r} has no objective", goal.line)
        )

    try:
        actions = extract_actions(goal, source_name)
        evidence = extract_evidence(goal, source_name)
        uncertainty = extract_uncertainty(goal, source_name)
        extract_context(goal, source_name)
    except CompileError as exc:
        diagnostics.append(Diagnostic("error", exc.message, exc.line))
        return diagnostics

    seen_modes: dict[str, ActionPolicy] = {}
    for policy in actions:
        previous = seen_modes.get(policy.action)
        if previous is not None and previous.mode != policy.mode:
            diagnostics.append(
                Diagnostic(
                    "error",
                    f"conflicting policies for action {policy.action!r}: "
                    f"{previous.mode!r} (line {previous.line}) vs {policy.mode!r}",
                    policy.line,
                )
            )
        seen_modes[policy.action] = policy

    for rule in uncertainty:
        if (
            rule.kind == "threshold"
            and rule.metric == "confidence"
            and rule.threshold is not None
            and not 0.0 <= rule.threshold <= 1.0
        ):
            diagnostics.append(
                Diagnostic(
                    "error",
                    f"confidence threshold {rule.threshold} out of range [0, 1]",
                    rule.line,
                )
            )

    if not extract_output(goal).fields:
        diagnostics.append(
            Diagnostic(
                "warning",
                f"goal {goal.name!r} declares no output fields",
                goal.line,
            )
        )
    if not evidence:
        diagnostics.append(
            Diagnostic(
                "warning",
                f"goal {goal.name!r} declares no evidence requirements; "
                "results will be unsupported speculation",
                goal.line,
            )
        )
    if not goal.statements("verify"):
        diagnostics.append(
            Diagnostic(
                "warning",
                f"goal {goal.name!r} declares no verification rules",
                goal.line,
            )
        )
    return diagnostics


def validate_program(program: Program) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for goal in program.goals:
        diagnostics.extend(validate_goal(goal, program.source_name))
    return diagnostics


# ---------------------------------------------------------------------------
# Execution plan
# ---------------------------------------------------------------------------


@dataclass
class ExecutionPlan:
    """Everything a runtime needs to execute a goal in a governed way."""

    goal: str
    objective: str
    context_policy: dict[str, Any]
    evidence: dict[str, list[str]]
    actions: dict[str, list[str]]
    model_directives: list[str]
    verification: list[dict[str, Any]]
    uncertainty_policy: list[dict[str, Any]]
    calibration: dict[str, Any]
    outputs: list[str]
    trace: dict[str, Any]
    prompt_plan: list[dict[str, str]]
    plan_version: str = PLAN_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _build_prompt_plan(
    goal_name: str,
    objective: str,
    evidence: list[EvidenceRequirement],
    actions: list[ActionPolicy],
    model_directives: list[str],
    verification: list[VerificationRule],
    outputs: OutputSpec,
) -> list[dict[str, str]]:
    """A staged prompt plan: each phase becomes one governed LLM interaction
    rather than a single opaque mega-prompt."""
    required = [e.source for e in evidence if e.stance == "require"]
    distrusted = [e.source for e in evidence if e.stance == "distrust"]
    allowed = [a.action for a in actions if a.mode == "allow"]
    gated = [a.action for a in actions if a.mode == "require_approval"]
    denied = [a.action for a in actions if a.mode == "deny"]

    frame = (
        f"You are executing the IntentFlow goal '{goal_name}'. "
        f"Objective: {objective} "
        "Separate observation from inference, attach a confidence in [0, 1] "
        "to every conclusion, and never take an action outside the allowed list."
    )
    if allowed:
        frame += f" Allowed actions: {', '.join(allowed)}."
    if gated:
        frame += f" Actions requiring human approval before use: {', '.join(gated)}."
    if denied:
        frame += f" Forbidden actions: {', '.join(denied)}."

    evidence_instruction = (
        "Collect all required evidence before reasoning: "
        + (", ".join(required) if required else "(none declared)")
        + ". Label each evidence item with a stable id (E1, E2, ...)."
    )
    if distrusted:
        evidence_instruction += (
            " Treat the following as untrusted and never cite them as sole "
            f"support: {', '.join(distrusted)}."
        )

    model_instruction = (
        "Reason over the collected evidence only. "
        + " ".join(d.capitalize() + "." for d in model_directives)
        + " Cite evidence ids for every hypothesis."
    ).strip()

    verify_instruction = (
        "Before producing output, check the result against every rule and "
        "report pass/fail per rule: "
        + ("; ".join(r.description for r in verification) if verification else "(none)")
    )

    output_instruction = (
        "Produce a JSON object with exactly these fields: "
        + (", ".join(outputs.fields) if outputs.fields else "(unspecified)")
        + ". Do not add commentary outside the JSON object."
    )

    return [
        {"phase": "frame", "role": "system", "instruction": frame},
        {"phase": "evidence", "role": "user", "instruction": evidence_instruction},
        {"phase": "model", "role": "user", "instruction": model_instruction},
        {"phase": "verify", "role": "user", "instruction": verify_instruction},
        {"phase": "output", "role": "user", "instruction": output_instruction},
    ]


def compile_goal(goal: Goal, source_name: str = "<string>") -> ExecutionPlan:
    """Lower a goal into an :class:`ExecutionPlan`.

    Raises :class:`CompileError` if the goal has semantic errors.
    """
    errors = [d for d in validate_goal(goal, source_name) if d.level == "error"]
    if errors:
        first = errors[0]
        raise CompileError(first.message, first.line, source_name)

    objective = extract_objective(goal)
    evidence = extract_evidence(goal, source_name)
    actions = extract_actions(goal, source_name)
    context = extract_context(goal, source_name)
    verification = extract_verification(goal)
    uncertainty = extract_uncertainty(goal, source_name)
    outputs = extract_output(goal)
    model_directives = extract_model_directives(goal)

    return ExecutionPlan(
        goal=goal.name,
        objective=objective,
        context_policy={
            "max_tokens": context.max_tokens,
            "prefer": context.prefer,
            "preserve": context.preserve,
        },
        evidence={
            "required": [e.source for e in evidence if e.stance == "require"],
            "preferred": [e.source for e in evidence if e.stance == "prefer"],
            "distrusted": [e.source for e in evidence if e.stance == "distrust"],
        },
        actions={
            "allowed": [a.action for a in actions if a.mode == "allow"],
            "approval_required": [
                a.action for a in actions if a.mode == "require_approval"
            ],
            "denied": [a.action for a in actions if a.mode == "deny"],
        },
        model_directives=model_directives,
        verification=[
            {
                "id": r.rule_id,
                "rule": r.description,
                "line": r.line,
                "check": classify_verification(r.description),
            }
            for r in verification
        ],
        # Raw model self-reported confidence is miscalibrated; uncertainty
        # rules fire on calibrated values. Shrinkage toward 0.5 is a stand-in
        # until a learned calibration map exists.
        calibration={"method": "shrinkage", "midpoint": 0.5, "factor": 0.8},
        uncertainty_policy=[
            {
                "kind": r.kind,
                "condition": r.condition,
                "action": r.action,
                "metric": r.metric,
                "op": r.op,
                "threshold": r.threshold,
            }
            for r in uncertainty
        ],
        outputs=list(outputs.fields),
        trace={"enabled": True, "level": "full", "record_prompts": True},
        prompt_plan=_build_prompt_plan(
            goal.name, objective, evidence, actions, model_directives,
            verification, outputs,
        ),
    )


def _check_pipeline(pipeline, program: Program, source_name: str) -> None:
    """Statically verify a pipeline's evidence chain: every dotted evidence
    source ``GoalName.field`` must be produced by an *earlier* stage's
    declared outputs."""
    produced: dict[str, set[str]] = {}
    for stage in pipeline.stages:
        goal = program.goal(stage.goal_name)
        if goal is None:
            raise CompileError(
                f"pipeline {pipeline.name!r} references unknown goal "
                f"{stage.goal_name!r}",
                stage.line,
                source_name,
            )
        for req in extract_evidence(goal, source_name):
            if req.stance != "require" or "." not in req.source:
                continue
            origin, _, field_name = req.source.partition(".")
            if origin not in produced and program.goal(origin) is not None:
                raise CompileError(
                    f"stage {stage.goal_name!r} requires {req.source!r} but goal "
                    f"{origin!r} does not run before it in pipeline "
                    f"{pipeline.name!r}",
                    req.line,
                    source_name,
                )
            if origin in produced and field_name not in produced[origin]:
                raise CompileError(
                    f"stage {stage.goal_name!r} requires {req.source!r} but goal "
                    f"{origin!r} does not declare output {field_name!r}",
                    req.line,
                    source_name,
                )
        produced[stage.goal_name] = set(extract_output(goal).fields)


def compile_program(program: Program) -> dict[str, Any]:
    """Compile every goal and pipeline in a program into a JSON document."""
    for pipeline in program.pipelines:
        _check_pipeline(pipeline, program, program.source_name)
    return {
        "intentflow_version": PLAN_VERSION,
        "source": program.source_name,
        "plans": [compile_goal(g, program.source_name).to_dict() for g in program.goals],
        "pipelines": [
            {"name": p.name, "stages": [s.goal_name for s in p.stages]}
            for p in program.pipelines
        ],
    }
