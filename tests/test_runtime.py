"""Runtime simulation tests: phases, uncertainty handling, verification,
escalation, and the auditable trace."""

from __future__ import annotations

import pytest

from intentflow.compiler import compile_goal
from intentflow.parser import parse_file, parse_source
from intentflow.runtime import SimulationRuntime


def _run_example(name: str) -> dict:
    program = parse_file(f"examples/{name}.iflow")
    plan = compile_goal(program.goals[0], program.source_name).to_dict()
    return SimulationRuntime(plan, printer=None).run()


@pytest.fixture()
def diagnose_result() -> dict:
    return _run_example("diagnose")


def test_simulation_completes_with_structured_outputs(diagnose_result: dict) -> None:
    assert diagnose_result["status"] == "completed"
    assert set(diagnose_result["outputs"]) == {
        "root_cause",
        "confidence",
        "recommended_fix",
        "risk",
    }
    assert 0.0 <= diagnose_result["outputs"]["confidence"] <= 1.0


def test_trace_covers_all_phases(diagnose_result: dict) -> None:
    phases = {event["phase"] for event in diagnose_result["trace"]}
    assert {"init", "context", "evidence", "actions", "model",
            "uncertainty", "verify", "output", "done"} <= phases
    seqs = [event["seq"] for event in diagnose_result["trace"]]
    assert seqs == sorted(seqs)  # append-only, ordered


def test_evidence_is_collected_for_required_sources(diagnose_result: dict) -> None:
    sources = [e["source"] for e in diagnose_result["evidence"]]
    assert sources == ["logs", "config", "recent_commits"]
    assert all(e["id"].startswith("E") for e in diagnose_result["evidence"])


def test_low_confidence_triggers_human_escalation(diagnose_result: dict) -> None:
    # Mock top confidence starts at 0.68, below the declared 0.7 threshold.
    assert diagnose_result["escalations"], "expected ask_human escalation"
    assert "threshold" in diagnose_result["escalations"][0]["question"]
    events = [e["event"] for e in diagnose_result["trace"]]
    assert "human_escalation" in events


def test_competing_hypotheses_trigger_discriminating_test(diagnose_result: dict) -> None:
    events = [e["event"] for e in diagnose_result["trace"]]
    assert "discriminating_test" in events
    # The test separates the top two hypotheses, raising the winner.
    top = diagnose_result["hypotheses"][0]
    assert top["confidence"] > 0.7


def test_verification_checks_citations_and_rollback(diagnose_result: dict) -> None:
    verification = diagnose_result["verification"]
    assert verification["passed"] is True
    statuses = {c["rule"]: c["status"] for c in verification["checks"]}
    assert statuses["each hypothesis must cite evidence"] == "pass"
    assert statuses["proposed fix must include rollback path"] == "pass"


def test_uncited_hypotheses_fail_citation_verification() -> None:
    # No evidence section: the mock hypothesis cannot cite anything.
    source = (
        "goal NoEvidence {\n"
        "  objective:\n    guess the answer\n"
        "  verify:\n    each claim must cite evidence\n"
        "  output:\n    answer\n"
        "}\n"
    )
    program = parse_source(source)
    plan = compile_goal(program.goals[0]).to_dict()
    result = SimulationRuntime(plan, printer=None).run()
    assert result["verification"]["passed"] is False
    assert result["verification"]["checks"][0]["status"] == "fail"


def test_approval_gated_actions_appear_in_trace(diagnose_result: dict) -> None:
    governance = [
        e for e in diagnose_result["trace"] if e["event"] == "governance_established"
    ]
    assert governance
    assert governance[0]["detail"]["approval_required"] == ["deploy_change"]


def test_symbolic_rule_without_simulator_is_recorded() -> None:
    result = _run_example("research_question")
    recorded = [
        e for e in result["trace"] if e["event"] == "rule_not_simulated"
    ]
    assert any("conflicting_sources" in e["detail"]["condition"] for e in recorded)


def test_runtime_is_deterministic() -> None:
    first = _run_example("diagnose")
    second = _run_example("diagnose")
    assert first == second
