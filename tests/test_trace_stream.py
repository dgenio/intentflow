"""Streamed JSONL trace tests (issue #82).

An opt-in sink appends each event to a JSONL file as it is recorded, so a hard
crash leaves a chain-verifiable prefix and long runs need not hold the whole
trace in memory to persist it. These tests cover the sink itself, prefix vs
complete verification, fail-closed behavior, a crash mid-run (via subprocess),
and that the flag changes nothing when absent.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from intentflow.auditor import verify_trace_stream
from intentflow.compiler import compile_program
from intentflow.parser import parse_file
from intentflow.runtime import GoalRuntime
from intentflow.trace import Event, Trace, TraceSinkError

ROOT = Path(__file__).resolve().parents[1]
TRIAGE = "examples/opensource_triage.iflow"


def _run_to_stream(path: Path) -> dict:
    document = compile_program(parse_file(TRIAGE))
    with open(path, "w", encoding="utf-8") as sink:
        result = GoalRuntime(document["goals"][0], printer=None, trace_sink=sink).run()
    return result


def test_streamed_events_match_the_in_memory_trace(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    result = _run_to_stream(path)
    streamed = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    # The stream is exactly the in-memory trace, event for event.
    assert streamed == result["trace"]


def test_complete_stream_verifies(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    _run_to_stream(path)
    report = verify_trace_stream(path.read_text())
    assert report["chain_ok"] is True
    assert report["complete"] is True
    assert report["violations"] == []


def test_truncated_prefix_still_verifies_but_is_incomplete(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    _run_to_stream(path)
    lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    # Drop the tail (including the terminal run_completed event).
    prefix = lines[: len(lines) // 2]
    report = verify_trace_stream(prefix)
    assert report["chain_ok"] is True  # a prefix of a chain is still a valid chain
    assert report["complete"] is False
    assert report["events"] == len(prefix)


def test_tampered_stream_line_breaks_the_chain(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    _run_to_stream(path)
    lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    event = json.loads(lines[3])
    event["detail"] = {"forged": True}
    lines[3] = json.dumps(event)
    report = verify_trace_stream(lines)
    assert report["chain_ok"] is False
    assert any(v["code"] == "T3" for v in report["violations"])


def test_sink_failure_fails_closed() -> None:
    class _BrokenSink:
        def write(self, data: str):
            raise OSError("disk full")

        def flush(self):
            pass

    trace = Trace(sink=_BrokenSink())
    with pytest.raises(TraceSinkError):
        trace.record("parse", Event.PHASE_STARTED, {"title": "t"})


def test_crash_mid_run_leaves_a_verifiable_prefix(tmp_path: Path) -> None:
    # Drive a run in a subprocess that hard-exits partway, then confirm the
    # streamed file is a chain-verifiable prefix (not a complete run).
    path = tmp_path / "trace.jsonl"
    script = (
        "import os\n"
        "from intentflow.compiler import compile_program\n"
        "from intentflow.parser import parse_file\n"
        "from intentflow.trace import Trace, Event\n"
        "from intentflow.runtime import GoalRuntime\n"
        f"doc = compile_program(parse_file({TRIAGE!r}))\n"
        f"sink = open({str(path)!r}, 'w', encoding='utf-8')\n"
        "orig = Trace.record\n"
        "count = {'n': 0}\n"
        "def patched(self, phase, event, detail=None):\n"
        "    orig(self, phase, event, detail)\n"
        "    count['n'] += 1\n"
        "    if count['n'] == 5:\n"
        "        os._exit(137)  # hard kill: no cleanup, no run_completed\n"
        "Trace.record = patched\n"
        "GoalRuntime(doc['goals'][0], printer=None, trace_sink=sink).run()\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script], cwd=str(ROOT), capture_output=True
    )
    assert proc.returncode == 137
    report = verify_trace_stream(path.read_text())
    assert report["events"] == 5
    assert report["chain_ok"] is True
    assert report["complete"] is False


def test_no_sink_leaves_run_unchanged(tmp_path: Path) -> None:
    # A run without a sink behaves exactly as before (same trace, same id).
    document = compile_program(parse_file(TRIAGE))
    a = GoalRuntime(document["goals"][0], printer=None).run()
    path = tmp_path / "trace.jsonl"
    b = _run_to_stream(path)
    assert a["trace_id"] == b["trace_id"]
    assert a["trace"] == b["trace"]
