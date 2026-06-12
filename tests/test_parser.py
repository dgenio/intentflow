"""Parser tests: valid programs, comments, strings, and error reporting with
line/column positions."""

from __future__ import annotations

from pathlib import Path

import pytest

from intentflow.parser import ParseError, parse_file, parse_source, strip_comment

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
    result: string
    confidence: number
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


def test_source_text_is_kept_for_hashing() -> None:
    program = parse_source(VALID)
    assert program.source_text == VALID
    assert "source_text" not in program.to_dict()


def test_comments_and_blank_lines_are_ignored() -> None:
    program = parse_source(VALID)
    objective = program.goals[0].statements("objective")
    assert [s.text for s in objective] == ["do the thing"]


def test_hash_inside_string_is_not_a_comment() -> None:
    assert strip_comment('description "issue #42" # real comment') == (
        'description "issue #42"'
    )
    src = (
        'goal G {\n  meta:\n    description "fixes #42"\n'
        "  objective:\n    x\n  output:\n    a: string\n}\n"
    )
    program = parse_source(src)
    assert program.goals[0].statements("meta")[0].text == 'description "fixes #42"'


def test_statement_positions_are_recorded() -> None:
    program = parse_source(VALID)
    require_logs = program.goals[0].statements("evidence")[0]
    assert require_logs.line == 7
    assert require_logs.column == 5


def test_parse_example_files() -> None:
    for path in sorted(Path("examples").glob("*.iflow")):
        program = parse_file(path)
        assert program.goals, path


def test_unclosed_goal_is_an_error() -> None:
    with pytest.raises(ParseError) as exc_info:
        parse_source("goal Broken {\n  objective:\n    something\n")
    assert "unclosed goal" in str(exc_info.value)
    assert exc_info.value.line == 1


def test_unknown_section_is_an_error_with_position() -> None:
    source = "goal G {\n  objective:\n    x\n  vibes:\n    y\n}\n"
    with pytest.raises(ParseError) as exc_info:
        parse_source(source)
    assert "unknown section 'vibes'" in str(exc_info.value)
    assert exc_info.value.line == 4
    assert exc_info.value.column == 3


def test_duplicate_section_is_an_error() -> None:
    source = "goal G {\n  objective:\n    x\n  objective:\n    y\n}\n"
    with pytest.raises(ParseError, match="duplicate section"):
        parse_source(source)


def test_duplicate_goal_names_parse_fine() -> None:
    # Duplicate goals are an analyzer error (IFLOW016), not a parse error.
    source = (
        "goal G {\n  objective:\n    x\n}\n"
        "goal G {\n  objective:\n    y\n}\n"
    )
    program = parse_source(source)
    assert len(program.goals) == 2


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
