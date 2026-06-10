"""Explain tests: the plain-English rendering of a program."""

from __future__ import annotations

from intentflow.explain import explain_program, render_explanation
from intentflow.parser import parse_file, parse_source


def _report(path: str = "examples/opensource_triage.iflow") -> dict:
    return explain_program(parse_file(path))


def test_explanation_covers_every_concern() -> None:
    goal = _report()["goals"][0]
    assert "triage" in goal["purpose"]
    assert any("issue body" in line for line in goal["evidence"])
    assert any("related issues" in line for line in goal["evidence"])
    assert any("read issue" in line for line in goal["allowed"])
    assert any("post comment" in line for line in goal["needs_approval"])
    assert any("close issue" in line for line in goal["forbidden"])
    assert any("0.65" in line for line in goal["verification"])
    assert any("ask a human" in line for line in goal["uncertainty"])
    assert any("refuse to act" in line for line in goal["uncertainty"])
    assert "proposed_labels: list[string]" in goal["promises"]


def test_rendered_explanation_is_readable_text() -> None:
    text = render_explanation(_report())
    assert "goal TriageGitHubIssue" in text
    assert "what it is forbidden to do" in text
    assert "what it promises to produce" in text


def test_explanation_calls_out_missing_governance() -> None:
    report = explain_program(
        parse_source("goal Bare {\n  objective:\n    wing it\n}\n")
    )
    goal = report["goals"][0]
    assert any("analyzer warns" in line for line in goal["evidence"])
    assert any("never escalate" in line for line in goal["uncertainty"])
    assert goal["promises"] == ["(no output promised)"]


def test_pipelines_are_explained() -> None:
    report = explain_program(parse_file("examples/incident_pipeline.iflow"))
    assert report["pipelines"][0]["name"] == "IncidentResponse"
    assert "DiagnoseIncident then ProposeRemediation" in (
        report["pipelines"][0]["explanation"]
    )
