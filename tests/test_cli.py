"""CLI tests: every command, exit codes, JSON modes, and end-to-end flows."""

from __future__ import annotations

import json

import pytest

from intentflow.cli import main

TRIAGE = "examples/opensource_triage.iflow"


# -- parse / validate / lint ---------------------------------------------------


def test_parse_prints_ast(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["parse", "examples/code_review.iflow"]) == 0
    ast = json.loads(capsys.readouterr().out)
    assert ast["goals"][0]["name"] == "ReviewPullRequest"


def test_validate_ok(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", TRIAGE]) == 0
    assert "OK" in capsys.readouterr().out


def test_validate_reports_errors_with_codes(tmp_path, capsys) -> None:
    bad = tmp_path / "bad.iflow"
    bad.write_text("goal G {\n  output:\n    result: string\n}\n")
    assert main(["validate", str(bad)]) == 1
    out = capsys.readouterr().out
    assert "IFLOW001" in out and "no objective" in out


def test_validate_json_output(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", TRIAGE, "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert report["error_count"] == 0
    assert all({"code", "severity", "message", "line"} <= set(d)
               for d in report["diagnostics"])


def test_validate_json_reports_errors(tmp_path, capsys) -> None:
    bad = tmp_path / "bad.iflow"
    bad.write_text("goal G {\n  output:\n    result: string\n}\n")
    assert main(["validate", str(bad), "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False
    assert any(d["code"] == "IFLOW001" for d in report["diagnostics"])


def test_lint_prints_advisories(capsys) -> None:
    assert main(["lint", "examples/research_synthesis.iflow"]) == 0
    out = capsys.readouterr().out
    assert "IFLOW009" in out


def test_lint_strict_fails_on_warnings(capsys) -> None:
    assert main(["lint", "examples/research_synthesis.iflow", "--strict"]) == 1


def test_parse_error_exits_2(tmp_path, capsys) -> None:
    bad = tmp_path / "bad.iflow"
    bad.write_text("not a goal\n")
    with pytest.raises(SystemExit) as exc_info:
        main(["parse", str(bad)])
    assert exc_info.value.code == 2
    assert "parse error" in capsys.readouterr().err


# -- compile -------------------------------------------------------------------


def test_compile_prints_json(capsys) -> None:
    assert main(["compile", TRIAGE]) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["goals"][0]["goal"] == "TriageGitHubIssue"
    assert document["plan_version"] == "0.2"
    assert document["source_hash"]


def test_compile_out_writes_file(tmp_path, capsys) -> None:
    out_file = tmp_path / "plan.json"
    assert main(["compile", TRIAGE, "--out", str(out_file)]) == 0
    assert "plan written to" in capsys.readouterr().out
    document = json.loads(out_file.read_text())
    assert document["goals"][0]["risk_profile"]["level"] == "medium"


def test_compile_invalid_file_fails(tmp_path, capsys) -> None:
    bad = tmp_path / "bad.iflow"
    bad.write_text("goal G {\n  output:\n    result: string\n}\n")
    with pytest.raises(SystemExit) as exc_info:
        main(["compile", str(bad)])
    assert exc_info.value.code == 1
    assert "IFLOW001" in capsys.readouterr().err


# -- run -----------------------------------------------------------------------


def test_run_defaults_to_simulate_and_completes(capsys) -> None:
    assert main(["run", TRIAGE]) == 0
    out = capsys.readouterr().out
    assert "status:             completed" in out
    assert "backend:            simulate" in out


def test_run_json_emits_full_result(capsys) -> None:
    assert main(["run", TRIAGE, "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "completed"
    assert result["trace"]
    assert result["summary"]["verification_status"] == "passed"


def test_run_verbose_narrates_phases(capsys) -> None:
    assert main(["run", TRIAGE, "--verbose"]) == 0
    out = capsys.readouterr().out
    assert "phase: collect_evidence" in out
    assert "phase: verify_output" in out


def test_run_blocked_goal_exits_1(capsys) -> None:
    assert main(["run", "examples/high_risk_deploy.iflow"]) == 1
    assert "blocked" in capsys.readouterr().out


def test_run_invalid_file_reports_failed_validation(tmp_path, capsys) -> None:
    bad = tmp_path / "bad.iflow"
    bad.write_text("goal G {\n  output:\n    result: string\n}\n")
    assert main(["run", str(bad)]) == 1
    captured = capsys.readouterr()
    assert "failed_validation" in captured.out
    assert "IFLOW001" in captured.err


def test_run_named_goal(capsys) -> None:
    code = main(
        ["run", "examples/incident_pipeline.iflow", "--goal", "DiagnoseIncident"]
    )
    assert code == 0
    assert "DiagnoseIncident" in capsys.readouterr().out


def test_run_pipeline_flag(capsys) -> None:
    code = main(
        ["run", "examples/incident_pipeline.iflow", "--pipeline", "IncidentResponse"]
    )
    assert code == 0


def test_run_with_judge_flag(capsys) -> None:
    code = main(["run", TRIAGE, "--simulate", "--judge", "simulate", "--json"])
    assert code == 0
    result = json.loads(capsys.readouterr().out)
    judged = [c for c in result["verification"]["checks"]
              if c.get("judged_by") == "simulate-judge"]
    assert judged


def test_run_sign_trace_requires_key(monkeypatch, capsys) -> None:
    monkeypatch.delenv("IFLOW_TRACE_KEY", raising=False)
    assert main(["run", TRIAGE, "--simulate", "--sign-trace"]) == 1
    assert "IFLOW_TRACE_KEY" in capsys.readouterr().err


def test_run_replay_backend_requires_cassette(capsys) -> None:
    assert main(["run", TRIAGE, "--backend", "replay"]) == 1
    assert "cassette" in capsys.readouterr().err


# -- trace artifacts, replay, audit ---------------------------------------------


def test_run_trace_dir_writes_artifact(tmp_path, capsys) -> None:
    trace_dir = tmp_path / "traces"
    assert main(["run", TRIAGE, "--trace-dir", str(trace_dir)]) == 0
    artifacts = list(trace_dir.glob("*.json"))
    assert len(artifacts) == 1
    artifact = json.loads(artifacts[0].read_text())
    assert artifact["artifact"] == "intentflow-trace"
    assert artifact["backend"] == "simulate"
    assert artifact["status"] == "completed"
    assert artifact["plan_hash"] and artifact["source_hash"] and artifact["trace_id"]
    assert artifact["result"]["goal"] == "TriageGitHubIssue"
    assert artifact["result"]["trace"]


def test_replay_renders_trace_summary(tmp_path, capsys) -> None:
    trace_dir = tmp_path / "traces"
    main(["run", TRIAGE, "--trace-dir", str(trace_dir)])
    artifact = next(trace_dir.glob("*.json"))
    capsys.readouterr()  # discard the run output
    assert main(["replay", str(artifact)]) == 0
    out = capsys.readouterr().out
    assert "IntentFlow trace replay" in out
    assert "status:      completed" in out
    assert "collect_evidence" in out
    assert "V0 [PASS]" in out
    assert "trace chain:" in out


def test_replay_json_mode(tmp_path, capsys) -> None:
    trace_dir = tmp_path / "traces"
    main(["run", TRIAGE, "--trace-dir", str(trace_dir)])
    artifact = next(trace_dir.glob("*.json"))
    capsys.readouterr()
    assert main(["replay", str(artifact), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["result"]["status"] == "completed"


def test_replay_missing_file_exits_2(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["replay", "no/such/trace.json"])
    assert exc_info.value.code == 2


def test_run_sign_and_audit_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("IFLOW_TRACE_KEY", "clitestkey")
    trace_dir = tmp_path / "traces"
    assert main(
        ["run", TRIAGE, "--simulate", "--sign-trace", "--trace-dir", str(trace_dir)]
    ) == 0
    artifact = next(trace_dir.glob("*.json"))
    assert main(["audit", TRIAGE, str(artifact)]) == 0


# -- explain / inspect / format -------------------------------------------------


def test_explain_human_output(capsys) -> None:
    assert main(["explain", TRIAGE]) == 0
    out = capsys.readouterr().out
    assert "forbidden to close issue" in out
    assert "human approval" in out


def test_explain_json_output(capsys) -> None:
    assert main(["explain", TRIAGE, "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["goals"][0]["goal"] == "TriageGitHubIssue"


def test_inspect_human_output(capsys) -> None:
    assert main(["inspect", TRIAGE]) == 0
    out = capsys.readouterr().out
    assert "goal TriageGitHubIssue" in out
    assert "post_comment" in out  # approval-gated action surfaced
    assert "summary: string" in out  # typed output field surfaced


def test_inspect_json_output(capsys) -> None:
    assert main(["inspect", TRIAGE, "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    goal = report["goals"][0]
    assert goal["approval_gated_actions"] == ["post_comment"]
    assert goal["required_evidence"] == ["issue_body", "comments", "repo_context"]
    assert goal["optional_evidence"] == ["related_issues"]


def test_format_check_passes_on_canonical_file(capsys) -> None:
    assert main(["format", TRIAGE, "--check"]) == 0


def test_format_check_fails_on_messy_file(tmp_path, capsys) -> None:
    messy = tmp_path / "messy.iflow"
    messy.write_text("goal G {\nobjective:\nx\noutput:\nresult: string\n}\n")
    assert main(["format", str(messy), "--check"]) == 1
    assert "not formatted" in capsys.readouterr().err


def test_format_write_makes_check_pass(tmp_path) -> None:
    messy = tmp_path / "messy.iflow"
    messy.write_text("goal G {\nobjective:\nx\noutput:\nresult: string\n}\n")
    assert main(["format", str(messy), "--write"]) == 0
    assert main(["format", str(messy), "--check"]) == 0


# -- end to end ------------------------------------------------------------------


def test_triage_example_runs_and_audits() -> None:
    from intentflow.auditor import audit_document
    from intentflow.compiler import compile_program
    from intentflow.parser import parse_file
    from intentflow.runtime import GoalRuntime

    document = compile_program(parse_file(TRIAGE))
    result = GoalRuntime(document["goals"][0], printer=None).run()
    assert result["status"] == "completed"
    report = audit_document(document, result)
    assert report["conformant"] is True
