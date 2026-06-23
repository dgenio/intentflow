"""Smoke tests for checked-in shell completion scripts."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPLETION_DIR = ROOT / "completions"


def test_static_completion_scripts_cover_core_commands_and_choices() -> None:
    for shell in ("bash", "zsh", "fish"):
        script = COMPLETION_DIR / f"intentflow.{shell}"
        assert script.is_file()
        text = script.read_text()
        for token in ("parse", "validate", "run", "audit", "simulate", "anthropic", "openai", "replay"):
            assert token in text


def test_completion_generation_is_dev_only() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert "dependencies = []" in pyproject
    assert "shtab" in pyproject
    assert (ROOT / "scripts" / "generate_completions.py").is_file()
