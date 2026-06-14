# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.6.0] - 2026-06-14

### Added
- **Typed output system**: structured, type-annotated outputs with runtime validation.
- **Analyzer**: static analysis pipeline for plans, evidence chains, and risk surfaces.
- **Phase runtime**: segmented execution phases with per-phase gating and checkpointing.
- **Replay and explain**: `intentflow replay` and `intentflow explain` to walk through prior traces step-by-step.
- `compiler.py`, `explain.py`, and `analyzer.py` modules to the core package.
- Expanded test coverage for typed outputs, analyzer diagnostics, and phase transitions.

### Changed
- Trace generation now integrates with phase boundaries for clearer audit trails.
- Plan compilation produces richer metadata for post-run verification.

### Fixed
- Various linter and formatter edge cases discovered during new runtime integration.
