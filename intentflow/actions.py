"""Action registry: metadata about the actions a goal may govern.

The runtime does not execute arbitrary external tools yet, but the language
*reasons* about action governance: the analyzer warns when a side-effecting
action is allowed without an approval gate, and the compiler's risk profile
is computed from this metadata.

Two layers of knowledge:

* a **default registry** of well-known actions with curated metadata;
* **heuristics** for unknown action names (verb sniffing), so a goal that
  invents ``deploy_to_prod`` still gets honest risk accounting.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

#: Verbs that suggest an action mutates the outside world.
SIDE_EFFECT_TOKENS: tuple[str, ...] = (
    "post",
    "write",
    "send",
    "create",
    "deploy",
    "delete",
    "drop",
    "push",
    "merge",
    "close",
    "force",
    "shutdown",
    "restart",
    "execute",
    "publish",
    "update",
)

#: Action names so broad that allowing them without approval is itself a risk.
OVERLY_BROAD_ACTIONS: tuple[str, ...] = (
    "execute_code",
    "run_command",
    "shell",
    "eval",
    "sudo",
)


@dataclass
class ActionSpec:
    """Metadata describing one action the language knows about."""

    name: str
    description: str
    side_effect: bool
    risk: str  # "low" | "medium" | "high"
    requires_approval_by_default: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ActionRegistry:
    """A lookup of :class:`ActionSpec` with heuristics for unknown names."""

    def __init__(self, specs: list[ActionSpec] | None = None) -> None:
        self._specs: dict[str, ActionSpec] = {s.name: s for s in (specs or [])}

    def add(self, spec: ActionSpec) -> "ActionRegistry":
        self._specs[spec.name] = spec
        return self

    def get(self, name: str) -> ActionSpec | None:
        return self._specs.get(name)

    def names(self) -> list[str]:
        return sorted(self._specs)

    def spec_for(self, name: str) -> ActionSpec:
        """The registered spec, or a heuristic one derived from the name."""
        known = self._specs.get(name)
        if known is not None:
            return known
        lowered = name.lower()
        if lowered in OVERLY_BROAD_ACTIONS:
            return ActionSpec(
                name=name,
                description="(unregistered) overly broad action",
                side_effect=True,
                risk="high",
                requires_approval_by_default=True,
            )
        side_effect = any(tok in lowered for tok in SIDE_EFFECT_TOKENS)
        return ActionSpec(
            name=name,
            description="(unregistered action; risk inferred from its name)",
            side_effect=side_effect,
            risk="medium" if side_effect else "low",
            requires_approval_by_default=side_effect,
        )

    def is_side_effect(self, name: str) -> bool:
        return self.spec_for(name).side_effect

    def is_overly_broad(self, name: str) -> bool:
        return name.lower() in OVERLY_BROAD_ACTIONS

    def to_dict(self) -> dict[str, Any]:
        return {name: spec.to_dict() for name, spec in sorted(self._specs.items())}


#: The default registry of actions the examples and docs use.
DEFAULT_ACTIONS: tuple[ActionSpec, ...] = (
    ActionSpec("read_issue", "read an issue and its comment thread", False, "low"),
    ActionSpec("search_repo", "search repository files and history", False, "low"),
    ActionSpec("draft_comment", "draft (but not post) a comment", False, "low"),
    ActionSpec("post_comment", "post a comment visible to others", True, "medium", True),
    ActionSpec("close_issue", "close an issue", True, "medium", True),
    ActionSpec("read_logs", "read log files", False, "low"),
    ActionSpec("inspect_code", "read source code and configuration", False, "low"),
    ActionSpec("read_diff", "read a code diff and review artifacts", False, "low"),
    ActionSpec("deploy_change", "deploy a change to a live system", True, "high", True),
    ActionSpec("write_database", "mutate a production database", True, "high", True),
    ActionSpec("run_discriminating_test", "run a test that separates hypotheses", False, "low"),
    ActionSpec("ask_human", "escalate a decision to a human", False, "low"),
    ActionSpec("block_action", "refuse to act and stop the run", False, "low"),
)


def default_registry() -> ActionRegistry:
    """A fresh registry seeded with the default actions."""
    return ActionRegistry(list(DEFAULT_ACTIONS))
