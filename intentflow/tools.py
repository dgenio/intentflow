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

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol


class ActionDenied(Exception):
    """Raised when an action is forbidden by policy or lacks approval."""

    def __init__(self, action: str, reason: str) -> None:
        self.action = action
        self.reason = reason
        super().__init__(f"action {action!r} blocked: {reason}")


class ApprovalError(ActionDenied):
    """Raised specifically when an approval-gated action is not approved."""


class _TraceLike(Protocol):
    def record(self, phase: str, event: str, detail: dict[str, Any]) -> None: ...


# ---------------------------------------------------------------------------
# Approvers: how an approval-gated action gets a (recorded) human decision
# ---------------------------------------------------------------------------


@dataclass
class ApprovalDecision:
    """A human (or human-stand-in) decision on an approval-gated action."""

    approved: bool
    via: str
    note: str = ""


class Approver(Protocol):
    def request(self, action: str, context: dict[str, Any]) -> ApprovalDecision:
        """Block until a decision exists for ``action``."""
        ...


class PreGrantedApprover:
    """Approves exactly the actions named ahead of time (e.g. ``--approve``).
    Fail-closed: anything not pre-granted is denied."""

    def __init__(self, approved: set[str] | None = None) -> None:
        self._approved = set(approved or ())

    def request(self, action: str, context: dict[str, Any]) -> ApprovalDecision:
        if action in self._approved:
            return ApprovalDecision(True, "pre-grant", "pre-granted before the run")
        return ApprovalDecision(False, "pre-grant", "no human approval granted")


class CallbackApprover:
    """Delegates to any callable; handy for tests and embedding. The callable
    may return a bool or a full :class:`ApprovalDecision`."""

    def __init__(
        self, fn: Callable[[str, dict[str, Any]], "bool | ApprovalDecision"]
    ) -> None:
        self._fn = fn

    def request(self, action: str, context: dict[str, Any]) -> ApprovalDecision:
        result = self._fn(action, context)
        if isinstance(result, ApprovalDecision):
            return result
        return ApprovalDecision(bool(result), "callback")


class TTYApprover:
    """Blocking, interactive approval over a terminal. Prompts for each gated
    action and waits for a y/n answer. ``input_fn``/``output`` are injectable
    so the prompt is testable without a real TTY."""

    def __init__(
        self,
        input_fn: Callable[[str], str] = input,
        output: Callable[[str], None] | None = None,
    ) -> None:
        self._input = input_fn
        self._output = output or (lambda msg: print(msg, file=sys.stderr))

    def request(self, action: str, context: dict[str, Any]) -> ApprovalDecision:
        self._output(
            f"[approval] action {action!r} requires human approval.\n"
            f"           context: {json.dumps(context)}"
        )
        try:
            answer = self._input(f"[approval] approve {action!r}? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        approved = answer in ("y", "yes")
        return ApprovalDecision(approved, "tty", f"answered {answer!r}")


class WebhookApprover:
    """Synchronous webhook approval: POST a request to ``url`` and read the
    decision from the JSON response (``{"approved": bool, "note": str}``).

    Uses ``urllib`` (no dependency); ``transport`` is injectable so tests run
    without a network. Asynchronous/polling approval is a future extension."""

    def __init__(
        self,
        url: str,
        transport: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._url = url
        self._timeout = timeout
        self._transport = transport or self._http_post

    def _http_post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        import urllib.request

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def request(self, action: str, context: dict[str, Any]) -> ApprovalDecision:
        response = self._transport(
            self._url, {"action": action, "context": context}
        )
        return ApprovalDecision(
            bool(response.get("approved", False)),
            "webhook",
            str(response.get("note", "")),
        )


class ActionGate:
    """Enforces a plan's action policy on every tool invocation.

    Denied or unlisted actions raise. Approval-gated actions consult an
    :class:`Approver` (pre-grant, interactive TTY, or webhook) and **block**
    until it decides; the decision — granted or denied, and via which channel
    — is always recorded in the trace. Fail closed: no decision means denied.
    """

    def __init__(
        self,
        actions: dict[str, list[str]],
        trace: _TraceLike,
        approved: set[str] | None = None,
        approver: Approver | None = None,
    ) -> None:
        self._allowed = set(actions.get("allowed", []))
        self._gated = set(actions.get("approval_required", []))
        self._denied = set(actions.get("denied", []))
        self._approver = approver or PreGrantedApprover(approved)
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
            decision = self._approver.request(action, {"action": action, "args": list(args)})
            if not decision.approved:
                self._trace.record(
                    "actions",
                    "approval_denied",
                    {
                        "action": action,
                        "via": decision.via,
                        "reason": decision.note or "no human approval granted",
                    },
                )
                raise ApprovalError(
                    action,
                    f"requires human approval (not granted via {decision.via})",
                )
            self._trace.record(
                "actions",
                "approval_granted",
                {"action": action, "via": decision.via, "note": decision.note},
            )
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
            self.add(tool)

    def add(self, tool: Tool) -> "ToolRegistry":
        """Register a tool, binding it to every evidence source it serves."""
        for source in tool.serves:
            self._by_source[source] = tool
        return self

    def register(
        self,
        action: str,
        serves: tuple[str, ...],
        handler: Callable[[str], str],
        description: str = "",
    ) -> "ToolRegistry":
        """Register a Python function as a governed action (for embedding).

        The handler still runs *through the action gate*: if the goal does not
        allow ``action``, the gate blocks it regardless of registration."""
        return self.add(Tool(action=action, serves=serves, handler=handler,
                             description=description))

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
