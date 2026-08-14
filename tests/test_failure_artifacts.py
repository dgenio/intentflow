from __future__ import annotations

from pathlib import Path

import pytest

from intentflow.auditor import audit_result
from intentflow.cli import _atomic_write_text
from intentflow.compiler import compile_goal
from intentflow.parser import parse_file
from intentflow.runtime import GoalRuntime, RunFailed


TRIAGE = "examples/opensource_triage.iflow"


def _plan() -> dict:
    program = parse_file(TRIAGE)
    return compile_goal(program.goals[0], program.source_name).to_dict()


class ExplodingRuntime(GoalRuntime):
    def _collect_evidence(self) -> None:
        self._phase("collect_evidence", "synthetic controlled failure")
        raise RuntimeError("tool handler exploded")


def test_caught_runtime_failure_carries_partial_result() -> None:
    runtime = ExplodingRuntime(_plan(), printer=None)

    with pytest.raises(RunFailed, match="collect_evidence") as caught:
        runtime.run()

    result = caught.value.result
    assert result["status"] == "failed"
    assert result["complete"] is False
    assert result["failure"]["type"] == "RuntimeError"
    assert result["failure"]["phase"] == "collect_evidence"
    assert result["failure"]["terminal_event_recorded"] is True
    assert result["trace"][-1]["event"] == "run_failed"
    assert result["trace_chain"]["root"] == result["trace"][-1]["hash"]
    assert result["failure_receipt"]["verdict"] == "failed-but-auditable"


def test_partial_failure_is_auditable_without_success_obligations() -> None:
    plan = _plan()
    runtime = ExplodingRuntime(plan, printer=None)
    with pytest.raises(RunFailed) as caught:
        runtime.run()

    report = audit_result(plan, caught.value.result)
    assert report["conformant"] is True
    assert report["violations"] == []


def test_atomic_write_replaces_complete_file(tmp_path: Path) -> None:
    target = tmp_path / "witness.json"
    target.write_text("old", encoding="utf-8")

    _atomic_write_text(target, '{"status":"failed"}')

    assert target.read_text(encoding="utf-8") == '{"status":"failed"}'
    assert not list(tmp_path.glob(".witness.json.*.tmp"))


def test_atomic_write_failure_preserves_previous_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "witness.json"
    target.write_text("old", encoding="utf-8")

    def fail_replace(src, dst):
        raise OSError("disk refused replace")

    monkeypatch.setattr("intentflow.cli.os.replace", fail_replace)
    with pytest.raises(OSError, match="disk refused replace"):
        _atomic_write_text(target, "new")

    assert target.read_text(encoding="utf-8") == "old"
    assert not list(tmp_path.glob(".witness.json.*.tmp"))
