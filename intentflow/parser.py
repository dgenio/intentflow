"""Parser for ``.iflow`` source files.

The grammar is deliberately simple and line-based:

* ``goal Name {`` opens a goal; ``}`` on its own line closes it.
* ``pipeline Name {`` opens a pipeline of ``stage GoalName`` lines.
* ``section:`` (e.g. ``evidence:``) opens a section inside a goal.
* Every other non-empty line inside a section is a statement.
* ``#`` starts a comment that runs to end of line.

All parse errors carry a line number and the source file name.
"""

from __future__ import annotations

import re
from pathlib import Path

from intentflow.iflow_ast import (
    Goal,
    Pipeline,
    Program,
    Section,
    StageRef,
    Statement,
    SECTION_NAMES,
)

_GOAL_RE = re.compile(r"^goal\s+([A-Za-z_][A-Za-z0-9_]*)\s*\{$")
_PIPELINE_RE = re.compile(r"^pipeline\s+([A-Za-z_][A-Za-z0-9_]*)\s*\{$")
_STAGE_RE = re.compile(r"^stage\s+([A-Za-z_][A-Za-z0-9_]*)$")
_SECTION_RE = re.compile(r"^([a-z_]+)\s*:$")


class ParseError(Exception):
    """A syntax error in an ``.iflow`` source file."""

    def __init__(self, message: str, line: int, source_name: str = "<string>") -> None:
        self.message = message
        self.line = line
        self.source_name = source_name
        super().__init__(f"{source_name}:{line}: {message}")


def _strip_comment(line: str) -> str:
    """Remove a ``#`` comment. The language has no string literals, so any
    ``#`` starts a comment."""
    idx = line.find("#")
    if idx != -1:
        line = line[:idx]
    return line.rstrip()


def parse_source(text: str, source_name: str = "<string>") -> Program:
    """Parse IntentFlow source text into a :class:`Program`."""
    program = Program(source_name=source_name)
    current_goal: Goal | None = None
    current_pipeline: Pipeline | None = None
    current_section: Section | None = None

    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = _strip_comment(raw).strip()
        if not line:
            continue

        if current_goal is None and current_pipeline is None:
            match = _GOAL_RE.match(line)
            if match:
                name = match.group(1)
                if program.goal(name) is not None:
                    raise ParseError(f"duplicate goal {name!r}", lineno, source_name)
                current_goal = Goal(name=name, line=lineno)
                current_section = None
                continue
            match = _PIPELINE_RE.match(line)
            if match:
                name = match.group(1)
                if program.pipeline(name) is not None:
                    raise ParseError(f"duplicate pipeline {name!r}", lineno, source_name)
                current_pipeline = Pipeline(name=name, line=lineno)
                continue
            if line.startswith("goal"):
                raise ParseError(
                    "malformed goal declaration; expected 'goal Name {'",
                    lineno,
                    source_name,
                )
            if line.startswith("pipeline"):
                raise ParseError(
                    "malformed pipeline declaration; expected 'pipeline Name {'",
                    lineno,
                    source_name,
                )
            raise ParseError(
                f"unexpected top-level content {line!r}; expected "
                "'goal Name {' or 'pipeline Name {'",
                lineno,
                source_name,
            )

        if current_pipeline is not None:
            if line == "}":
                if not current_pipeline.stages:
                    raise ParseError(
                        f"pipeline {current_pipeline.name!r} has no stages",
                        current_pipeline.line,
                        source_name,
                    )
                program.pipelines.append(current_pipeline)
                current_pipeline = None
                continue
            match = _STAGE_RE.match(line)
            if not match:
                raise ParseError(
                    f"invalid pipeline statement {line!r}; expected 'stage GoalName'",
                    lineno,
                    source_name,
                )
            current_pipeline.stages.append(
                StageRef(goal_name=match.group(1), line=lineno)
            )
            continue

        if line == "}":
            program.goals.append(current_goal)
            current_goal = None
            current_section = None
            continue

        section_match = _SECTION_RE.match(line)
        if section_match:
            section_name = section_match.group(1)
            if section_name not in SECTION_NAMES:
                raise ParseError(
                    f"unknown section {section_name!r}; expected one of: "
                    + ", ".join(SECTION_NAMES),
                    lineno,
                    source_name,
                )
            if section_name in current_goal.sections:
                raise ParseError(
                    f"duplicate section {section_name!r} in goal {current_goal.name!r}",
                    lineno,
                    source_name,
                )
            current_section = Section(name=section_name, line=lineno)
            current_goal.sections[section_name] = current_section
            continue

        if current_section is None:
            raise ParseError(
                f"statement {line!r} outside of any section; "
                "open a section first (e.g. 'evidence:')",
                lineno,
                source_name,
            )
        current_section.statements.append(Statement(text=line, line=lineno))

    if current_goal is not None:
        raise ParseError(
            f"unclosed goal {current_goal.name!r}; missing '}}'",
            current_goal.line,
            source_name,
        )
    if current_pipeline is not None:
        raise ParseError(
            f"unclosed pipeline {current_pipeline.name!r}; missing '}}'",
            current_pipeline.line,
            source_name,
        )
    if not program.goals:
        raise ParseError("no goals found in source", 1, source_name)
    return program


def parse_file(path: str | Path) -> Program:
    """Parse an ``.iflow`` file from disk."""
    path = Path(path)
    return parse_source(path.read_text(encoding="utf-8"), source_name=str(path))
