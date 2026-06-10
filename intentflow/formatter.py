"""A small, structural formatter for ``.iflow`` source.

The formatter normalizes indentation and blank-line spacing without changing
meaning. It is deliberately line-based and comment-preserving: it never
reorders sections, rewrites statements, or drops comments — it only fixes
indentation (goals/pipelines at column 0, sections/stages at 2 spaces,
statements at 4 spaces) and collapses runs of blank lines.

Because formatting is a pure function of structure, ``format_source`` is
idempotent: ``format_source(format_source(x)) == format_source(x)``.
"""

from __future__ import annotations

from pathlib import Path

from intentflow.parser import _GOAL_RE, _PIPELINE_RE, _SECTION_RE, _STAGE_RE

_INDENT = "  "


def _comment_indent(context: str) -> str:
    if context == "section":
        return _INDENT * 2
    if context in ("goal", "pipeline"):
        return _INDENT
    return ""


def format_source(text: str) -> str:
    """Reformat IntentFlow source text canonically."""
    out: list[str] = []
    context = "top"  # top | goal | section | pipeline

    for raw in text.splitlines():
        stripped = raw.strip()

        if not stripped:
            out.append("")
            continue

        if stripped.startswith("#"):
            out.append(_comment_indent(context) + stripped)
            continue

        if stripped == "}":
            out.append("}")
            context = "top"
            continue

        if context == "top":
            goal = _GOAL_RE.match(stripped)
            if goal:
                out.append(f"goal {goal.group(1)} {{")
                context = "goal"
                continue
            pipeline = _PIPELINE_RE.match(stripped)
            if pipeline:
                out.append(f"pipeline {pipeline.group(1)} {{")
                context = "pipeline"
                continue
            # Unknown top-level content: leave it untouched rather than choke.
            out.append(stripped)
            continue

        if context == "pipeline":
            stage = _STAGE_RE.match(stripped)
            out.append(_INDENT + (f"stage {stage.group(1)}" if stage else stripped))
            continue

        # Inside a goal: a section header drops to 2 spaces; anything else is
        # a statement at 4 spaces.
        section = _SECTION_RE.match(stripped)
        if section:
            out.append(_INDENT + f"{section.group(1)}:")
            context = "section"
            continue
        out.append(_INDENT * 2 + stripped)

    return _clean_blank_lines(out)


def _clean_blank_lines(lines: list[str]) -> str:
    cleaned: list[str] = []
    for line in lines:
        if line == "":
            if not cleaned or cleaned[-1] == "":
                continue  # drop leading and duplicate blank lines
            if cleaned[-1].endswith("{"):
                continue  # drop a blank immediately after an opening brace
            cleaned.append("")
            continue
        if line == "}":
            while cleaned and cleaned[-1] == "":
                cleaned.pop()  # drop blanks immediately before a closing brace
        cleaned.append(line)
    while cleaned and cleaned[-1] == "":
        cleaned.pop()
    return "\n".join(cleaned) + "\n"


def format_file(path: str | Path) -> str:
    """Read and reformat an ``.iflow`` file (does not write it back)."""
    return format_source(Path(path).read_text(encoding="utf-8"))
