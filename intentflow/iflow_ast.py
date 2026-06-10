"""AST and cognitive intermediate representation (IR) for IntentFlow.

Two layers live here:

1. The *syntactic* AST produced by the parser: ``Program``, ``Goal``,
   ``Section``, ``Statement``. It stays close to the source text and keeps
   line/column positions for diagnostics.

2. The *cognitive IR*: typed nodes the compiler lowers statements into —
   ``EvidenceRequirement``/``EvidencePolicy``, ``ActionRule``/``ActionPolicy``,
   ``VerificationRule``/``VerificationPolicy``, ``UncertaintyRule``,
   ``OutputField``/``OutputSchema``, ``ContextPolicy``, ``GoalMetadata``,
   ``PromptPlan``, ``RiskProfile``. These describe a governed cognitive
   process, not text prompts: every policy is inspectable and
   machine-checkable before any model is invoked.

Every IR node is JSON-serializable via ``to_dict()``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

#: Section names a goal may contain, in canonical order.
SECTION_NAMES: tuple[str, ...] = (
    "meta",
    "objective",
    "context",
    "evidence",
    "model",
    "actions",
    "verify",
    "uncertainty",
    "output",
)

# ---------------------------------------------------------------------------
# Syntactic AST
# ---------------------------------------------------------------------------


@dataclass
class Statement:
    """A single line-based statement inside a section."""

    text: str
    line: int
    column: int = 1


@dataclass
class Section:
    """A named section (``evidence:``, ``actions:``, ...) inside a goal."""

    name: str
    line: int
    column: int = 1
    statements: list[Statement] = field(default_factory=list)


@dataclass
class Goal:
    """A top-level ``goal Name { ... }`` block."""

    name: str
    line: int
    column: int = 1
    sections: dict[str, Section] = field(default_factory=dict)

    def section(self, name: str) -> Section | None:
        return self.sections.get(name)

    def statements(self, name: str) -> list[Statement]:
        sec = self.sections.get(name)
        return sec.statements if sec else []


@dataclass
class StageRef:
    """A reference to a goal executed as one stage of a pipeline."""

    goal_name: str
    line: int


@dataclass
class Pipeline:
    """A top-level ``pipeline Name { stage GoalA ... }`` block.

    Stages run in order; the structured outputs of earlier stages become
    addressable evidence (``GoalName.field``) for later stages.
    """

    name: str
    line: int
    stages: list[StageRef] = field(default_factory=list)


@dataclass
class Program:
    """A parsed ``.iflow`` file: goals and optional pipelines.

    ``source_text`` keeps the exact source so the compiler can embed a
    ``source_hash`` in every plan it emits.
    """

    goals: list[Goal] = field(default_factory=list)
    pipelines: list[Pipeline] = field(default_factory=list)
    source_name: str = "<string>"
    source_text: str = ""

    def goal(self, name: str) -> Goal | None:
        for g in self.goals:
            if g.name == name:
                return g
        return None

    def pipeline(self, name: str) -> Pipeline | None:
        for p in self.pipelines:
            if p.name == name:
                return p
        return None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("source_text", None)  # the AST dump should not embed the file
        return data


# ---------------------------------------------------------------------------
# Cognitive IR
# ---------------------------------------------------------------------------

#: Stances a goal may take towards an evidence source.
EVIDENCE_STANCES: tuple[str, ...] = ("require", "optional", "prefer", "distrust")

#: Governance modes for actions/tools.
ACTION_MODES: tuple[str, ...] = ("allow", "deny", "require_approval")

#: Output field types the language supports. ``?`` marks an optional field
#: (the value may be null / omitted).
OUTPUT_TYPES: tuple[str, ...] = (
    "string",
    "string?",
    "number",
    "number?",
    "boolean",
    "boolean?",
    "markdown",
    "markdown?",
    "list[string]",
    "list[number]",
    "object",
    "object?",
)

#: Built-in uncertainty control-flow actions the language understands as
#: escalation primitives (as opposed to governed tool invocations).
UNCERTAINTY_PRIMITIVES: tuple[str, ...] = (
    "ask_human",
    "block_action",
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

#: Symbolic uncertainty signals the runtime knows how to evaluate.
KNOWN_SIGNALS: tuple[str, ...] = (
    "missing_evidence",
    "security_risk",
    "competing_hypotheses",
)


class _Node:
    """Mixin: every IR node serializes to plain JSON-compatible dicts."""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)  # type: ignore[call-overload]


@dataclass
class GoalMetadata(_Node):
    """Optional metadata from a goal's ``meta:`` section plus provenance."""

    name: str
    line: int
    source: str = "<string>"
    description: str | None = None
    owner: str | None = None
    version: str | None = None
    tags: list[str] = field(default_factory=list)


@dataclass
class EvidenceRequirement(_Node):
    """A stance towards one evidence source."""

    source: str
    stance: str  # one of EVIDENCE_STANCES
    line: int


