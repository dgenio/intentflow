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

PLAN_VERSION = "0.3.0"

_THRESHOLD_RE = re.compile(
    r"^if\s+([a-z_]+)\s*(<=|>=|<|>|==)\s*([0-9]*\.?[0-9]+)\s+(\S+)$"
)
_SYMBOLIC_RE = re.compile(r"^if\s+(.+?)\s+(\S+)$")
_MAX_TOKENS_RE = re.compile(r"^max_tokens\s+(\d+)$")
#: ``check <metric> <op> <number>`` — a machine-checkable verification rule
#: evaluated by the runtime against structured state (e.g. confidence).
_CHECK_RE = re.compile(r"^check\s+([a-z_]+)\s*(<=|>=|<|>|==)\s*([0-9]*\.?[0-9]+)$")

#: Verbs that suggest an action mutates the outside world (shared with the
#: linter and the compiler's risk profiler).
DESTRUCTIVE_TOKENS: tuple[str, ...] = (
    "deploy",
    "delete",
    "drop",
    "push",
    "write",
    "merge",
    "force",
    "shutdown",
    "restart",
)

#: Built-in uncertainty control-flow actions the language understands as
#: escalation primitives (as opposed to governed tool invocations).
UNCERTAINTY_PRIMITIVES: tuple[str, ...] = (
    "ask_human",
    "escalate",
    "abort",
    "halt",
    "defer",
    "retry",
    "run_discriminating_test",
    "present_both_views",
    "request_more_evidence",
    "gather_more_evidence",
)


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
    text = description.lower().strip()
    check_match = _CHECK_RE.match(text)
    if check_match:
        metric, op, value = check_match.groups()
        return {
            "kind": "threshold_check",
            "metric": metric,
            "op": op,
            "value": float(value),
            "mode": "machine",
        }
    if "cit" in text:  # cite / citation / citations
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

    allowed_or_gated = {
        p.action for p in actions if p.mode in ("allow", "require_approval")
    }
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
        # An uncertainty action is either a known escalation primitive or a
        # governed tool the goal allows. Anything else is most likely a typo
        # or an action the author forgot to declare.
        if (
            rule.action not in UNCERTAINTY_PRIMITIVES
            and rule.action not in allowed_or_gated
        ):
            diagnostics.append(
                Diagnostic(
                    "warning",
                    f"uncertainty action {rule.action!r} is neither a built-in "
                    "escalation primitive nor an allowed/approval-gated action; "
                    "it will be recorded but cannot be executed",
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


def inspect_goal(goal: Goal, source_name: str = "<string>") -> dict[str, Any]:
    """A structured, at-a-glance view of a goal for ``intentflow inspect``:
    sections present, action governance, required evidence, output fields,
    and any validation warnings/errors — without compiling a full plan."""
    try:
        actions = extract_actions(goal, source_name)
        evidence = extract_evidence(goal, source_name)
    except CompileError:
        actions, evidence = [], []
    diagnostics = validate_goal(goal, source_name)
    return {
        "goal": goal.name,
        "objective": extract_objective(goal),
        "sections": list(goal.sections),
        "allowed_actions": [a.action for a in actions if a.mode == "allow"],
        "approval_gated_actions": [
            a.action for a in actions if a.mode == "require_approval"
        ],
        "denied_actions": [a.action for a in actions if a.mode == "deny"],
        "required_evidence": [e.source for e in evidence if e.stance == "require"],
        "distrusted_evidence": [e.source for e in evidence if e.stance == "distrust"],
        "output_fields": extract_output(goal).fields,
        "diagnostics": [
            {"level": d.level, "message": d.message, "line": d.line}
            for d in diagnostics
        ],
    }


def inspect_program(program: Program) -> dict[str, Any]:
    """Inspect every goal in a program plus its pipelines."""
    return {
        "source": program.source_name,
        "goals": [inspect_goal(g, program.source_name) for g in program.goals],
        "pipelines": [
            {"name": p.name, "stages": [s.goal_name for s in p.stages]}
            for p in program.pipelines
        ],
    }


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
    risk_profile: dict[str, Any]
    trace_policy: dict[str, Any]
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
    uncertainty: list[UncertaintyRule],
    outputs: OutputSpec,
) -> list[dict[str, str]]:
    """A staged prompt plan: one governed block per concern, instead of a
    single opaque mega-prompt.

    Each block is a distinct, inspectable message so that *what the model is
    told about evidence, allowed actions, denied actions, verification,
    uncertainty handling, and the required output format* is visible (and
    diffable) before any model runs. This is the difference between compiling
    intent into a controlled interaction and merely concatenating a prompt.
    """
    required = [e.source for e in evidence if e.stance == "require"]
    preferred = [e.source for e in evidence if e.stance == "prefer"]
    distrusted = [e.source for e in evidence if e.stance == "distrust"]
    allowed = [a.action for a in actions if a.mode == "allow"]
    gated = [a.action for a in actions if a.mode == "require_approval"]
    denied = [a.action for a in actions if a.mode == "deny"]

    system = (
        f"You are executing the IntentFlow goal '{goal_name}'. You are a "
        "governed reasoning process: separate observation from inference, "
        "attach a confidence in [0, 1] to every conclusion, cite evidence ids "
        "for every claim, and never take an action outside the allowed list."
    )
    if model_directives:
        system += " Reasoning discipline: " + "; ".join(model_directives) + "."

    objective_block = f"Objective: {objective}"

    evidence_block = (
        "Required evidence (collect before reasoning, label each item E1, E2, ...): "
        + (", ".join(required) if required else "(none declared)")
    )
    if preferred:
        evidence_block += f". Prefer when available: {', '.join(preferred)}"
    if distrusted:
        evidence_block += (
            f". Treat as untrusted, never cite as sole support: {', '.join(distrusted)}"
        )

    allowed_block = (
        "Allowed actions (you may call these): "
        + (", ".join(allowed) if allowed else "(none)")
    )
    if gated:
        allowed_block += (
            f". Approval-gated (blocked until a human approves): {', '.join(gated)}"
        )

    denied_block = (
        "Forbidden actions (never call these): "
        + (", ".join(denied) if denied else "(none)")
    )

    verify_block = (
        "Before producing output, check the result against every rule and "
        "report pass/fail per rule: "
        + ("; ".join(r.description for r in verification) if verification else "(none)")
    )

    uncertainty_block = (
        "Uncertainty handling — when a condition holds, take the named action: "
        + (
            "; ".join(f"if {r.condition} -> {r.action}" for r in uncertainty)
            if uncertainty
            else "(none)"
        )
    )

    output_block = (
        "Produce a JSON object with exactly these fields: "
        + (", ".join(outputs.fields) if outputs.fields else "(unspecified)")
        + ". Do not add commentary outside the JSON object."
    )

    return [
        {"phase": "system", "role": "system", "instruction": system},
        {"phase": "objective", "role": "user", "instruction": objective_block},
        {"phase": "evidence", "role": "user", "instruction": evidence_block},
        {"phase": "actions_allowed", "role": "user", "instruction": allowed_block},
        {"phase": "actions_denied", "role": "user", "instruction": denied_block},
        {"phase": "verify", "role": "user", "instruction": verify_block},
        {"phase": "uncertainty", "role": "user", "instruction": uncertainty_block},
        {"phase": "output", "role": "user", "instruction": output_block},
    ]


def _build_risk_profile(
    allowed: list[str],
    gated: list[str],
    denied: list[str],
    verification: list[VerificationRule],
) -> dict[str, Any]:
    """Summarize the goal's risk posture from its action and verification
    policy. Because risk is visible in the IR, it is part of the plan a
    reviewer reads before approving a run."""
    destructive_allowed = [
        a for a in allowed if any(tok in a.lower() for tok in DESTRUCTIVE_TOKENS)
    ]
    has_rollback = any("rollback" in r.description.lower() for r in verification)
    factors: list[str] = []
    if destructive_allowed:
        factors.append(
            "destructive actions allowed without approval gating: "
            + ", ".join(destructive_allowed)
        )
    if gated:
        factors.append("approval-gated actions present: " + ", ".join(gated))
    if denied:
        factors.append("explicitly denied actions: " + ", ".join(denied))
    if not has_rollback and (destructive_allowed or gated):
        factors.append("no verification rule requires a rollback path")

    if destructive_allowed:
        level = "high"
    elif gated or denied:
        level = "medium"
    else:
        level = "low"

    return {
        "level": level,
        "destructive_actions_allowed": destructive_allowed,
        "approval_gated_actions": list(gated),
        "denied_actions": list(denied),
        "requires_human_approval": bool(gated),
        "has_rollback_requirement": has_rollback,
        "factors": factors,
    }


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

    allowed = [a.action for a in actions if a.mode == "allow"]
    gated = [a.action for a in actions if a.mode == "require_approval"]
    denied = [a.action for a in actions if a.mode == "deny"]

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
        risk_profile=_build_risk_profile(allowed, gated, denied, verification),
        trace_policy={"enabled": True, "level": "full", "record_prompts": True},
        prompt_plan=_build_prompt_plan(
            goal.name, objective, evidence, actions, model_directives,
            verification, uncertainty, outputs,
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
