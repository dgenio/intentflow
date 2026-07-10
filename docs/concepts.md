# Concepts and glossary

The load-bearing vocabulary IntentFlow uses, defined once here and
cross-referenced from the rest of the docs. Each term names the module that
implements it and, where relevant, the auditor check that enforces it.

## Program as contract

An `.iflow` program is not a script; it is a **contract** for a cognitive task
— objective, required evidence, the action envelope, verification rules,
uncertainty handling, and a typed output schema. The compiler
(`intentflow/compiler.py`) lowers it to an inspectable execution plan (JSON)
before any model runs. See [`formats.md`](formats.md) for the plan shape.

## Trace as witness

A run emits a **witness**: the structured result plus a hash-chained **trace**
of every phase (`intentflow/trace.py`, `intentflow/runtime.py`). The witness is
designed to be checked by someone who did not run it — that is what makes
"auditable" more than a slogan.

## Behavior envelope

The **envelope** is the set of actions a run is authorized to take, fixed by the
plan's `actions:` policy (allow / deny / require_approval). The **ActionGate**
(`intentflow/tools.py`) authorizes every side-effecting call against the
envelope — and crucially, *never reads model output to make that decision*. A
model cannot widen its own envelope.

## Trust tiers: machine vs judged

Verification runs in two tiers:

- **Machine-checkable** rules (`cites_evidence`, `check <metric> <op> <n>`,
  `requires_phrase`) are evaluated deterministically by the runtime.
- **Judged** rules are delegated to an LLM **judge** (`intentflow/judges.py`), a
  separate trust tier used only when `--judge` is set. A judged check is never
  silently passed — an unparseable/failed judgment fails closed.

## Calibration

The simulator adjusts a raw confidence toward a calibrated value before
threshold checks (`intentflow/runtime.py`), so `if confidence < 0.7 ask_human`
is evaluated against calibrated confidence, not the model's self-report.

## Escalation

When an `uncertainty:` condition triggers `ask_human`, the run **escalates**
rather than fabricating an answer — the terminal status becomes `needs_human`
and the escalation is recorded in the trace.

## Conformance

A witness is **conformant** if the auditor (`intentflow/auditor.py`) can verify,
against the plan, that the run stayed inside its contract. The auditor codes:

| Code | Checks |
|------|--------|
| A1 | every invoked action was allowed by the plan |
| A2 | every approval-gated invocation had a prior grant |
| A3 | no denied action was ever invoked |
| T1 | the trace is append-only (sequence strictly increasing from 1) |
| T2 | phases ran in canonical order |
| T3 | the hash chain is intact and, when keys are configured, the seal verifies |
| E1 | every citation points at collected evidence |
| U1 | every uncertainty rule was evaluated or recorded |
| V1 | every verification rule was checked; no failed check is reported as pass |
| S1 | the reported status is consistent with the trace |
| O1 | produced outputs match the declared output schema |
| P1 | a plan exists for the goal/stage named in the result |
| P2 | plan/result format versions are ones this auditor supports |

(Authoritative list: the module docstring in `intentflow/auditor.py`.)

## Integrity vs authenticity

Two distinct guarantees about a witness (see [`trace-signing.md`](trace-signing.md)):

- **Integrity** — the hash chain proves the trace was not edited after the fact.
  It holds with no keys at all: any change breaks a link.
- **Authenticity** — an optional **seal** (HMAC or Ed25519 **signature**) proves
  *who* produced it. `audit --require-signed` rejects an unsigned witness so a
  forger cannot simply drop the seal.

Integrity without authenticity still catches tampering; authenticity adds "and
it came from the expected signer."

## Cassette

A **cassette** records a real backend's (and judge's) responses to a file so a
run can be **replayed** deterministically later — in CI, with no API key. See
`--cassette` / `--record-cassette` and [`backends.md`](backends.md).

## Content digest

Each collected evidence item records a `content_digest` (SHA-256 of the exact
summary the model was shown), witnessed in the trace, so an auditor can confirm
*what content the run used* — see [`threat-model.md`](threat-model.md).

## Related

- [`architecture.md`](architecture.md) — how these fit into the pipeline.
- [`language-reference.md`](language-reference.md) — the syntax that expresses them.
