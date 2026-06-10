"""Compiler: lowers the syntactic AST into the cognitive IR and emits an
execution plan.

The execution plan is the contract between the language and any runtime
(simulated or LLM-backed). It makes agent behavior inspectable *before*
execution: which evidence is mandatory, which actions are governed, which
checks must pass, what shape the output must take, and when control
escalates to a human.

Phases of the toolchain:

    parse (parser.py) -> analyze (analyzer.py) -> compile (this module)
    -> run (runtime.py) -> audit (auditor.py)

The compiler refuses to emit a plan for a goal with analyzer ERRORs.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from intentflow import iflow_ast as ir
from intentflow._version import __version__
from intentflow.actions import default_registry
from intentflow.iflow_ast import (
    ActionPolicy,
    ActionRule,
    ContextPolicy,
    EvidencePolicy,
    EvidenceRequirement,
    Goal,
    GoalMetadata,
    OutputField,
    OutputSchema,
    Program,
    PromptBlock,
    PromptPlan,
    RiskProfile,
    UncertaintyAction,
    UncertaintyCondition,
    UncertaintyPolicy,
    UncertaintyRule,
    VerificationPolicy,
    VerificationRule,
)

#: Version of the *plan format* (independent of the package version).
PLAN_VERSION = "0.2"

#: The phase order every conformant run follows (embedded in each plan and
#: checked by the auditor).
EXECUTION_PHASES: tuple[str, ...] = (
    "parse",
    "analyze",
    "compile",
    "prepare_context",
    "collect_evidence",
    "build_messages",
    "call_backend",
    "parse_output",
    "verify_output",
    "apply_uncertainty_policy",
    "enforce_action_policy",
    "finalize",
    "trace",
)

_THRESHOLD_RE = re.compile(
    r"^if\s+([a-z_]+)\s*(<=|>=|<|>|==)\s*([0-9]*\.?[0-9]+)\s+([a-z_]\w*)$"
)
_SYMBOLIC_RE = re.compile(r"^if\s+(.+?)\s+([a-z_]\w*)$")
_MAX_TOKENS_RE = re.compile(r"^max_tokens\s+(\d+)$")
#: ``check <metric> <op> <number>`` — a machine-checkable verification rule
#: evaluated by the runtime against structured state (e.g. confidence).
_CHECK_RE = re.compile(r"^check\s+([a-z_]+)\s*(<=|>=|<|>|==)\s*([0-9]*\.?[0-9]+)$")
#: ``require <named_check>`` — a named verification requirement.
_REQUIRE_RE = re.compile(r"^require\s+([a-z_][a-z0-9_]*)$")
#: Typed output field: ``name: type`` (type may be ``list[string]`` etc.).
_OUTPUT_FIELD_RE = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([A-Za-z]+(?:\[[A-Za-z]+\])?\??)$"
)
_BARE_OUTPUT_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)$")
#: Whole-word citation verbs, so "explicit"/"implicit"/"solicit" do not match.
_CITE_RE = re.compile(r"\bcit(?:e|es|ed|ing|ation|ations)\b")
#: ``key value`` metadata statement in a ``meta:`` section.
_META_RE = re.compile(r"^([a-z_]+)\s+(.+)$")

#: Named ``require`` checks the runtime can evaluate mechanically. Everything
#: else named with ``require`` is judged (LLM judge or recorded as skipped).
MACHINE_REQUIRE_CHECKS: tuple[str, ...] = ("cites_evidence",)


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


def extract_metadata(goal: Goal, source_name: str = "<string>") -> GoalMetadata:
    """Lower the optional ``meta:`` section plus provenance."""
    meta = GoalMetadata(name=goal.name, line=goal.line, source=source_name)
    for stmt in goal.statements("meta"):
        match = _META_RE.match(stmt.text)
        if not match:
            raise CompileError(
                f"malformed meta statement {stmt.text!r}; expected 'key value'",
                stmt.line,
                source_name,
            )
        key, value = match.group(1), match.group(2).strip().strip('"')
        if key == "description":
            meta.description = value
        elif key == "owner":
            meta.owner = value
        elif key == "version":
            meta.version = value
        elif key == "tags":
            meta.tags = [t.strip() for t in value.split(",") if t.strip()]
        else:
            raise CompileError(
                f"unknown meta key {key!r}; expected one of: "
                "description, owner, version, tags",
                stmt.line,
                source_name,
            )
    return meta


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


def extract_actions(goal: Goal, source_name: str = "<string>") -> list[ActionRule]:
    rules: list[ActionRule] = []
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
        rules.append(ActionRule(action=parts[1].strip(), mode=verb, line=stmt.line))
    return rules


def classify_verification(description: str) -> dict[str, Any]:
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
    if _CITE_RE.search(text):  # cite / cites / cited / citation(s)
        return {"kind": "cites_evidence", "mode": "machine"}
    require_match = _REQUIRE_RE.match(text)
    if require_match:
        name = require_match.group(1)
        if name in MACHINE_REQUIRE_CHECKS:
            return {"kind": name, "mode": "machine"}
        return {"kind": "judged", "name": name, "mode": "judged"}
    if "rollback" in text:
        return {"kind": "requires_phrase", "arg": "rollback", "mode": "machine"}
    return {"kind": "judged", "mode": "judged"}


def extract_verification(goal: Goal) -> list[VerificationRule]:
    return [
        VerificationRule(
            rule_id=f"V{i}",
            description=stmt.text,
            line=stmt.line,
            check=classify_verification(stmt.text),
        )
        for i, stmt in enumerate(goal.statements("verify"), start=1)
    ]


def extract_uncertainty(goal: Goal, source_name: str = "<string>") -> list[UncertaintyRule]:
    rules: list[UncertaintyRule] = []
    for stmt in goal.statements("uncertainty"):
        match = _THRESHOLD_RE.match(stmt.text)
        if match:
            metric, op, value, action = match.groups()
            condition = UncertaintyCondition(
                kind="threshold",
                text=f"{metric} {op} {value}",
                metric=metric,
                op=op,
                threshold=float(value),
            )
        else:
            match = _SYMBOLIC_RE.match(stmt.text)
            if not match:
                raise CompileError(
                    f"malformed uncertainty rule {stmt.text!r}; expected "
                    "'if <metric> <op> <number> <action>' or 'if <signal> <action>'",
                    stmt.line,
                    source_name,
                )
            condition_text, action = match.groups()
            condition_text = condition_text.strip()
            signal = condition_text.split()[0]
            condition = UncertaintyCondition(
                kind="signal", text=condition_text, signal=signal
            )
        rules.append(
            UncertaintyRule(
                condition=condition,
                action=UncertaintyAction(
                    name=action, primitive=action in ir.UNCERTAINTY_PRIMITIVES
                ),
                line=stmt.line,
            )
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


def parse_output_field(text: str, line: int, source_name: str = "<string>") -> OutputField:
    """Parse one output statement: ``name: type`` or a bare legacy ``name``
    (which defaults to ``string``; the analyzer reports IFLOW017 for it)."""
    match = _OUTPUT_FIELD_RE.match(text)
    if match:
        name, type_text = match.group(1), match.group(2)
        if type_text not in ir.OUTPUT_TYPES:
            raise CompileError(
                f"invalid output type {type_text!r} for field {name!r}; "
                "expected one of: " + ", ".join(ir.OUTPUT_TYPES),
                line,
                source_name,
            )
        optional = type_text.endswith("?")
        core = type_text.rstrip("?")
        if core.startswith("list["):
            base, item = "list", core[len("list["):-1]
        else:
            base, item = core, None
        return OutputField(
            name=name, type=type_text, base=base, line=line,
            optional=optional, item_type=item,
        )
    match = _BARE_OUTPUT_RE.match(text)
    if match:
        return OutputField(
            name=match.group(1), type="string", base="string", line=line,
        )
    raise CompileError(
        f"malformed output field {text!r}; expected 'name: type' "
        "(e.g. 'confidence: number', 'proposed_labels: list[string]')",
        line,
        source_name,
    )


def extract_output(goal: Goal, source_name: str = "<string>") -> OutputSchema:
    return OutputSchema(
        fields=[
            parse_output_field(s.text, s.line, source_name)
            for s in goal.statements("output")
        ]
    )


def extract_model_directives(goal: Goal) -> list[str]:
    return [s.text for s in goal.statements("model")]


# ---------------------------------------------------------------------------
# Inspection (structured, at-a-glance views for `intentflow inspect`)
# ---------------------------------------------------------------------------


def inspect_goal(goal: Goal, source_name: str = "<string>") -> dict[str, Any]:
    """A structured, at-a-glance view of a goal: sections present, action
    governance, evidence stances, typed output fields, and analyzer
    diagnostics — without compiling a full plan."""
    from intentflow.analyzer import analyze_goal

    try:
        actions = ActionPolicy.from_rules(extract_actions(goal, source_name))
        evidence = EvidencePolicy.from_requirements(extract_evidence(goal, source_name))
    except CompileError:
        actions, evidence = ActionPolicy(), EvidencePolicy()
    try:
        output = extract_output(goal, source_name)
    except CompileError:
        output = OutputSchema()
    diagnostics = analyze_goal(goal, source_name)
    return {
        "goal": goal.name,
        "objective": extract_objective(goal),
        "sections": list(goal.sections),
        "allowed_actions": actions.allowed,
        "approval_gated_actions": actions.approval_required,
        "denied_actions": actions.denied,
        "required_evidence": evidence.required,
        "optional_evidence": evidence.optional,
        "distrusted_evidence": evidence.distrusted,
        "output_fields": [f"{f.name}: {f.type}" for f in output.fields],
        "diagnostics": [d.to_dict() for d in diagnostics],
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
    metadata: dict[str, Any]
    context_policy: dict[str, Any]
    evidence_policy: dict[str, list[str]]
    action_policy: dict[str, list[str]]
    model_directives: list[str]
    verification_policy: dict[str, Any]
    uncertainty_policy: dict[str, Any]
    calibration: dict[str, Any]
    output_schema: dict[str, Any]
    risk_profile: dict[str, Any]
    trace_policy: dict[str, Any]
    prompt_plan: dict[str, Any]
    execution_phases: list[str] = field(default_factory=lambda: list(EXECUTION_PHASES))
    plan_version: str = PLAN_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _build_prompt_plan(
    goal_name: str,
    objective: str,
    evidence: EvidencePolicy,
    actions: ActionPolicy,
    model_directives: list[str],
    verification: list[VerificationRule],
    uncertainty: list[UncertaintyRule],
    output: OutputSchema,
) -> PromptPlan:
    """A staged prompt plan: one governed block per concern, instead of a
    single opaque mega-prompt.

    Each block is a distinct, inspectable message so that *what the model is
    told about evidence, allowed actions, denied actions, verification,
    uncertainty handling, and the required output format* is visible (and
    diffable) before any model runs.
    """
    system = (
        f"You are executing the IntentFlow goal '{goal_name}'. You are a "
        "governed reasoning process: separate observation from inference, "
        "attach a confidence in [0, 1] to your conclusion, cite evidence ids "
        "for every claim, and never take an action outside the allowed list."
    )
    if model_directives:
        system += " Reasoning discipline: " + "; ".join(model_directives) + "."

    objective_block = f"Objective: {objective}"

    evidence_block = (
        "Required evidence (collect before reasoning, label each item E1, E2, ...): "
        + (", ".join(evidence.required) if evidence.required else "(none declared)")
    )
    if evidence.optional:
        evidence_block += f". Optional, use when available: {', '.join(evidence.optional)}"
    if evidence.preferred:
        evidence_block += f". Prefer when available: {', '.join(evidence.preferred)}"
    if evidence.distrusted:
        evidence_block += (
            ". Treat as untrusted, never cite as sole support: "
            + ", ".join(evidence.distrusted)
        )

    allowed_block = (
        "Allowed actions (you may call these): "
        + (", ".join(actions.allowed) if actions.allowed else "(none)")
    )
    if actions.approval_required:
        allowed_block += (
            ". Approval-gated (blocked until a human approves): "
            + ", ".join(actions.approval_required)
        )

    denied_block = (
        "Forbidden actions (never call these): "
        + (", ".join(actions.denied) if actions.denied else "(none)")
    )

    verify_block = (
        "Before producing output, check the result against every rule and "
        "report pass/fail per rule: "
        + ("; ".join(r.description for r in verification) if verification else "(none)")
    )

    uncertainty_block = (
        "Uncertainty handling — when a condition holds, take the named action: "
        + (
            "; ".join(f"if {r.condition.text} -> {r.action.name}" for r in uncertainty)
            if uncertainty
            else "(none)"
        )
    )

    field_specs = (
        ", ".join(f"{f.name} ({f.type})" for f in output.fields)
        if output.fields
        else "(unspecified)"
    )
    output_block = (
        'Produce a JSON object {"output": {...}, "confidence": number, '
        '"citations": [evidence ids]} where "output" has exactly these '
        f"typed fields: {field_specs}. Optional fields (marked with ?) may be "
        "null. Do not add commentary outside the JSON object."
    )

    return PromptPlan(
        blocks=[
            PromptBlock("system", "system", system),
            PromptBlock("objective", "user", objective_block),
            PromptBlock("evidence", "user", evidence_block),
            PromptBlock("actions_allowed", "user", allowed_block),
            PromptBlock("actions_denied", "user", denied_block),
            PromptBlock("verify", "user", verify_block),
            PromptBlock("uncertainty", "user", uncertainty_block),
            PromptBlock("output", "user", output_block),
        ]
    )


def build_risk_profile(
    actions: ActionPolicy,
    verification: list[VerificationRule],
    uncertainty: list[UncertaintyRule],
) -> RiskProfile:
    """Compute the goal's risk posture from its policies, using the action
    registry's metadata (with name heuristics for unregistered actions).
    Because risk is visible in the IR, it is part of the plan a reviewer
    reads before approving a run."""
    registry = default_registry()
    side_effect = [
        a
        for a in actions.allowed + actions.approval_required
        if registry.is_side_effect(a)
    ]
    ungated_side_effect = [a for a in actions.allowed if registry.is_side_effect(a)]
    broad_allowed = [a for a in actions.allowed if registry.is_overly_broad(a)]
    high_risk_allowed = [
        a for a in actions.allowed if registry.spec_for(a).risk == "high"
    ]
    has_rollback = any("rollback" in r.description.lower() for r in verification)
    has_human_path = any(
        r.action.name in ("ask_human", "escalate", "block_action") for r in uncertainty
    )

    missing: list[str] = []
    for action in ungated_side_effect:
        missing.append(
            f"side-effect action '{action}' is allowed without approval gating"
        )
    if not verification:
        missing.append("no verification rules declared")
    if not uncertainty:
        missing.append("no uncertainty rules declared")
    elif not has_human_path:
        missing.append("no human escalation path (no ask_human/block_action rule)")
    if not has_rollback and side_effect:
        missing.append("no verification rule requires a rollback path")

    factors: list[str] = []
    if ungated_side_effect:
        factors.append(
            "side-effect actions allowed without approval: "
            + ", ".join(ungated_side_effect)
        )
    if broad_allowed:
        factors.append("overly broad actions allowed: " + ", ".join(broad_allowed))
    if actions.approval_required:
        factors.append(
            "approval-gated actions present: " + ", ".join(actions.approval_required)
        )
    if actions.denied:
        factors.append("explicitly denied actions: " + ", ".join(actions.denied))

    if ungated_side_effect or broad_allowed or high_risk_allowed:
        level = "high"
    elif side_effect or actions.approval_required:
        level = "medium"
    else:
        level = "low"

    return RiskProfile(
        level=level,
        side_effect_actions=side_effect,
        blocked_actions=list(actions.denied),
        approval_required=list(actions.approval_required),
        missing_safety_controls=missing,
        factors=factors,
    )


def compile_goal(goal: Goal, source_name: str = "<string>") -> ExecutionPlan:
    """Lower a goal into an :class:`ExecutionPlan`.

    Raises :class:`CompileError` on the first analyzer ERROR.
    """
    from intentflow.analyzer import analyze_goal

    errors = [d for d in analyze_goal(goal, source_name) if d.severity == "error"]
    if errors:
        first = errors[0]
        raise CompileError(f"[{first.code}] {first.message}", first.line, source_name)

    objective = extract_objective(goal)
    metadata = extract_metadata(goal, source_name)
    evidence = EvidencePolicy.from_requirements(extract_evidence(goal, source_name))
    actions = ActionPolicy.from_rules(extract_actions(goal, source_name))
    context = extract_context(goal, source_name)
    verification = extract_verification(goal)
    uncertainty = extract_uncertainty(goal, source_name)
    output = extract_output(goal, source_name)
    model_directives = extract_model_directives(goal)

    return ExecutionPlan(
        goal=goal.name,
        objective=objective,
        metadata=metadata.to_dict(),
        context_policy=context.to_dict(),
        evidence_policy=evidence.to_dict(),
        action_policy=actions.to_dict(),
        model_directives=model_directives,
        verification_policy=VerificationPolicy(rules=verification).to_dict(),
        uncertainty_policy=UncertaintyPolicy(rules=uncertainty).to_dict(),
        # Raw model self-reported confidence is miscalibrated; uncertainty
        # rules fire on calibrated values. Shrinkage toward 0.5 is a stand-in
        # until a learned calibration map exists.
        calibration={"method": "shrinkage", "midpoint": 0.5, "factor": 0.8},
        output_schema=output.to_dict(),
        risk_profile=build_risk_profile(actions, verification, uncertainty).to_dict(),
        trace_policy={"enabled": True, "level": "full", "record_prompts": True},
        prompt_plan=_build_prompt_plan(
            goal.name, objective, evidence, actions, model_directives,
            verification, uncertainty, output,
        ).to_dict(),
    )


def source_hash(text: str) -> str:
    """SHA-256 of the exact source text, embedded in plans and traces so a
    trace can always be matched to the program version that produced it."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def plan_hash(document: dict[str, Any]) -> str:
    """A short, stable hash of a compiled document."""
    canonical = json.dumps(document, sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()[:16]


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
        produced[stage.goal_name] = set(
            extract_output(goal, source_name).field_names()
        )


def compile_program(program: Program) -> dict[str, Any]:
    """Compile every goal and pipeline in a program into a JSON document."""
    for pipeline in program.pipelines:
        _check_pipeline(pipeline, program, program.source_name)
    return {
        "intentflow_version": __version__,
        "plan_version": PLAN_VERSION,
        "source": program.source_name,
        "source_hash": source_hash(program.source_text),
        "goals": [compile_goal(g, program.source_name).to_dict() for g in program.goals],
        "pipelines": [
            {"name": p.name, "stages": [s.goal_name for s in p.stages]}
            for p in program.pipelines
        ],
    }
