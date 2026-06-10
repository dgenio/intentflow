"""Formatter tests: indentation, section ordering, typed-field spacing,
comment preservation, and idempotence."""

from __future__ import annotations

from pathlib import Path

from intentflow.formatter import format_file, format_source
from intentflow.parser import parse_source

MESSY = """\
goal   Demo {
objective:
do the thing


      evidence:
            require    logs   # keep this comment
   distrust rumors
   output:
result:string
confidence :  number
}
"""


def test_format_normalizes_indentation_and_spacing() -> None:
    formatted = format_source(MESSY)
    lines = formatted.splitlines()
    assert lines[0] == "goal Demo {"
    assert "  objective:" in lines
    assert "    do the thing" in lines
    assert "  evidence:" in lines
    assert "    require logs # keep this comment" in lines
    assert lines[-1] == "}"


def test_format_normalizes_typed_output_fields() -> None:
    formatted = format_source(MESSY)
    assert "    result: string" in formatted.splitlines()
    assert "    confidence: number" in formatted.splitlines()


def test_format_orders_sections_canonically() -> None:
    src = (
        "goal G {\n"
        "  output:\n    a: string\n"
        "  objective:\n    x\n"
        "  evidence:\n    require logs\n"
        "}\n"
    )
    formatted = format_source(src)
    order = [
        line.strip().rstrip(":")
        for line in formatted.splitlines()
        if line.strip().endswith(":")
    ]
    assert order == ["objective", "evidence", "output"]


def test_section_comments_move_with_their_section() -> None:
    src = (
        "goal G {\n"
        "  # what we promise\n"
        "  output:\n    a: string\n"
        "  objective:\n    x\n"
        "}\n"
    )
    lines = format_source(src).splitlines()
    comment_index = lines.index("  # what we promise")
    assert lines[comment_index + 1] == "  output:"


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
    # Statement meaning is preserved (internal runs of spaces are normalized).
    assert [" ".join(s.text.split()) for s in before.goals[0].statements("evidence")] == [
        s.text for s in after.goals[0].statements("evidence")
    ]


def test_quoted_strings_survive_space_collapsing() -> None:
    src = (
        'goal G {\n  meta:\n    description "two  spaces   stay"\n'
        "  objective:\n    x\n}\n"
    )
    formatted = format_source(src)
    assert '"two  spaces   stay"' in formatted


def test_pipelines_format() -> None:
    src = (
        "goal A {\n  objective:\n    x\n}\n"
        "pipeline    P {\n      stage   A\n}\n"
    )
    formatted = format_source(src)
    assert "pipeline P {" in formatted
    assert "  stage A" in formatted
    assert format_source(formatted) == formatted


def test_examples_are_already_formatted() -> None:
    for path in sorted(Path("examples").glob("*.iflow")):
        original = path.read_text(encoding="utf-8")
        assert format_file(path) == original, f"{path} is not canonically formatted"
