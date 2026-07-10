"""Shared lexical grammar for ``.iflow`` — the single source of truth.

These compiled patterns describe the line-based surface syntax (goal and
pipeline headers, stage lines, section headers). They are consumed by both
:mod:`intentflow.parser` (to build the AST) and :mod:`intentflow.formatter`
(to reformat source without changing meaning), so they live here rather than
in either consumer.

This module is **internal** (leading-underscore name): it is not part of the
public API and may change between releases without a deprecation cycle. See
``docs/api-stability.md``. It exists so that no module has to reach into
another module's underscore-prefixed names to share the grammar.
"""

from __future__ import annotations

import re

#: ``goal Name {`` — opens a goal block. Group 1 is the goal name.
GOAL_RE = re.compile(r"^goal\s+([A-Za-z_][A-Za-z0-9_]*)\s*\{$")
#: ``pipeline Name {`` — opens a pipeline block. Group 1 is the pipeline name.
PIPELINE_RE = re.compile(r"^pipeline\s+([A-Za-z_][A-Za-z0-9_]*)\s*\{$")
#: ``stage GoalName`` — one stage line inside a pipeline. Group 1 is the goal.
STAGE_RE = re.compile(r"^stage\s+([A-Za-z_][A-Za-z0-9_]*)$")
#: ``section:`` — opens a section inside a goal. Group 1 is the section name.
SECTION_RE = re.compile(r"^([a-z_]+)\s*:$")