@dataclass
class EvidencePolicy(_Node):
    """All of a goal's evidence stances, grouped for inspection."""

    required: list[str] = field(default_factory=list)
    optional: list[str] = field(default_factory=list)
    preferred: list[str] = field(default_factory=list)
    distrusted: list[str] = field(default_factory=list)

    @classmethod
    def from_requirements(cls, reqs: list[EvidenceRequirement]) -> "EvidencePolicy":
        policy = cls()
        buckets = {
            "require": policy.required,
            "optional": policy.optional,
            "prefer": policy.preferred,
            "distrust": policy.distrusted,
        }
        for req in reqs:
            buckets[req.stance].append(req.source)
        return policy


@dataclass
class ActionRule(_Node):
    """Governance for a single action/tool: allowed, denied, or approval-gated."""

    action: str
    mode: str  # one of ACTION_MODES
    line: int


@dataclass
class ActionPolicy(_Node):
    """All of a goal's action rules, grouped by governance mode."""

    allowed: list[str] = field(default_factory=list)
    approval_required: list[str] = field(default_factory=list)
    denied: list[str] = field(default_factory=list)

    @classmethod
    def from_rules(cls, rules: list[ActionRule]) -> "ActionPolicy":
        policy = cls()
        buckets = {
            "allow": policy.allowed,
            "require_approval": policy.approval_required,
            "deny": policy.denied,
        }
        for rule in rules:
            buckets[rule.mode].append(rule.action)
        return policy


@dataclass
class VerificationRule(_Node):
    """A check the runtime must apply to the result before emitting output.

    ``check`` is the typed classification: ``cites_evidence`` /
    ``requires_phrase`` / ``threshold_check`` are machine-evaluated;
    ``judged`` rules need an LLM judge and are recorded as skipped (never
    silently passed) when no judge is configured.
    """

    rule_id: str
    description: str
    line: int
    check: dict[str, Any] = field(default_factory=dict)


@dataclass
class VerificationPolicy(_Node):
    """All of a goal's verification rules."""

    rules: list[VerificationRule] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"rules": [r.to_dict() for r in self.rules]}


@dataclass
class UncertaintyCondition(_Node):
    """The condition half of an uncertainty rule.

    ``kind`` is ``"threshold"`` for numeric conditions such as
    ``confidence < 0.7`` (metric/op/threshold are set) or ``"signal"`` for
    symbolic conditions such as ``missing_evidence``.
    """

    kind: str  # "threshold" | "signal"
    text: str
    metric: str | None = None
    op: str | None = None
    threshold: float | None = None
    signal: str | None = None


@dataclass
class UncertaintyAction(_Node):
    """The action half of an uncertainty rule.

    ``primitive`` is True when the action is a built-in escalation primitive
    (``ask_human``, ``block_action``, ...) rather than a governed tool name.
    """

    name: str
    primitive: bool = True


@dataclass
class UncertaintyRule(_Node):
    """A rule mapping an uncertainty condition to a control-flow action."""

    condition: UncertaintyCondition
    action: UncertaintyAction
    line: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition": self.condition.to_dict(),
            "action": self.action.to_dict(),
            "line": self.line,
        }


@dataclass
class UncertaintyPolicy(_Node):
    """All of a goal's uncertainty rules."""

    rules: list[UncertaintyRule] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"rules": [r.to_dict() for r in self.rules]}


@dataclass
class OutputField(_Node):
    """One typed field of a goal's output contract.

    ``type`` is the declared type text (e.g. ``list[string]``, ``number?``);
    ``base`` is the scalar/container kind (``string``/``number``/``boolean``/
    ``markdown``/``list``/``object``); ``item_type`` is set for lists; and
    ``optional`` reflects a trailing ``?``.
    """

    name: str
    type: str
    base: str
    line: int
    optional: bool = False
    item_type: str | None = None


@dataclass
class OutputSchema(_Node):
    """The structured, typed fields the goal must produce."""

    fields: list[OutputField] = field(default_factory=list)

    def field_names(self) -> list[str]:
        return [f.name for f in self.fields]

    def to_dict(self) -> dict[str, Any]:
        return {"fields": [f.to_dict() for f in self.fields]}


@dataclass
class ContextPolicy(_Node):
    """Policy for what the agent keeps in working context."""

    max_tokens: int | None = None
    prefer: list[str] = field(default_factory=list)
    preserve: list[str] = field(default_factory=list)


@dataclass
class PromptBlock(_Node):
    """One inspectable block of the staged prompt plan."""

    phase: str
    role: str
    instruction: str


@dataclass
class PromptPlan(_Node):
    """The staged prompt plan: one governed block per concern, instead of a
    single opaque mega-prompt."""

    blocks: list[PromptBlock] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"blocks": [b.to_dict() for b in self.blocks]}


@dataclass
class RiskProfile(_Node):
    """The risk posture computed from a goal's policies."""

    level: str  # "low" | "medium" | "high"
    side_effect_actions: list[str] = field(default_factory=list)
    blocked_actions: list[str] = field(default_factory=list)
    approval_required: list[str] = field(default_factory=list)
    missing_safety_controls: list[str] = field(default_factory=list)
    factors: list[str] = field(default_factory=list)


#: Backwards-compatible aliases for the pre-0.2 IR names.
OutputSpec = OutputSchema
