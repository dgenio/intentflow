# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- **Docs, adoption & hygiene sweep**: `LICENSE` (MIT) plus `[project.urls]`
  and an `intentflow/py.typed` typing marker, now shipped in the built
  sdist/wheel (#41); `docs/api-stability.md` defining the semver-covered public
  surface and internal boundaries (#39); `docs/threat-model.md` and
  `SECURITY.md` (#29); `docs/cli-conventions.md` with a CLI surface budget
  (#92); reference/onboarding docs — `docs/language-reference.md` (#14),
  `docs/quickstart.md` (#15), `docs/concepts.md` (#85), `docs/backends.md`
  (#87), `docs/embedding.md` (#86), `docs/adr/0002-minimal-grammar-and-deterministic-simulator.md`
  (#50); a MkDocs (Material) site (`mkdocs.yml`, `.github/workflows/docs.yml`)
  (#16); community infrastructure — `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, a
  PR template, issue-template config, discussion templates (#26, #101);
  supply-chain hygiene — `.github/dependabot.yml` and a `pip-audit` workflow
  (#79); a `Dockerfile` and `.devcontainer/` (#96); adoption assets — a
  regenerable tamper-demo (`examples/tamper_demo.py`, #28), an example gallery
  index (#30), model-routing/escalation examples (#146), and a README demo
  block with a checked-in recording (#100).
- **`lint --json`**: `intentflow lint` gains machine-readable JSON output,
  matching `validate --json` (#92).
- **Evidence content digests**: each collected evidence item records a
  `content_digest` (SHA-256 of the summary shown to the model), witnessed in
  the `evidence_collected` trace event, so an auditor can confirm exactly what
  content a run used (#29).
- **New `docs` and `audit` optional-dependency groups** (`mkdocs`/
  `mkdocs-material`; `pip-audit`/`cyclonedx-bom`). The runtime core stays
  dependency-free.
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
- **Trace-seal key ids and rotation**: `Trace(sign_key=, key_id=)` tags an HMAC
  seal with a key id; the auditor verifies key-id'd seals against a key set
  (`IFLOW_TRACE_KEYS="id=secret,…"` at audit time, `IFLOW_TRACE_KEY_ID` at
  sign time), so rotating the signing key keeps old witnesses verifiable.
  Unknown-key-id and invalid-signature are distinct violations; key material is
  never logged. Procedure in `docs/trace-signing.md`.
- **Ed25519 public-key trace signatures**: new `intentflow.signing` module
  (`sign_root`, `verify_root`, `Ed25519Signer`) behind the optional `sign`
  extra (`pip install "intentflow[sign]"`, which adds `cryptography`). A run
  signed with a private key (`--sign-trace` + `IFLOW_TRACE_SIGNING_KEY`) is
  verifiable by any third party with only the **public** key
  (`IFLOW_TRACE_PUBLIC_KEY`) — no shared secret. HMAC and Ed25519 seals compose
  (dual-signing). The core import path stays free of `cryptography` (lazy,
  function-scoped import), verified by test.
- **Streamed JSONL trace sink**: `intentflow run --trace-stream PATH` (API:
  `trace_sink=`) appends each event to a JSONL file as it is recorded and
  flushes, so a hard crash leaves a chain-verifiable prefix and long runs need
  not hold the whole trace in memory. Writing fails closed
  (`trace.TraceSinkError`). `auditor.verify_trace_stream` and `intentflow audit`
  (auto-detecting a JSONL stream) chain-verify a stream and distinguish a
  complete run from a valid-but-truncated prefix.
- **Signature-required audit** (`intentflow audit --require-signed`, auditor
  `require_signed=`): rejects a witness that carries no signature verifying
  against the supplied keys — a stripped or absent seal — as a `T3`. Closes the
  downgrade path where a forger recomputes the bare chain and drops the seal's
  `signatures` list; the bare chain is integrity, sealing is authenticity.
  Opt-in, so the default (sealing is optional) is unchanged.
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
- **`intentflow run` help** now groups flags (backend / target selection /
  approvals / judging / trace output) via argparse argument groups. Parsing is
  unchanged (#92).
- **Shared grammar** moved to an internal `intentflow._grammar` module; the
  formatter no longer imports the parser's underscore-prefixed regexes. No
  behavior change (#39).
- Trace event names are now defined once as `trace.Event` constants and shared
  by the runtime, the action gate, and the auditor (previously duplicated string
  literals across three modules). Hash output is unchanged.

### Security
- **Untrusted evidence is delimited in prompts.** Collected evidence is wrapped
  in explicit fences and marked as data (not instructions) before being sent to
  the model — the standard prompt-injection mitigation (OWASP LLM01). Documented
  in `docs/threat-model.md` (#29).
- Because evidence-block wording changed, the exact prompt text sent to the
  model differs from prior releases; the delimited content is the same evidence.
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
- **Breaking (seal shape)**: the trace seal now carries a `signatures` list
  (`[{algo, signature, key_id?}]`) instead of a single flat `signature` field,
  so HMAC and (new) Ed25519 signatures coexist and HMAC seals can be key-id'd.
- `try_parse_json` now recovers a balanced JSON object embedded in surrounding
  prose, reducing spurious parse failures on real model replies. (#35)
- Code-fence stripping matches a whole ` ```json ` fence with a regex instead of
  character-stripping backticks, so backticks inside the reply survive. (#35)
- The LLM judge fails **closed** on an unparseable reply (records a failing
  verdict instead of raising), and retries transient chat failures. (#35, #73)

### Documented
- `docs/adr/0001-canonical-json-hashing.md`: adopts RFC 8785 (JCS) as the target
  canonical form for the (now enforced) JSON-native hashed domain, and defers
  the byte-format migration to a version-gated follow-up. Hash bytes are
  unchanged in this release.
- `docs/trace-scaling-investigation.md` + `scripts/bench_trace.py`: measured
  trace memory (~1.6 KB/event, linear) and trace-id hashing cost, motivating the
  chain-root `trace_id` derivation and the streaming sink.
### Fixed
- The embedding API (`IntentFlowProgram.run`/`run_pipeline`) now threads its
  `cassette` argument to the judge as it already does for the backend, so a
  `replay` judge reads recorded verdicts and a real judge records them — an
  API-driven run is fully replayable. Previously the cassette was dropped, so
  `judge="replay"` raised "requires a cassette path" and recording judges never
  captured their verdicts. (#75)

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
