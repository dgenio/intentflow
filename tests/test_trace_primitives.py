"""Trace-primitive module tests (issue #67).

The trace primitives now live in :mod:`intentflow.trace`; these tests lock the
properties that the extraction must preserve — a stable hash chain, a single
shared event vocabulary, and the layering rule that the independent verifier
(the auditor) never imports from the runtime it audits.
"""

from __future__ import annotations

import ast
from pathlib import Path

from intentflow.auditor import audit_document
from intentflow.compiler import EXECUTION_PHASES, compile_program
from intentflow.parser import parse_file
from intentflow.runtime import GoalRuntime
from intentflow.trace import CANONICAL_PHASES, KNOWN_EVENTS, Event, Trace

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = "examples/production_diagnosis.iflow"


def _run_example():
    document = compile_program(parse_file(EXAMPLE))
    result = GoalRuntime(
        document["goals"][0], printer=None, workspace="examples/workspace"
    ).run()
    return document, result


def test_canonical_phases_is_the_single_source_for_execution_phases() -> None:
    # The compiler re-exports the trace module's canonical phase order.
    assert EXECUTION_PHASES is CANONICAL_PHASES


def test_every_recorded_event_is_in_the_known_vocabulary() -> None:
    _, result = _run_example()
    recorded = {event["event"] for event in result["trace"]}
    assert recorded, "the example run recorded no events"
    unknown = recorded - KNOWN_EVENTS
    assert unknown == set(), f"events recorded but absent from KNOWN_EVENTS: {unknown}"


def test_event_constants_match_their_string_values() -> None:
    # The constants are bare strings so recorded events stay JSON/hash stable.
    assert Event.TOOL_INVOKED == "tool_invoked"
    assert Event.PHASE_STARTED == "phase_started"
    assert Event.RUN_COMPLETED == "run_completed"
    assert all(isinstance(name, str) for name in KNOWN_EVENTS)


def test_trace_chain_is_intact_and_audits_conformant() -> None:
    document, result = _run_example()
    report = audit_document(document, result)
    assert report["conformant"] is True


def test_bare_trace_records_a_hash_chain() -> None:
    trace = Trace()
    trace.record("parse", Event.PHASE_STARTED, {"title": "t"})
    trace.record("trace", Event.RUN_COMPLETED, {"status": "completed"})
    events = trace.to_list()
    assert events[0]["prev_hash"] == "0" * 64
    assert events[1]["prev_hash"] == events[0]["hash"]
    seal = trace.seal()
    assert seal["length"] == 2
    assert seal["root"] == events[1]["hash"]
    assert seal["signatures"] == []


def test_auditor_does_not_import_from_runtime() -> None:
    # The independent verifier must not depend on the runtime it verifies.
    source = (ROOT / "intentflow" / "auditor.py").read_text()
    tree = ast.parse(source)
    runtime_imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "intentflow.runtime"
    ]
    assert runtime_imports == []
