"""AST and cognitive intermediate representation (IR) for IntentFlow.

Two layers live here:

1. The *syntactic* AST produced by the parser: ``Program``, ``Goal``,
   ``Section``, ``Statement``. It stays close to the source text and keeps
   line numbers for diagnostics.

2. The *cognitive IR*: typed nodes the compiler lowers statements into —
   ``EvidenceRequirement``, ``ActionPolicy``, ``VerificationRule``,
   ``UncertaintyRule``, ``ContextPolicy``, ``OutputSpec``. These describe a
   governed cognitive process, not text prompts: every policy is
   inspectable and machine-checkable before any model is invoked.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

#: Section names a goal may contain, in canonical order.
SECTION_NAMES: tuple[str, ...] = (
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


@dataclass
class Section:
    """A named section (``evidence:``, ``actions:``, ...) inside a goal."""

    name: str
    line: int
    statements: list[Statement] = field(default_factory=list)


@dataclass
class Goal:
    """A top-level ``goal Name { ... }`` block."""

    name: str
    line: int
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
    """A parsed ``.iflow`` file: goals and optional pipelines."""

    goals: list[Goal] = field(default_factory=list)
    pipelines: list[Pipeline] = field(default_factory=list)
    source_name: str = "<string>"

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
        return asdict(self)


# ---------------------------------------------------------------------------
# Cognitive IR
# ---------------------------------------------------------------------------

#: Stances a goal may take towards an evidence source.
EVIDENCE_STANCES: tuple[str, ...] = ("require", "prefer", "distrust")

#: Governance modes for actions/tools.
ACTION_MODES: tuple[str, ...] = ("allow", "deny", "require_approval")


@dataclass
class EvidenceRequirement:
    """A stance towards an evidence source: required, preferred or distrusted."""

    source: str
    stance: str  # one of EVIDENCE_STANCES
    line: int


@dataclass
class ActionPolicy:
    """Governance for a single action/tool: allowed, denied, or approval-gated."""

    action: str
    mode: str  # one of ACTION_MODES
    line: int


@dataclass
class VerificationRule:
    """A check the runtime must apply to the result before emitting output."""

    rule_id: str
    description: str
    line: int


@dataclass
class UncertaintyRule:
    """A rule mapping an uncertainty condition to a control-flow action.

    ``kind`` is ``"threshold"`` for numeric conditions such as
    ``if confidence < 0.7 ask_human`` (metric/op/threshold are set), or
    ``"symbolic"`` for conditions such as
    ``if competing_hypotheses remain run_discriminating_test``.
    """

    kind: str  # "threshold" | "symbolic"
    condition: str
    action: str
    line: int
    metric: str | None = None
    op: str | None = None
    threshold: float | None = None


@dataclass
class ContextPolicy:
    """Policy for what the agent keeps in working context."""

    max_tokens: int | None = None
    prefer: list[str] = field(default_factory=list)
    preserve: list[str] = field(default_factory=list)


@dataclass
class OutputSpec:
    """The structured fields the goal must produce."""

    fields: list[str] = field(default_factory=list)
