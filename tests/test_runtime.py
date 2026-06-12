"""Runtime simulation tests: phases, uncertainty handling, verification,
escalation, and the auditable trace."""

from __future__ import annotations

import pytest

from intentflow.backends import Hypothesis, Proposal
from intentflow.compiler import compile_goal
from intentflow.parser import parse_file, parse_source
from intentflow.runtime import (
    _DISCRIMINATING_TEST_CONFIDENCE_BOOST,
    _DISCRIMINATING_TEST_CONFIDENCE_CEILING,
    _DISCRIMINATING_TEST_CONFIDENCE_FLOOR,
    _DISCRIMINATING_TEST_CONFIDENCE_PENALTY,
    _DISCRIMINATING_TEST_CONFIDENCE_PRECISION,
    SimulationRuntime,
)


class _FixedBackend:
    name = "fixed"

    def __init__(self, confidences: list[float]) -> None:
        self._confidences = confidences

    def propose(self, plan: dict, evidence: list[dict]) -> Proposal:
        return Proposal(
            hypotheses=[
                Hypothesis(
                    hypothesis_id=f"H{i}",
                    statement=f"hypothesis {i}",
                    raw_confidence=confidence,
                    confidence=confidence,
                    citations=["E1"],
                )
                for i, confidence in enumerate(self._confidences, start=1)
            ],
            proposed_fix="Rollback: revert to the previous known-good state.",
        )


def _run_example(name: str) -> dict:
    program = parse_file(f"examples/{name}.iflow")
    plan = compile_goal(program.goals[0], program.source_name).to_dict()
    return SimulationRuntime(plan, printer=None).run()


def _run_confidences(
    confidences: list[float], uncertainty_policy: list[dict] | None = None
) -> SimulationRuntime:
    source = (
        "goal RuntimeHeuristics {\n"
        "  objective:\n    pin runtime heuristic constants\n"
        "  evidence:\n    require logs\n"
        "  uncertainty:\n    if competing_hypotheses remain run_discriminating_test\n"
        "  output:\n    answer\n"
        "}\n"
    )
    program = parse_source(source)
    plan = compile_goal(program.goals[0]).to_dict()
    plan["calibration"] = {}
    if uncertainty_policy is not None:
        plan["uncertainty_policy"] = uncertainty_policy
    runtime = SimulationRuntime(plan, backend=_FixedBackend(confidences), printer=None)
    runtime.run()
    return runtime


def _run_competing_confidences(confidences: list[float]) -> SimulationRuntime:
    return _run_confidences(confidences)


def _run_forced_discriminating_test(confidences: list[float]) -> SimulationRuntime:
    return _run_confidences(
        confidences,
        uncertainty_policy=[
            {
                "kind": "threshold",
                "metric": "confidence",
                "op": ">",
                "threshold": 0.0,
                "condition": "confidence > 0.0",
                "action": "run_discriminating_test",
            }
        ],
    )


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
    assert {
        "init",
        "context",
        "evidence",
        "actions",
        "model",
        "uncertainty",
        "verify",
        "output",
        "done",
    } <= phases
    seqs = [event["seq"] for event in diagnose_result["trace"]]
    assert seqs == sorted(seqs)  # append-only, ordered


def test_evidence_is_collected_for_required_sources(diagnose_result: dict) -> None:
    sources = [e["source"] for e in diagnose_result["evidence"]]
    assert sources == ["logs", "config", "recent_commits"]
    assert all(e["id"].startswith("E") for e in diagnose_result["evidence"])


def test_confidence_is_calibrated_before_rules_fire(diagnose_result: dict) -> None:
    top = diagnose_result["hypotheses"][0]
    assert top["raw_confidence"] == 0.68
    # shrinkage toward 0.5 with factor 0.8 (then boosted by the
    # discriminating test, which the next tests cover)
    assert top["confidence"] != top["raw_confidence"]


