"""Approval-gate tests: pre-grant, interactive TTY, webhook, and callback
approvers — all blocking, all recorded in the trace."""

from __future__ import annotations

import pytest

from intentflow.compiler import compile_goal
from intentflow.parser import parse_source
from intentflow.runtime import GoalRuntime, Trace
from intentflow.tools import (
    ApprovalDecision,
    ApprovalError,
    ActionGate,
    CallbackApprover,
    PreGrantedApprover,
    TTYApprover,
    WebhookApprover,
)

ACTIONS = {"allowed": ["read_logs"], "approval_required": ["deploy"], "denied": []}


def _gate(approver) -> tuple[ActionGate, Trace]:
    trace = Trace()
    return ActionGate(ACTIONS, trace=trace, approver=approver), trace


def test_pregranted_approver_allows_named_actions() -> None:
    gate, trace = _gate(PreGrantedApprover({"deploy"}))
    assert gate.invoke("deploy", lambda: "done") == "done"
    events = [e["event"] for e in trace.events]
    assert events == ["approval_granted", "tool_invoked", "tool_completed"]
    grant = next(e for e in trace.events if e["event"] == "approval_granted")
    assert grant["detail"]["via"] == "pre-grant"


def test_pregranted_approver_denies_unnamed_actions() -> None:
    gate, trace = _gate(PreGrantedApprover(set()))
    with pytest.raises(ApprovalError, match="requires human approval"):
        gate.invoke("deploy", lambda: "done")
    assert trace.events[-1]["event"] == "approval_denied"
    assert trace.events[-1]["detail"]["via"] == "pre-grant"


def test_callback_approver_can_return_bool_or_decision() -> None:
    gate, _ = _gate(CallbackApprover(lambda a, ctx: True))
    assert gate.invoke("deploy", lambda: "ok") == "ok"
    gate2, trace2 = _gate(
        CallbackApprover(lambda a, ctx: ApprovalDecision(False, "callback", "nope"))
    )
    with pytest.raises(ApprovalError):
        gate2.invoke("deploy", lambda: "ok")
    assert trace2.events[-1]["detail"]["reason"] == "nope"


def test_tty_approver_reads_yes() -> None:
    answers = iter(["y"])
    approver = TTYApprover(input_fn=lambda prompt: next(answers), output=lambda m: None)
    gate, trace = _gate(approver)
    assert gate.invoke("deploy", lambda: "deployed") == "deployed"
    assert trace.events[0]["event"] == "approval_granted"
    assert trace.events[0]["detail"]["via"] == "tty"


def test_tty_approver_reads_no() -> None:
    approver = TTYApprover(input_fn=lambda prompt: "n", output=lambda m: None)
    gate, _ = _gate(approver)
    with pytest.raises(ApprovalError):
        gate.invoke("deploy", lambda: "deployed")


def test_webhook_approver_uses_transport() -> None:
    calls = []

    def transport(url, payload):
        calls.append((url, payload))
        return {"approved": True, "note": "approved by oncall"}

    approver = WebhookApprover("https://approvals.example/hook", transport=transport)
    gate, trace = _gate(approver)
    assert gate.invoke("deploy", lambda: "deployed") == "deployed"
    assert calls[0][0] == "https://approvals.example/hook"
    assert calls[0][1]["action"] == "deploy"
    grant = trace.events[0]
    assert grant["detail"]["via"] == "webhook"
    assert grant["detail"]["note"] == "approved by oncall"


def test_webhook_denial_blocks() -> None:
    approver = WebhookApprover("u", transport=lambda url, p: {"approved": False})
    gate, _ = _gate(approver)
    with pytest.raises(ApprovalError):
        gate.invoke("deploy", lambda: "x")


def test_runtime_uses_approver_for_gated_evidence_tool() -> None:
    # A goal that requires evidence served by an approval-gated tool: the
    # approver decides whether the tool runs.
    src = (
        "goal G {\n  objective:\n    x\n"
        "  evidence:\n    require logs\n"
        "  actions:\n    require_approval read_logs\n"
        "  output:\n    answer\n}\n"
    )
    plan = compile_goal(parse_source(src).goals[0]).to_dict()
    # Approved: the real tool runs (origin tool:read_logs).
    approved = GoalRuntime(
        plan, printer=None, workspace="examples/workspace",
        approver=PreGrantedApprover({"read_logs"}),
    ).run()
    assert approved["evidence"][0]["origin"] == "tool:read_logs"
    # Denied: falls back to simulated evidence, denial is traced.
    denied = GoalRuntime(
        plan, printer=None, workspace="examples/workspace",
        approver=PreGrantedApprover(set()),
    ).run()
    assert denied["evidence"][0]["origin"] == "simulated"
    assert any(e["event"] == "approval_denied" for e in denied["trace"])
