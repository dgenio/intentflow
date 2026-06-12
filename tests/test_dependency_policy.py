"""Dependency policy tests for IntentFlow's stdlib-only core.

The guard itself intentionally uses only the standard library plus pytest from
the dev extra. Runtime dependencies must stay empty; provider SDKs belong
behind optional extras and lazy imports.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import intentflow
from intentflow.backends import make_backend


ROOT = Path(__file__).resolve().parents[1]
STDLIB_MODULES = set(sys.stdlib_module_names) | {"__future__"}


def _runtime_dependencies(pyproject_text: str) -> list[str]:
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
        match = re.search(
            r"(?ms)^\[project\]\s*(.*?)(?:^\[|\Z)",
            pyproject_text,
        )
        if not match:
            raise AssertionError("missing [project] table")
        project_block = match.group(1)
        deps = re.search(r"(?m)^dependencies\s*=\s*\[(.*?)\]", project_block)
        if deps is None:
            raise AssertionError("missing project.dependencies")
        raw = deps.group(1).strip()
        if not raw:
            return []
        return [item.strip().strip("\"'") for item in raw.split(",") if item.strip()]

    payload = tomllib.loads(pyproject_text)
    return list(payload["project"].get("dependencies", []))


def _top_level_imports(source: str) -> set[str]:
    tree = ast.parse(source)
    modules: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            if node.module:
                modules.add(node.module.split(".", 1)[0])
    return modules


def _third_party_top_level_imports(source: str) -> set[str]:
    return {
        module
        for module in _top_level_imports(source)
        if module not in STDLIB_MODULES and module != "intentflow"
    }


def test_core_runtime_dependencies_stay_empty() -> None:
    deps = _runtime_dependencies((ROOT / "pyproject.toml").read_text())
    assert deps == []


def test_intentflow_modules_only_import_stdlib_or_intentflow_at_top_level() -> None:
    violations = {
        path.relative_to(ROOT).as_posix(): sorted(
            _third_party_top_level_imports(path.read_text())
        )
        for path in sorted((ROOT / "intentflow").glob("*.py"))
    }
    violations = {path: modules for path, modules in violations.items() if modules}
    assert violations == {}


def test_policy_guard_detects_fixture_violations() -> None:
    assert _runtime_dependencies(
        """
[project]
name = "fixture"
dependencies = ["requests"]
"""
    ) == ["requests"]
    assert _third_party_top_level_imports("import requests\n") == {"requests"}


def test_core_import_and_simulate_backend_work_without_optional_extras() -> None:
    assert intentflow.__version__
    backend = make_backend("simulate")
    proposal = backend.propose(
        {
            "prompt_plan": [
                {
                    "phase": "system",
                    "instruction": "Goal DiagnoseProductionIssue",
                }
            ]
        },
        [{"id": "E1", "source": "logs", "summary": "synthetic evidence"}],
    )
    assert proposal.hypotheses
    assert proposal.proposed_fix
