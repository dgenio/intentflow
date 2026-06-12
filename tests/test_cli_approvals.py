"""CLI approval and trace-signing regression tests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from intentflow.cli import _build_approver, main
from intentflow.tools import PreGrantedApprover, TTYApprover, WebhookApprover


def _args(
    *,
    approve: list[str] | None = None,
    approve_interactive: bool = False,
    approve_webhook: str | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        approve=approve,
        approve_interactive=approve_interactive,
        approve_webhook=approve_webhook,
    )


@pytest.mark.parametrize(
    ("approve", "interactive", "webhook", "expected"),
    [
        (None, False, None, None),
        (["read_logs"], False, None, PreGrantedApprover),
        (None, True, None, TTYApprover),
        (["read_logs"], True, None, TTYApprover),
        (None, False, "https://approvals.example/hook", WebhookApprover),
        (["read_logs"], False, "https://approvals.example/hook", WebhookApprover),
        (None, True, "https://approvals.example/hook", WebhookApprover),
        (["read_logs"], True, "https://approvals.example/hook", WebhookApprover),
    ],
)
def test_build_approver_precedence_matrix(
    approve: list[str] | None,
    interactive: bool,
    webhook: str | None,
    expected: type | None,
) -> None:
    approver = _build_approver(
        _args(
            approve=approve,
            approve_interactive=interactive,
            approve_webhook=webhook,
        )
    )
    if expected is None:
        assert approver is None
    else:
        assert isinstance(approver, expected)


def test_approve_flags_accumulate_pregranted_actions() -> None:
    approver = _build_approver(_args(approve=["read_logs", "deploy_change"]))
    assert isinstance(approver, PreGrantedApprover)
    assert approver.request("read_logs", {}).approved is True
    assert approver.request("deploy_change", {}).approved is True
    assert approver.request("comment_on_issue", {}).approved is False


def _approval_goal(tmp_path: Path) -> Path:
    source = tmp_path / "approval.iflow"
    source.write_text(
        "goal ApprovalWiring {\n"
        "  objective:\n"
        "    prove CLI approval flags guard evidence collection\n"
        "  evidence:\n"
        "    require logs\n"
        "  actions:\n"
        "    require_approval read_logs\n"
        "  output:\n"
        "    result\n"
        "}\n"
    )
    return source


def _result_json(out: str) -> dict:
    body = out.split("=== final result ===", 1)[1].split("--- summary ---", 1)[0]
    return json.loads(body)


def test_cli_pregrant_allows_approval_gated_evidence_tool(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _approval_goal(tmp_path)
    assert main(
        [
            "run",
            str(source),
            "--simulate",
            "--workspace",
            "examples/workspace",
            "--approve",
            "read_logs",
        ]
    ) == 0
    result = _result_json(capsys.readouterr().out)
    assert result["evidence"][0]["origin"] == "tool:read_logs"
    assert any(
        event["event"] == "approval_granted"
        and event["detail"]["action"] == "read_logs"
        and event["detail"]["via"] == "pre-grant"
        for event in result["trace"]
    )


def test_cli_missing_approval_blocks_gated_tool_and_records_denial(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _approval_goal(tmp_path)
    assert main(
        [
            "run",
            str(source),
            "--simulate",
            "--workspace",
            "examples/workspace",
        ]
    ) == 0
    result = _result_json(capsys.readouterr().out)
    assert result["evidence"][0]["origin"] == "simulated"
    assert any(
        event["event"] == "approval_denied"
        and event["detail"]["action"] == "read_logs"
        for event in result["trace"]
    )


def test_cli_sign_trace_requires_env_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("IFLOW_TRACE_KEY", raising=False)
    source = _approval_goal(tmp_path)
    assert main(["run", str(source), "--simulate", "--sign-trace"]) == 1
    assert "IFLOW_TRACE_KEY" in capsys.readouterr().err


def test_cli_sign_trace_writes_trace_chain_signature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("IFLOW_TRACE_KEY", "cli-approval-test-key")
    source = _approval_goal(tmp_path)
    output = tmp_path / "result.json"
    assert main(
        [
            "run",
            str(source),
            "--simulate",
            "--sign-trace",
            "--trace-out",
            str(output),
        ]
    ) == 0
    capsys.readouterr()
    result = json.loads(output.read_text())
    assert result["trace_chain"]["signature"]
