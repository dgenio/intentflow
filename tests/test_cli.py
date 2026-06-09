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


def test_run_requires_simulate_flag(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", "examples/diagnose.iflow"]) == 1
    assert "--simulate" in capsys.readouterr().err


def test_run_simulate_emits_result_and_trace(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", "examples/diagnose.iflow", "--simulate"]) == 0
    out = capsys.readouterr().out
    assert "=== final result ===" in out
    result = json.loads(out.split("=== final result ===", 1)[1])
    assert result["trace"]


def test_parse_error_exits_2(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.iflow"
    bad.write_text("not a goal\n")
    with pytest.raises(SystemExit) as exc_info:
        main(["parse", str(bad)])
    assert exc_info.value.code == 2
    assert "parse error" in capsys.readouterr().err
