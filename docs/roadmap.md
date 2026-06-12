# IntentFlow Roadmap

## Shipped (v0.5)

* Typed output schema (`summary: string`, `proposed_labels: list[string]`,
  optional `?` types) enforced at runtime by the implicit `V0` machine check.
* Static analyzer with coded diagnostics (IFLOW001–022), severity, position,
  and suggestions; `validate --json` for CI.
* Plan format 0.2: versioned, source-hashed, with per-goal policies, a
  computed risk profile, a staged prompt plan, and execution phases.
* 13-phase runtime with six honest statuses (`completed`, `needs_human`,
  `blocked`, `failed_validation`, `failed_verification`, `backend_error`).
* Backend contract (`BackendResponse`: raw text, parsed JSON, model,
  latency, token usage, finish reason) with simulate / mock / OpenAI-
  compatible / Anthropic / cassette-replay backends.
* Action registry with side-effect/risk metadata feeding the analyzer and
  risk profiler.
* `intentflow replay` (readable trace summaries, `--json`) and
  `intentflow explain` (plain-English program rendering).
* Formatter v2: canonical section order, typed-field spacing, comment
  preservation, idempotence.

## Next

1. **Learned confidence calibration** — replace the fixed shrinkage map
   with calibration learned from scored historical runs (per backend/model).
2. **Memory/context compiler** — turn `context:` policy (`max_tokens`,
   `prefer`, `preserve`) into concrete retrieval/eviction behavior instead
   of prompt text.
3. **Executable uncertainty actions** — give `retry`,
   `request_more_evidence`, and `run_discriminating_test` real executors
   with bounded budgets.
4. **Richer machine verification** — numeric bounds on output fields,
   `consistent_with(source)`, cross-field constraints, regex/phrase checks
   declared in the language.
5. **Typed object schemas** — `object` fields with declared keys, and
   nested list item types.
6. **DAG pipelines** — fan-out/fan-in over today's linear pipelines, with
   the same static evidence-chain checking.
7. **Asynchronous approvals** — issue an approval request, suspend the run,
   resume on callback (generalizing the synchronous webhook approver).
8. **Public-key trace signatures** (Ed25519) so witnesses verify without a
   shared HMAC secret.
9. **Real governed tool execution** — let approval-granted side-effect
   actions actually execute through the gate, with dry-run mode and
   rollback hooks.
10. **Language server / editor support** — diagnostics, hover docs for
    sections and actions, and format-on-save for `.iflow` files.
