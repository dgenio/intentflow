"""Governed tools: real action execution with enforcement outside the model.

Two pieces:

* :class:`ToolRegistry` — binds action names (``read_logs``) to real
  handlers that serve evidence sources from a workspace directory.
* :class:`ActionGate` — the enforcement point. *Every* tool invocation goes
  through the gate, which consults the compiled action policy: denied
  actions raise, approval-gated actions block unless a grant exists, and
  every decision lands in the trace. The model never sees the gate; it
  cannot talk its way past it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol


class ActionDenied(Exception):
    """Raised when an action is forbidden by policy or lacks approval."""

    def __init__(self, action: str, reason: str) -> None:
        self.action = action
        self.reason = reason
        super().__init__(f"action {action!r} blocked: {reason}")


class _TraceLike(Protocol):
    def record(self, phase: str, event: str, detail: dict[str, Any]) -> None: ...


class ActionGate:
    """Enforces a plan's action policy on every tool invocation.

    ``approver`` decides approval-gated actions: a set of pre-granted action
    names (e.g. from ``--approve``). With no grant, gated actions are denied
    and the denial is traced — fail closed, never fail open.
    """

    def __init__(
        self,
        actions: dict[str, list[str]],
        trace: _TraceLike,
        approved: set[str] | None = None,
    ) -> None:
        self._allowed = set(actions.get("allowed", []))
        self._gated = set(actions.get("approval_required", []))
        self._denied = set(actions.get("denied", []))
        self._approved = approved or set()
        self._trace = trace

    def invoke(self, action: str, handler: Callable[..., str], *args: Any) -> str:
        if action in self._denied or (
            action not in self._allowed and action not in self._gated
        ):
            reason = "denied by policy" if action in self._denied else "not in allowed list"
            self._trace.record(
                "actions", "action_blocked", {"action": action, "reason": reason}
            )
            raise ActionDenied(action, reason)
        if action in self._gated:
            if action not in self._approved:
                self._trace.record(
                    "actions",
                    "approval_denied",
                    {"action": action, "reason": "no human approval granted"},
                )
                raise ActionDenied(action, "requires human approval (not granted)")
            self._trace.record("actions", "approval_granted", {"action": action})
        self._trace.record("actions", "tool_invoked", {"action": action, "args": list(args)})
        result = handler(*args)
        self._trace.record(
            "actions",
            "tool_completed",
            {"action": action, "result_chars": len(result)},
        )
        return result


@dataclass
class Tool:
    """A real handler bound to an action name, serving named evidence sources."""

    action: str
    serves: tuple[str, ...]
    handler: Callable[[str], str]
    description: str = ""


class ToolError(Exception):
    """A tool ran but could not produce a result (e.g. missing source file)."""


def _read_source_file(workspace: Path, source: str) -> str:
    """Read ``<workspace>/<source>.txt`` (or ``.log``/``.md``) as evidence."""
    for suffix in (".txt", ".log", ".md"):
        path = workspace / f"{source}{suffix}"
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    raise ToolError(f"no file for source {source!r} in workspace {workspace}")


class ToolRegistry:
    """Maps evidence sources to the tool (action) able to collect them."""

    def __init__(self, tools: list[Tool]) -> None:
        self._by_source: dict[str, Tool] = {}
        for tool in tools:
            for source in tool.serves:
                self._by_source[source] = tool

    def tool_for_source(self, source: str) -> Tool | None:
        return self._by_source.get(source)

    @classmethod
    def builtin(cls, workspace: str | Path) -> ToolRegistry:
        """Built-in read-only tools over a workspace directory."""
        ws = Path(workspace)
        reader = lambda source: _read_source_file(ws, source)  # noqa: E731
        return cls(
            [
                Tool(
                    action="read_logs",
                    serves=("logs", "recent_logs"),
                    handler=reader,
                    description="read log files from the workspace",
                ),
                Tool(
                    action="inspect_code",
                    serves=("config", "recent_commits", "code", "source"),
                    handler=reader,
                    description="read code/config artifacts from the workspace",
                ),
                Tool(
                    action="read_diff",
                    serves=("diff", "test_results", "style_guide"),
                    handler=reader,
                    description="read review artifacts from the workspace",
                ),
                Tool(
                    action="read_issue",
                    serves=("issue_body", "comments"),
                    handler=reader,
                    description="read an issue and its comments from the workspace",
                ),
                Tool(
                    action="search_repo",
                    serves=("repo_context", "related_issues"),
                    handler=reader,
                    description="read repository context from the workspace",
                ),
            ]
        )
