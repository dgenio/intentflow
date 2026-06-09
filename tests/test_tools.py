"""Action gate and tool registry tests: enforcement lives outside the model."""

from __future__ import annotations

from pathlib import Path

import pytest

from intentflow.compiler import compile_goal
from intentflow.parser import parse_file, parse_source
from intentflow.runtime import GoalRuntime, Trace
from intentflow.tools import ActionDenied, ActionGate, ToolRegistry

ACTIONS = {
    "allowed": ["read_logs"],
    "approval_required": ["deploy_change"],
    "denied": ["force_push"],
}


def _gate(approved: set[str] | None = None) -> tuple[ActionGate, Trace]:
    trace = Trace()
    return ActionGate(ACTIONS, trace=trace, approved=approved), trace


def test_allowed_action_executes_and_is_traced() -> None:
    gate, trace = _gate()
    assert gate.invoke("read_logs", lambda: "log content") == "log content"
    events = [e["event"] for e in trace.events]
    assert events == ["tool_invoked", "tool_completed"]


def test_denied_action_raises_and_is_traced() -> None:
    gate, trace = _gate()
    with pytest.raises(ActionDenied, match="denied by policy"):
        gate.invoke("force_push", lambda: "boom")
    assert trace.events[-1]["event"] == "action_blocked"


def test_unlisted_action_fails_closed() -> None:
    gate, trace = _gate()
    with pytest.raises(ActionDenied, match="not in allowed list"):
        gate.invoke("exfiltrate_data", lambda: "boom")
    assert trace.events[-1]["event"] == "action_blocked"


def test_gated_action_without_grant_is_denied() -> None:
    gate, trace = _gate()
    with pytest.raises(ActionDenied, match="requires human approval"):
        gate.invoke("deploy_change", lambda: "deployed")
    assert trace.events[-1]["event"] == "approval_denied"


def test_gated_action_with_grant_executes_with_approval_event() -> None:
    gate, trace = _gate(approved={"deploy_change"})
    assert gate.invoke("deploy_change", lambda: "deployed") == "deployed"
    events = [e["event"] for e in trace.events]
    assert events == ["approval_granted", "tool_invoked", "tool_completed"]


def test_builtin_registry_reads_workspace_files(tmp_path: Path) -> None:
    (tmp_path / "logs.txt").write_text("real log line\n")
    registry = ToolRegistry.builtin(tmp_path)
    tool = registry.tool_for_source("logs")
    assert tool is not None and tool.action == "read_logs"
    assert tool.handler("logs") == "real log line"


def test_runtime_collects_real_evidence_through_the_gate() -> None:
    program = parse_file("examples/diagnose.iflow")
    plan = compile_goal(program.goals[0], program.source_name).to_dict()
    result = GoalRuntime(plan, printer=None, workspace="examples/workspace").run()
    origins = {e["source"]: e["origin"] for e in result["evidence"]}
    assert origins["logs"] == "tool:read_logs"
    assert origins["config"] == "tool:inspect_code"
    assert "OOMKilled" in result["evidence"][0]["summary"]
    invoked = [e for e in result["trace"] if e["event"] == "tool_invoked"]
    assert {e["detail"]["action"] for e in invoked} == {"read_logs", "inspect_code"}


def test_runtime_blocks_tool_when_action_not_allowed() -> None:
    # Goal requires logs as evidence but never allows read_logs: the gate
    # must block the tool and the runtime must fall back to simulation.
    source = (
        "goal Locked {\n"
        "  objective:\n    diagnose without log access\n"
        "  evidence:\n    require logs\n"
        "  actions:\n    allow inspect_code\n"
        "  output:\n    root_cause\n"
        "}\n"
    )
    program = parse_source(source)
    plan = compile_goal(program.goals[0]).to_dict()
    result = GoalRuntime(plan, printer=None, workspace="examples/workspace").run()
    assert result["evidence"][0]["origin"] == "simulated"
    blocked = [e for e in result["trace"] if e["event"] == "action_blocked"]
    assert blocked and blocked[0]["detail"]["action"] == "read_logs"
