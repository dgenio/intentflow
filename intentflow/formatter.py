"""A structural, comment-preserving formatter for ``.iflow`` source.

The formatter normalizes, without changing meaning:

* indentation (goals/pipelines at column 0, sections/stages at 2 spaces,
  statements at 4 spaces);
* blank lines (one between sections, one between top-level blocks, none
  immediately inside braces);
* section order (canonical: meta, objective, context, evidence, model,
  actions, verify, uncertainty, output) — comments move with the section
  and statement they annotate;
* spacing inside statements (``summary:string`` -> ``summary: string``;
  ``require   logs`` -> ``require logs``), respecting quoted strings;
* trailing whitespace.

Formatting is a pure function of structure, so ``format_source`` is
idempotent: ``format_source(format_source(x)) == format_source(x)``.
The CLI refuses to format syntactically broken source, so the formatter may
assume parseable input (and degrades gracefully when it cannot match a line).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from intentflow.iflow_ast import SECTION_NAMES
from intentflow.parser import _GOAL_RE, _PIPELINE_RE, _SECTION_RE, _STAGE_RE

_INDENT = "  "
_OUTPUT_FIELD_SPACING_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(\S+)$")
_SECTION_ORDER = {name: i for i, name in enumerate(SECTION_NAMES)}


def _collapse_spaces(text: str) -> str:
    """Collapse runs of whitespace outside double-quoted strings."""
    out: list[str] = []
    in_string = False
    escaped = False
    pending_space = False
    for ch in text:
        if escaped:
            out.append(ch)
            escaped = False
            continue
        if in_string and ch == "\\":
            out.append(ch)
            escaped = True
            continue
        if ch == '"':
            if pending_space:
                out.append(" ")
                pending_space = False
            in_string = not in_string
            out.append(ch)
            continue
        if not in_string and ch in (" ", "\t"):
            pending_space = bool(out)
            continue
        if pending_space:
            out.append(" ")
            pending_space = False
        out.append(ch)
    return "".join(out)


def _normalize_statement(text: str, section: str | None) -> str:
    """Normalize one statement's internal spacing."""
    if section == "output":
        match = _OUTPUT_FIELD_SPACING_RE.match(text)
        if match:
            return f"{match.group(1)}: {match.group(2)}"
    return _collapse_spaces(text)


@dataclass
class _Item:
    """A statement (or stage) with the comments written above it."""

    comments: list[str] = field(default_factory=list)
    text: str = ""


@dataclass
class _SectionBlock:
    name: str
    comments: list[str] = field(default_factory=list)
    items: list[_Item] = field(default_factory=list)
    trailing_comments: list[str] = field(default_factory=list)


@dataclass
class _Block:
    """A goal or pipeline with its comments and contents."""

    kind: str  # "goal" | "pipeline" | "raw"
    name: str = ""
    comments: list[str] = field(default_factory=list)
    sections: list[_SectionBlock] = field(default_factory=list)
    items: list[_Item] = field(default_factory=list)  # pipeline stages
    trailing_comments: list[str] = field(default_factory=list)
    raw: str = ""


def _parse_blocks(text: str) -> tuple[list[_Block], list[str]]:
    """Group source lines into blocks, attaching comments to what follows."""
    blocks: list[_Block] = []
    pending_comments: list[str] = []
    current: _Block | None = None
    current_section: _SectionBlock | None = None

    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            pending_comments.append(stripped)
            continue
        if current is None:
            match = _GOAL_RE.match(stripped)
            if match:
                current = _Block("goal", match.group(1), comments=pending_comments)
                pending_comments = []
                current_section = None
                continue
            match = _PIPELINE_RE.match(stripped)
            if match:
                current = _Block("pipeline", match.group(1), comments=pending_comments)
                pending_comments = []
                continue
            # Unknown top-level content: keep it verbatim rather than choke.
            blocks.append(_Block("raw", comments=pending_comments, raw=stripped))
            pending_comments = []
            continue
        if stripped == "}":
            if current_section is not None:
                current_section.trailing_comments.extend(pending_comments)
            else:
                current.trailing_comments.extend(pending_comments)
            pending_comments = []
            blocks.append(current)
            current = None
            current_section = None
            continue
        if current.kind == "pipeline":
            current.items.append(_Item(comments=pending_comments, text=stripped))
            pending_comments = []
            continue
        section_match = _SECTION_RE.match(stripped)
        if section_match and section_match.group(1) in SECTION_NAMES:
            current_section = _SectionBlock(
                section_match.group(1), comments=pending_comments
            )
            pending_comments = []
            current.sections.append(current_section)
            continue
        if current_section is None:
            # Statement outside any section (broken source): keep verbatim.
            current.items.append(_Item(comments=pending_comments, text=stripped))
            pending_comments = []
            continue
        current_section.items.append(_Item(comments=pending_comments, text=stripped))
        pending_comments = []

    return blocks, pending_comments


def _emit_goal(block: _Block, out: list[str]) -> None:
    for comment in block.comments:
        out.append(comment)
    out.append(f"goal {block.name} {{")
    ordered = sorted(
        block.sections, key=lambda s: _SECTION_ORDER.get(s.name, len(SECTION_NAMES))
    )
    for i, section in enumerate(ordered):
        if i > 0:
            out.append("")
        for comment in section.comments:
            out.append(_INDENT + comment)
        out.append(f"{_INDENT}{section.name}:")
        for item in section.items:
            for comment in item.comments:
                out.append(_INDENT * 2 + comment)
            out.append(_INDENT * 2 + _normalize_statement(item.text, section.name))
        for comment in section.trailing_comments:
            out.append(_INDENT * 2 + comment)
    for item in block.items:  # statements outside sections (kept verbatim)
        for comment in item.comments:
            out.append(_INDENT + comment)
        out.append(_INDENT + _collapse_spaces(item.text))
    for comment in block.trailing_comments:
        out.append(_INDENT + comment)
    out.append("}")


def _emit_pipeline(block: _Block, out: list[str]) -> None:
    for comment in block.comments:
        out.append(comment)
    out.append(f"pipeline {block.name} {{")
    for item in block.items:
        for comment in item.comments:
            out.append(_INDENT + comment)
        stage = _STAGE_RE.match(item.text)
        out.append(_INDENT + (f"stage {stage.group(1)}" if stage else _collapse_spaces(item.text)))
    for comment in block.trailing_comments:
        out.append(_INDENT + comment)
    out.append("}")


def format_source(text: str) -> str:
    """Reformat IntentFlow source text canonically."""
    blocks, dangling = _parse_blocks(text)
    out: list[str] = []
    for i, block in enumerate(blocks):
        if i > 0:
            out.append("")
        if block.kind == "goal":
            _emit_goal(block, out)
        elif block.kind == "pipeline":
            _emit_pipeline(block, out)
        else:
            for comment in block.comments:
                out.append(comment)
            out.append(block.raw)
    for comment in dangling:
        out.append(comment)
    return "\n".join(out) + "\n"


def format_file(path: str | Path) -> str:
    """Read and reformat an ``.iflow`` file (does not write it back)."""
    return format_source(Path(path).read_text(encoding="utf-8"))