def test_low_confidence_triggers_human_escalation(diagnose_result: dict) -> None:
    # Mock raw 0.68 calibrates to 0.644, below the declared 0.7 threshold.
    assert diagnose_result["escalations"], "expected ask_human escalation"
    assert "threshold" in diagnose_result["escalations"][0]["question"]
    events = [e["event"] for e in diagnose_result["trace"]]
    assert "human_escalation" in events


def test_competing_hypotheses_trigger_discriminating_test(
    diagnose_result: dict,
) -> None:
    events = [e["event"] for e in diagnose_result["trace"]]
    assert "discriminating_test" in events
    # The test separates the top two hypotheses, raising the winner.
    top = diagnose_result["hypotheses"][0]
    assert top["confidence"] > 0.7


def test_discriminating_test_uses_named_adjustment_magnitudes() -> None:
    runtime = _run_competing_confidences([0.6, 0.55])
    by_id = {hyp.hypothesis_id: hyp for hyp in runtime.hypotheses}
    assert by_id["H1"].confidence == round(
        0.6 + _DISCRIMINATING_TEST_CONFIDENCE_BOOST,
        _DISCRIMINATING_TEST_CONFIDENCE_PRECISION,
    )
    assert by_id["H2"].confidence == round(
        0.55 - _DISCRIMINATING_TEST_CONFIDENCE_PENALTY,
        _DISCRIMINATING_TEST_CONFIDENCE_PRECISION,
    )
    assert sum(e["event"] == "discriminating_test" for e in runtime.trace.events) == 1


def test_discriminating_test_clamps_confidence_ceiling_and_floor() -> None:
    runtime = _run_forced_discriminating_test([0.9, 0.08])
    by_id = {hyp.hypothesis_id: hyp for hyp in runtime.hypotheses}
    assert by_id["H1"].confidence == _DISCRIMINATING_TEST_CONFIDENCE_CEILING
    assert by_id["H2"].confidence == _DISCRIMINATING_TEST_CONFIDENCE_FLOOR


def test_discriminating_test_preserves_rounding_precision() -> None:
    runtime = _run_competing_confidences([0.60006, 0.55006])
    by_id = {hyp.hypothesis_id: hyp for hyp in runtime.hypotheses}
    assert by_id["H1"].confidence == 0.7801
    assert by_id["H2"].confidence == 0.4501


def test_discriminating_test_skips_when_fewer_than_two_hypotheses() -> None:
    runtime = _run_forced_discriminating_test([0.6])
    assert runtime.hypotheses[0].confidence == 0.6
    assert not any(e["event"] == "discriminating_test" for e in runtime.trace.events)


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
    recorded = [e for e in result["trace"] if e["event"] == "rule_not_simulated"]
    assert any("conflicting_sources" in e["detail"]["condition"] for e in recorded)


def test_judged_verification_is_skipped_not_passed() -> None:
    result = _run_example("research_question")
    by_rule = {c["rule"]: c for c in result["verification"]["checks"]}
    judged = by_rule["conflicting sources must be reported not hidden"]
    assert judged["mode"] == "judged"
    assert judged["status"] == "skipped"


def test_distrusted_sources_trace_order_is_deterministic() -> None:
    source = (
        "goal G {\n"
        "  objective:\n    x\n"
        "  evidence:\n    require logs\n    distrust b_source\n    distrust a_source\n"
        "  output:\n    answer\n"
        "}\n"
    )
    program = parse_source(source)
    plan = compile_goal(program.goals[0]).to_dict()
    result = SimulationRuntime(plan, printer=None).run()
    noted = [
        e["detail"]["source"]
        for e in result["trace"]
        if e["event"] == "source_distrusted"
    ]
    assert noted == ["b_source", "a_source"]  # declaration order, not set order


def test_runtime_is_deterministic() -> None:
    first = _run_example("diagnose")
    second = _run_example("diagnose")
    assert first == second
