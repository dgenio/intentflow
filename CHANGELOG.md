# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- **Reliability primitives** (`intentflow/reliability.py`): `HTTPTimeout` and a
  bounded, fail-closed `RetryPolicy` with deterministic exponential backoff,
  shared by real cognition backends and the LLM judge. Configurable via
  `INTENTFLOW_HTTP_TIMEOUT`, `INTENTFLOW_HTTP_CONNECT_TIMEOUT`,
  `INTENTFLOW_MAX_ATTEMPTS`, `INTENTFLOW_RETRY_BASE_DELAY`,
  `INTENTFLOW_RETRY_MAX_DELAY`, and `INTENTFLOW_RETRY_BACKOFF`. (#73, #135)
- **Explicit HTTP timeouts** threaded into every Anthropic/OpenAI request; the
  provider SDKs' own retry loops are disabled so IntentFlow owns retry policy. (#135, #73)
- **Judge cassettes**: `ReplayChat`/`RecordingChat` and a `replay` judge, so
  `judged` verification rules can be recorded once and replayed in CI with no
  API key — reusing the existing `--cassette`/`--record-cassette` flags. (#75)
- Fake-client tests exercising the real backends' assemble → call → parse path
  without network access or SDKs. (#44)

### Changed
- `try_parse_json` now recovers a balanced JSON object embedded in surrounding
  prose, reducing spurious parse failures on real model replies. (#35)
- The LLM judge fails **closed** on an unparseable reply (records a failing
  verdict instead of raising), and retries transient chat failures. (#35, #73)

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
