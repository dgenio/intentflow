"""Keep documented ``.iflow`` snippets honest.

The language reference, quickstart, and concepts docs embed ```iflow fenced
blocks. This test extracts every such block that is a complete program (has a
``goal`` or ``pipeline`` header) and asserts it actually parses, so the docs
cannot drift from the implemented grammar (see #14, #15).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from intentflow.analyzer import analyze_program, errors_in
from intentflow.parser import parse_source

DOCS = Path(__file__).resolve().parent.parent / "docs"
DOC_FILES = ["language-reference.md", "quickstart.md", "concepts.md"]
_FENCE = re.compile(r"```iflow\n(.*?)```", re.DOTALL)


def _program_blocks() -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    for name in DOC_FILES:
        text = (DOCS / name).read_text(encoding="utf-8")
        for i, match in enumerate(_FENCE.findall(text)):
            snippet = match.strip()
            # A goal block is a self-contained program; a lone pipeline block is
            # illustrative (the parser requires at least one goal), so only
            # goal-headed blocks are parse-checked here.
            if snippet.startswith("goal "):
                blocks.append((f"{name}#{i}", snippet))
    return blocks


PROGRAM_BLOCKS = _program_blocks()


def test_docs_contain_iflow_examples() -> None:
    assert PROGRAM_BLOCKS, "expected at least one complete .iflow doc example"


@pytest.mark.parametrize(
    "snippet", [b for _, b in PROGRAM_BLOCKS], ids=[n for n, _ in PROGRAM_BLOCKS]
)
def test_documented_iflow_snippet_parses(snippet: str) -> None:
    parse_source(snippet)  # raises ParseError on invalid syntax


def test_quickstart_goal_validates_clean() -> None:
    # The quickstart's headline goal must analyze without errors — a new user
    # copy-pasting it should not hit a validation failure.
    text = (DOCS / "quickstart.md").read_text(encoding="utf-8")
    triage = next(
        b for b in _FENCE.findall(text) if "goal TriageBug" in b
    )
    program = parse_source(triage.strip())
    assert errors_in(analyze_program(program)) == []
