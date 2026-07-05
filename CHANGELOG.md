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

- **Hashed-domain enforcement**: `trace.assert_json_native` rejects any trace
  `detail` that is not composed of JSON-native types, enforced in `Trace.record`
  so the canonical hash form can never silently depend on CPython's `str()`
  coercion. Documented in `docs/adr/0001-canonical-json-hashing.md`.

### Changed
- Trace event names are now defined once as `trace.Event` constants and shared
  by the runtime, the action gate, and the auditor (previously duplicated string
  literals across three modules). Hash output is unchanged.

### Documented
- `docs/adr/0001-canonical-json-hashing.md`: adopts RFC 8785 (JCS) as the target
  canonical form for the (now enforced) JSON-native hashed domain, and defers
  the byte-format migration to a version-gated follow-up. Hash bytes are
  unchanged in this release.

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
