"""Packaging and licensing hygiene (see #41).

These are structural checks against the repo tree and ``pyproject.toml`` — no
build step required — so they run in the standard suite and fail fast if the
license file, typing marker, or metadata regress.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _pyproject() -> dict:
    with (ROOT / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)


def test_license_file_exists_and_is_mit() -> None:
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in text
    assert "Permission is hereby granted, free of charge" in text


def test_pyproject_references_license_file() -> None:
    project = _pyproject()["project"]
    assert project["license"] == {"file": "LICENSE"}
    assert "License :: OSI Approved :: MIT License" in project["classifiers"]


def test_pyproject_declares_project_urls() -> None:
    urls = _pyproject()["project"]["urls"]
    for key in ("Homepage", "Repository", "Issues"):
        assert key in urls
        assert urls[key].startswith("https://github.com/dgenio/intentflow")


def test_py_typed_marker_is_present_and_packaged() -> None:
    assert (ROOT / "intentflow" / "py.typed").exists()
    package_data = _pyproject()["tool"]["setuptools"]["package-data"]
    assert "py.typed" in package_data["intentflow"]
