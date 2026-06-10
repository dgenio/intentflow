"""Formatter tests: indentation normalization, comment preservation, and
idempotence."""

from __future__ import annotations

from intentflow.formatter import format_file, format_source
from intentflow.parser import parse_source

MESSY = """\
goal   Demo {
objective:
do the thing


      evidence:
            require logs   # keep this comment
   distrust rumors
   output:
result
}
"""


def test_format_normalizes_indentation() -> None:
    formatted = format_source(MESSY)
    lines = formatted.splitlines()
    assert lines[0] == "goal Demo {"
    assert "  objective:" in lines
    assert "    do the thing" in lines
    assert "  evidence:" in lines
    assert "    require logs   # keep this comment" in lines
    assert lines[-1] == "}"


def test_format_is_idempotent() -> None:
    once = format_source(MESSY)
    twice = format_source(once)
    assert once == twice


def test_format_preserves_meaning() -> None:
    # The reformatted source must parse to the same structure.
    before = parse_source(MESSY)
    after = parse_source(format_source(MESSY))
    assert [g.name for g in before.goals] == [g.name for g in after.goals]
    assert before.goals[0].sections.keys() == after.goals[0].sections.keys()
    assert [s.text for s in before.goals[0].statements("evidence")] == [
        s.text for s in after.goals[0].statements("evidence")
    ]


def test_examples_are_already_formatted() -> None:
    for name in ("diagnose", "code_review", "research_question",
                 "incident_pipeline", "triage_issue"):
        path = f"examples/{name}.iflow"
        with open(path, encoding="utf-8") as fh:
            original = fh.read()
        assert format_file(path) == original, f"{name} is not canonically formatted"
