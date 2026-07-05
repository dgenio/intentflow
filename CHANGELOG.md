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
- **Format-version compatibility**: the auditor now verifies the plan and
  result declare a `format_version` it supports (`auditor.SUPPORTED_PLAN_FORMATS`
  / `SUPPORTED_TRACE_FORMATS`), emitting a `P2` violation on a mismatch instead
  of auditing an unknown shape. Run results carry a `format_version`
  (`trace.TRACE_FORMAT_VERSION`). Policy documented in `docs/formats.md`.
- **Published JSON Schemas** (`schemas/plan.schema.json`,
  `schemas/result.schema.json`, JSON Schema draft 2020-12) for the two contract
  artifacts, linked from the README and `docs/formats.md`. Every bundled
  example's plan, goal result, and pipeline result is validated against them in
  the test suite. `jsonschema` added as a **dev-only** dependency; the runtime
  core stays dependency-free.

### Changed
- Trace event names are now defined once as `trace.Event` constants and shared
  by the runtime, the action gate, and the auditor (previously duplicated string
  literals across three modules). Hash output is unchanged.
- **`trace_id` derivation**: now `sha256(plan_digest + trace_chain_root)` instead
  of re-serializing the whole `{plan, trace}` document. The chain root already
  commits to every trace event, so the id no longer scales with trace length
  (3.8–5.9× faster on the benchmark). Determinism and audit semantics are
  unchanged; the id values themselves differ from prior releases.
- **Breaking (plan shape)**: the plan/document version field is renamed
  `plan_version` → `format_version` (constant `PLAN_VERSION` → `PLAN_FORMAT_VERSION`)
  so both contract artifacts use one uniform, independently-versioned field name.
- **Breaking (witness shape)**: `--trace-out` now writes the same canonical
  witness envelope as `--trace-dir` (`{artifact, …, result}`) instead of a bare
  result, and a multi-goal `--trace-out` run errors with guidance (use
  `--trace-dir` or `--goal`) instead of writing an unauditable JSON list.
  `audit` and `replay` now require the envelope and no longer sniff shapes;
  `build_witness_envelope` is the single source for both flags.

### Documented
- `docs/adr/0001-canonical-json-hashing.md`: adopts RFC 8785 (JCS) as the target
  canonical form for the (now enforced) JSON-native hashed domain, and defers
  the byte-format migration to a version-gated follow-up. Hash bytes are
  unchanged in this release.
- `docs/trace-scaling-investigation.md` + `scripts/bench_trace.py`: measured
  trace memory (~1.6 KB/event, linear) and trace-id hashing cost, motivating the
  chain-root `trace_id` derivation and the streaming sink.

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
