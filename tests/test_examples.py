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
EXPECTED_INFO_CODES_BY_EXAMPLE = {
    "code_review.iflow": {"IFLOW021"},
    "opensource_triage.iflow": {"IFLOW021"},
    "research_synthesis.iflow": {"IFLOW017"},
}


def _assert_no_simulated_required_evidence(result: dict, plan: dict) -> None:
    if result["status"] == "blocked":
        return

    required_sources = {
        source for source in plan["evidence_policy"]["required"] if "." not in source
    }
    collected_by_source = {
        item["source"]: item
        for item in result["evidence"]
        if item["source"] in required_sources
    }
    assert set(collected_by_source) == required_sources
    assert {
        source
        for source, item in collected_by_source.items()
        if item["origin"] == "simulated"
    } == set()


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda path: path.name)
def test_examples_parse_validate_lint_run_and_audit(path: Path) -> None:
    program = parse_file(str(path))

    diagnostics = analyze_program(program)
    assert errors_in(diagnostics) == []
    lint_findings = lint_program(program)
    warning_codes = {
        finding.rule_id for finding in lint_findings if finding.level == "warning"
    }
    info_codes = {finding.rule_id for finding in lint_findings if finding.level == "info"}
    assert warning_codes == EXPECTED_WARNING_CODES_BY_EXAMPLE.get(path.name, set())
    assert info_codes == EXPECTED_INFO_CODES_BY_EXAMPLE.get(path.name, set())
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
