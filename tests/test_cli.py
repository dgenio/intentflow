"""CLI smoke tests."""

from __future__ import annotations

import json

import pytest

from intentflow.cli import main


def test_compile_prints_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["compile", "examples/diagnose.iflow"]) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["plans"][0]["goal"] == "DiagnoseProductionIssue"


def test_parse_prints_ast(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["parse", "examples/code_review.iflow"]) == 0
    ast = json.loads(capsys.readouterr().out)
    assert ast["goals"][0]["name"] == "ReviewPullRequest"


def test_validate_ok(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", "examples/research_question.iflow"]) == 0
    assert "OK" in capsys.readouterr().out


def test_validate_reports_errors(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.iflow"
    bad.write_text("goal G {\n  output:\n    result\n}\n")
    assert main(["validate", str(bad)]) == 1
    assert "no objective" in capsys.readouterr().out


def test_run_defaults_to_simulate(capsys: pytest.CaptureFixture[str]) -> None:
    # No flags: the simulate backend is the default and the run completes.
    assert main(["run", "examples/diagnose.iflow"]) == 0
    out = capsys.readouterr().out
    assert "backend: simulate" in out
    assert "=== final result ===" in out


def _result_json(out: str) -> dict:
    body = out.split("=== final result ===", 1)[1].split("--- summary ---", 1)[0]
    return json.loads(body)


def test_run_simulate_emits_result_and_trace(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", "examples/diagnose.iflow", "--simulate"]) == 0
    out = capsys.readouterr().out
    assert "=== final result ===" in out
    result = _result_json(out)
    assert result["trace"]
    assert result["summary"]["verification_status"] in ("passed", "failed")


def test_parse_error_exits_2(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.iflow"
    bad.write_text("not a goal\n")
    with pytest.raises(SystemExit) as exc_info:
        main(["parse", str(bad)])
    assert exc_info.value.code == 2
    assert "parse error" in capsys.readouterr().err


def test_validate_json_output(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", "examples/diagnose.iflow", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert report["error_count"] == 0
    assert "diagnostics" in report


def test_validate_json_reports_errors(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.iflow"
    bad.write_text("goal G {\n  output:\n    result\n}\n")
    assert main(["validate", str(bad), "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False
    assert any("no objective" in d["message"] for d in report["diagnostics"])


def test_inspect_human_output(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["inspect", "examples/diagnose.iflow"]) == 0
    out = capsys.readouterr().out
    assert "goal DiagnoseProductionIssue" in out
    assert "deploy_change" in out  # approval-gated action surfaced
    assert "root_cause" in out  # output field surfaced


def test_inspect_json_output(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["inspect", "examples/diagnose.iflow", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    goal = report["goals"][0]
    assert goal["approval_gated_actions"] == ["deploy_change"]
    assert goal["required_evidence"] == ["logs", "config", "recent_commits"]


def test_format_check_passes_on_canonical_file(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["format", "examples/diagnose.iflow", "--check"]) == 0


def test_format_check_fails_on_messy_file(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    messy = tmp_path / "messy.iflow"
    messy.write_text("goal G {\nobjective:\nx\noutput:\nresult\n}\n")
    assert main(["format", str(messy), "--check"]) == 1
    assert "not formatted" in capsys.readouterr().err


def test_format_write_makes_check_pass(tmp_path) -> None:
    messy = tmp_path / "messy.iflow"
    messy.write_text("goal G {\nobjective:\nx\noutput:\nresult\n}\n")
    assert main(["format", str(messy), "--write"]) == 0
    assert main(["format", str(messy), "--check"]) == 0


def test_run_trace_dir_writes_artifact(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    trace_dir = tmp_path / "traces"
    code = main(
        ["run", "examples/diagnose.iflow", "--backend", "simulate",
         "--trace-dir", str(trace_dir)]
    )
    assert code == 0
    artifacts = list(trace_dir.glob("*.json"))
    assert len(artifacts) == 1
    artifact = json.loads(artifacts[0].read_text())
    assert artifact["backend"] == "simulate"
    assert artifact["plan_hash"]
    assert artifact["result"]["goal"] == "DiagnoseProductionIssue"
    assert artifact["result"]["trace"]


def test_run_backend_simulate_explicit(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", "examples/diagnose.iflow", "--backend", "simulate"]) == 0
    assert "backend: simulate" in capsys.readouterr().out


def test_triage_example_runs_and_audits(tmp_path) -> None:
    # End-to-end: compile, run in simulate, then independently audit.
    from intentflow.auditor import audit_document
    from intentflow.compiler import compile_program
    from intentflow.parser import parse_file
    from intentflow.runtime import GoalRuntime

    document = compile_program(parse_file("examples/triage_issue.iflow"))
    result = GoalRuntime(
        document["plans"][0], printer=None, workspace="examples/workspace"
    ).run()
    assert set(result["outputs"]) == {
        "summary",
        "likely_cause",
        "suggested_response",
        "proposed_labels",
    }
    report = audit_document(document, result)
    assert report["conformant"] is True
