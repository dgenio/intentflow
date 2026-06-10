"""Pipeline tests: parsing, static evidence-chain checking, and execution."""

from __future__ import annotations

import pytest

from intentflow.compiler import CompileError, compile_program
from intentflow.parser import ParseError, parse_file, parse_source
from intentflow.runtime import run_pipeline

GOAL_A = (
    "goal A {\n  objective:\n    find x\n  evidence:\n    require logs\n"
    "  output:\n    root_cause: string\n}\n"
)
GOAL_B_TEMPLATE = (
    "goal B {{\n  objective:\n    fix x\n  evidence:\n    require {req}\n"
    "  output:\n    recommended_fix: string\n}}\n"
)


def test_parse_pipeline_block() -> None:
    source = GOAL_A + GOAL_B_TEMPLATE.format(req="A.root_cause")
    source += "pipeline P {\n  stage A\n  stage B\n}\n"
    program = parse_source(source)
    assert program.pipeline("P") is not None
    assert [s.goal_name for s in program.pipeline("P").stages] == ["A", "B"]


def test_invalid_pipeline_statement_is_a_parse_error() -> None:
    with pytest.raises(ParseError, match="expected 'stage GoalName'"):
        parse_source(GOAL_A + "pipeline P {\n  run A\n}\n")


def test_empty_pipeline_is_a_parse_error() -> None:
    with pytest.raises(ParseError, match="has no stages"):
        parse_source(GOAL_A + "pipeline P {\n}\n")


def test_pipeline_unknown_goal_is_a_compile_error() -> None:
    program = parse_source(GOAL_A + "pipeline P {\n  stage Missing\n}\n")
    with pytest.raises(CompileError, match="unknown goal 'Missing'"):
        compile_program(program)


def test_pipeline_missing_output_field_is_a_compile_error() -> None:
    source = GOAL_A + GOAL_B_TEMPLATE.format(req="A.nonexistent_field")
    source += "pipeline P {\n  stage A\n  stage B\n}\n"
    with pytest.raises(CompileError, match="does not declare output 'nonexistent_field'"):
        compile_program(parse_source(source))


def test_pipeline_wrong_stage_order_is_a_compile_error() -> None:
    source = GOAL_A + GOAL_B_TEMPLATE.format(req="A.root_cause")
    source += "pipeline P {\n  stage B\n  stage A\n}\n"
    with pytest.raises(CompileError, match="does not run before it"):
        compile_program(parse_source(source))


def test_pipelines_compile_into_the_document() -> None:
    document = compile_program(parse_file("examples/incident_pipeline.iflow"))
    assert document["pipelines"] == [
        {"name": "IncidentResponse", "stages": ["DiagnoseIncident", "ProposeRemediation"]}
    ]


def test_pipeline_run_feeds_outputs_forward_as_evidence() -> None:
    document = compile_program(parse_file("examples/incident_pipeline.iflow"))
    result = run_pipeline(document, "IncidentResponse", printer=None)
    assert result["status"] == "completed"
    assert [s["goal"] for s in result["stages"]] == [
        "DiagnoseIncident",
        "ProposeRemediation",
    ]
    stage2_evidence = {
        e["source"]: e for e in result["stages"][1]["evidence"]
    }
    seeded = stage2_evidence["DiagnoseIncident.root_cause"]
    assert seeded["origin"] == "pipeline:DiagnoseIncident"
    # The seeded evidence carries the actual upstream output value.
    assert seeded["summary"] == str(result["stages"][0]["outputs"]["root_cause"])


def test_pipeline_combined_trace_tags_stages() -> None:
    document = compile_program(parse_file("examples/incident_pipeline.iflow"))
    result = run_pipeline(document, "IncidentResponse", printer=None)
    stages_in_trace = {event["stage"] for event in result["trace"]}
    assert stages_in_trace == {"DiagnoseIncident", "ProposeRemediation"}


def test_pipeline_stops_at_first_non_completed_stage() -> None:
    # Stage A escalates (confidence 0.676 < 0.9): stage B must not run.
    source = (
        "goal A {\n  objective:\n    find x\n  evidence:\n    require logs\n"
        "  uncertainty:\n    if confidence < 0.9 ask_human\n"
        "  output:\n    root_cause: string\n}\n"
        + GOAL_B_TEMPLATE.format(req="A.root_cause")
        + "pipeline P {\n  stage A\n  stage B\n}\n"
    )
    document = compile_program(parse_source(source))
    result = run_pipeline(document, "P", printer=None)
    assert result["status"] == "needs_human"
    assert [s["goal"] for s in result["stages"]] == ["A"]
