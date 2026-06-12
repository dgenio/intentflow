"""Static analysis entry point kept for compatibility.

The real analysis lives in :mod:`intentflow.analyzer`, which produces coded
diagnostics (``IFLOW001``..). ``intentflow lint`` and these helpers surface
the analyzer's *warnings and info* — the advisory tier — as
:class:`Finding` objects. Use ``intentflow validate`` (or
:func:`intentflow.analyzer.analyze_program`) for the full picture including
errors.
"""

from __future__ import annotations

from dataclasses import dataclass

from intentflow.analyzer import analyze_goal, analyze_program
from intentflow.iflow_ast import Goal, Program


@dataclass
class Finding:
    rule_id: str
    level: str  # "warning" | "info"
    message: str
    line: int


def lint_goal(goal: Goal) -> list[Finding]:
    return [
        Finding(d.code, d.severity, d.message, d.line)
        for d in analyze_goal(goal)
        if d.severity in ("warning", "info")
    ]


def lint_program(program: Program) -> list[Finding]:
    return [
        Finding(d.code, d.severity, d.message, d.line)
        for d in analyze_program(program)
        if d.severity in ("warning", "info")
    ]
