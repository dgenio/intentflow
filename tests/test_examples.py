"""Conformance smoke tests for shipped examples."""

from __future__ import annotations

from pathlib import Path

import pytest

from intentflow.analyzer import analyze_program, errors_in
from intentflow.auditor import audit_document
from intentflow.backends import SimulatedCognition
from intentflow.compiler import compile_program
from intentflow.formatter import format_source
from intentflow.linter import lint_program
from intentflow.parser import parse_file
from intentflow.runtime import GoalRuntime, run_pipeline


EXAMPLES = sorted(Path("examples").glob("*.iflow"))
WORKSPACE = "examples/workspace"
EXPECTED_WARNING_CODES_BY_EXAMPLE = {
    "high_risk_deploy.iflow": {"IFLOW010"},
    "research_synthesis.iflow": {"IFLOW009"},
}


def _assert_no_simulated_required_evidence(result: dict, plan: dict) -> None:
    required_sources = {
        source for source in plan["evidence_policy"]["required"] if "." not in source
    }
    simulated_required = [
        item["source"]
        for item in result["evidence"]
        if item["source"] in required_sources and item["origin"] == "simulated"
    ]
    assert simulated_required == []


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda path: path.name)
def test_examples_parse_validate_lint_run_and_audit(path: Path) -> None:
    program = parse_file(str(path))

    diagnostics = analyze_program(program)
    assert errors_in(diagnostics) == []
    warning_codes = {
        finding.rule_id for finding in lint_program(program) if finding.level == "warning"
    }
    assert warning_codes == EXPECTED_WARNING_CODES_BY_EXAMPLE.get(path.name, set())
    assert format_source(path.read_text()) == path.read_text()

    document = compile_program(program)
    plans = {plan["goal"]: plan for plan in document["goals"]}

    if document["pipelines"]:
        for pipeline in document["pipelines"]:
            result = run_pipeline(
                document,
                pipeline["name"],
                backend=SimulatedCognition(),
                printer=None,
                workspace=WORKSPACE,
            )
            assert audit_document(document, result)["conformant"] is True
            for stage in result["stages"]:
                _assert_no_simulated_required_evidence(stage, plans[stage["goal"]])
    else:
        for plan in document["goals"]:
            result = GoalRuntime(
                plan,
                backend=SimulatedCognition(),
                printer=None,
                workspace=WORKSPACE,
            ).run()
            assert audit_document(document, result)["conformant"] is True
            _assert_no_simulated_required_evidence(result, plan)
