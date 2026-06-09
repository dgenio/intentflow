"""Parser tests: valid programs, comments, and error reporting with lines."""

from __future__ import annotations

import pytest

from intentflow.parser import ParseError, parse_file, parse_source

VALID = """\
# top-level comment
goal Demo {
  objective:
    do the thing  # trailing comment

  evidence:
    require logs
    distrust rumors

  actions:
    allow read_logs
    require_approval deploy

  output:
    result
}
"""


def test_parse_valid_program() -> None:
    program = parse_source(VALID, source_name="demo.iflow")
    assert len(program.goals) == 1
    goal = program.goals[0]
    assert goal.name == "Demo"
    assert set(goal.sections) == {"objective", "evidence", "actions", "output"}
    assert [s.text for s in goal.statements("evidence")] == [
        "require logs",
        "distrust rumors",
    ]


def test_comments_and_blank_lines_are_ignored() -> None:
    program = parse_source(VALID)
    objective = program.goals[0].statements("objective")
    assert [s.text for s in objective] == ["do the thing"]


def test_statement_line_numbers_are_recorded() -> None:
    program = parse_source(VALID)
    require_logs = program.goals[0].statements("evidence")[0]
    assert require_logs.line == 7


def test_parse_example_files() -> None:
    for name in ("diagnose", "code_review", "research_question"):
        program = parse_file(f"examples/{name}.iflow")
        assert program.goals, name


def test_unclosed_goal_is_an_error() -> None:
    with pytest.raises(ParseError) as exc_info:
        parse_source("goal Broken {\n  objective:\n    something\n")
    assert "unclosed goal" in str(exc_info.value)
    assert exc_info.value.line == 1


def test_unknown_section_is_an_error_with_line() -> None:
    source = "goal G {\n  objective:\n    x\n  vibes:\n    y\n}\n"
    with pytest.raises(ParseError) as exc_info:
        parse_source(source)
    assert "unknown section 'vibes'" in str(exc_info.value)
    assert exc_info.value.line == 4


def test_duplicate_section_is_an_error() -> None:
    source = "goal G {\n  objective:\n    x\n  objective:\n    y\n}\n"
    with pytest.raises(ParseError, match="duplicate section"):
        parse_source(source)


def test_statement_outside_section_is_an_error() -> None:
    source = "goal G {\n  floating statement\n}\n"
    with pytest.raises(ParseError, match="outside of any section") as exc_info:
        parse_source(source)
    assert exc_info.value.line == 2


def test_garbage_at_top_level_is_an_error() -> None:
    with pytest.raises(ParseError, match="unexpected top-level content"):
        parse_source("just some words\n")


def test_malformed_goal_header_is_an_error() -> None:
    with pytest.raises(ParseError, match="malformed goal declaration"):
        parse_source("goal Missing Brace\n}\n")


def test_empty_source_is_an_error() -> None:
    with pytest.raises(ParseError, match="no goals"):
        parse_source("# only a comment\n")
