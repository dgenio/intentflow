"""Conformance sweep for the example gallery (see #30, #146).

Every gallery example lives in its own directory with its own workspace. This
sweep parses, validates (no errors), compiles, runs each goal/pipeline against
that workspace on the simulate backend, and audits the witness — so a gallery
example can never drift into a non-conformant or invalid state.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from intentflow.analyzer import analyze_program, errors_in
from intentflow.auditor import audit_document
from intentflow.backends import SimulatedCognition
from intentflow.compiler import compile_program
from intentflow.parser import parse_file
from intentflow.runtime import GoalRuntime, run_pipeline

GALLERY = Path(__file__).resolve().parent.parent / "examples" / "gallery"
EXAMPLES = sorted(GALLERY.glob("*/program.iflow"))


def test_gallery_is_not_empty() -> None:
    assert EXAMPLES, "expected at least one gallery example"


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.parent.name)
def test_gallery_example_validates_runs_and_audits(path: Path) -> None:
    workspace = str(path.parent / "workspace")
    program = parse_file(str(path))

    assert errors_in(analyze_program(program)) == []

    document = compile_program(program)
    if document["pipelines"]:
        for pipeline in document["pipelines"]:
            result = run_pipeline(
                document,
                pipeline["name"],
                backend=SimulatedCognition(),
                printer=None,
                workspace=workspace,
            )
            assert audit_document(document, result)["conformant"] is True
    else:
        for plan in document["goals"]:
            result = GoalRuntime(
                plan,
                backend=SimulatedCognition(),
                printer=None,
                workspace=workspace,
            ).run()
            assert audit_document(document, result)["conformant"] is True


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.parent.name)
def test_gallery_example_is_canonically_formatted(path: Path) -> None:
    from intentflow.formatter import format_source

    text = path.read_text()
    assert format_source(text) == text


def test_gallery_has_a_readme_index() -> None:
    assert (GALLERY / "README.md").exists()
    for path in EXAMPLES:
        assert (path.parent / "README.md").exists(), path.parent.name
