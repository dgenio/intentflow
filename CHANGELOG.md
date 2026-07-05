# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- **`intentflow/trace.py`**: trace primitives (`Trace`, `link_hash`,
  `GENESIS_HASH`, `CANONICAL_PHASES`) extracted into a dedicated module, plus a
  shared event vocabulary (`Event` constants and the `KNOWN_EVENTS` set). The
  auditor now depends on this module instead of importing chain primitives from
  the runtime it verifies. `Trace`, `link_hash`, `GENESIS_HASH`,
  `CANONICAL_PHASES`, `Event`, and `KNOWN_EVENTS` are exported from the package
  root.

### Changed
- Trace event names are now defined once as `trace.Event` constants and shared
  by the runtime, the action gate, and the auditor (previously duplicated string
  literals across three modules). Hash output is unchanged.

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
