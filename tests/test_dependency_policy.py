"""Dependency policy tests for IntentFlow's stdlib-only core.

The guard itself intentionally uses only the standard library plus pytest from
the dev dependency group. Runtime dependencies must stay empty; user-facing
provider/signing SDKs belong behind optional extras, while maintainer tooling
belongs in PEP 735 dependency groups.
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
PUBLIC_FUNCTIONAL_EXTRAS = {"llm", "openai", "sign"}
LEGACY_EMPTY_EXTRAS = {"dev", "docs", "audit"}
MAINTAINER_GROUPS = {"dev", "docs", "audit"}


def _load_pyproject(pyproject_text: str) -> dict:
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
        import tomli as tomllib

    return tomllib.loads(pyproject_text)


def _runtime_dependencies(pyproject_text: str) -> list[str]:
    try:
        payload = _load_pyproject(pyproject_text)
    except ModuleNotFoundError:  # pragma: no cover - defensive fallback
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

    return list(payload["project"].get("dependencies", []))


def _top_level_imports(source: str) -> set[str]:
    tree = ast.parse(source)
    modules: set[str] = set()

    def iter_module_level(nodes: list[ast.stmt]):
        for node in nodes:
            yield node
            if isinstance(node, ast.If):
                yield from iter_module_level(node.body)
                yield from iter_module_level(node.orelse)
            elif isinstance(node, ast.Try):
                yield from iter_module_level(node.body)
                for handler in node.handlers:
                    yield from iter_module_level(handler.body)
                yield from iter_module_level(node.orelse)
                yield from iter_module_level(node.finalbody)
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                yield from iter_module_level(node.body)

    for node in iter_module_level(tree.body):
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


def test_published_extras_only_expose_user_capabilities() -> None:
    payload = _load_pyproject((ROOT / "pyproject.toml").read_text())
    extras = payload["project"].get("optional-dependencies", {})
    assert set(extras) == PUBLIC_FUNCTIONAL_EXTRAS | LEGACY_EMPTY_EXTRAS
    assert all(extras[name] for name in PUBLIC_FUNCTIONAL_EXTRAS)
    assert all(extras[name] == [] for name in LEGACY_EMPTY_EXTRAS)

    groups = payload.get("dependency-groups", {})
    assert set(groups) == MAINTAINER_GROUPS
    assert all(groups[name] for name in MAINTAINER_GROUPS)


def test_public_install_section_is_registry_first() -> None:
    readme = (ROOT / "README.md").read_text()
    install = readme.split("## Install", 1)[1].split("## Quickstart", 1)[0]
    assert "pip install intentflow" in install
    assert 'pip install "intentflow[openai]"' in install
    assert 'pip install "intentflow[llm]"' in install
    assert 'pip install "intentflow[sign]"' in install
    assert "pip install -e" not in install
    assert "intentflow[dev]" not in install
    assert "intentflow[docs]" not in install
    assert "intentflow[audit]" not in install


def test_intentflow_modules_only_import_stdlib_or_intentflow_at_top_level() -> None:
    violations = {
        path.relative_to(ROOT).as_posix(): sorted(
            _third_party_top_level_imports(path.read_text())
        )
        for path in sorted((ROOT / "intentflow").rglob("*.py"))
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
    assert isinstance(backend.complete("system", "user"), str)
