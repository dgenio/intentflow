# Concepts and glossary

This glossary describes the **legacy/experimental v0 reference implementation**. For exact positive claims, assumptions, and non-claims, see [`../CLAIMS.md`](../CLAIMS.md) and [`limitations.md`](limitations.md).

## Program as reference-runtime contract

An `.iflow` program declares an objective, evidence requirements, action-name policy, verification rules, uncertainty handling, and a typed output schema. The compiler (`intentflow/compiler.py`) lowers it to an inspectable execution plan before a model runs.

Calling the program a **contract** means the v0 compiler/runtime has explicit structured declarations to interpret. It does not mean every declaration is formally verified or that every external action path is completely mediated.

## Trace as witness record

A successfully recorded run can emit a structured result plus a hash-chained trace of reference-runtime events (`intentflow/trace.py`, `intentflow/runtime.py`). The record is designed to be replayed and checked offline by the bundled auditor.

“Witness” in v0 means **inspectable recorded evidence under documented assumptions**, not proof that external evidence was truthful or every external system behaved correctly.

## Action envelope

The reference action envelope is the set of action names declared allowed, denied, or approval-required. The `ActionGate` (`intentflow/tools.py`) checks registered calls routed through it and does not use model output to decide allow/deny.

A model cannot widen the gate's policy through prompt output. However, v0 does not prove complete mediation: application code, credentials, or mutation paths outside the gate remain outside this guarantee.

## Trust tiers: machine vs judged

Verification records two distinct kinds of result:

- **Machine-evaluated** rules are checked deterministically by implemented runtime predicates.
- **Judged** rules can be delegated to an LLM judge when configured and remain a separate trust tier.

A machine-evaluated pass means the implemented predicate passed; it is not automatically proof of semantic correctness or external truth. A judged result is a model opinion, not a deterministic proof.

Without a judge, judged rules are recorded as skipped. Issue #160 tracks the v0 gap where skipped/unevaluable mandatory rules may not force overall verification failure.

## Confidence transformation

The simulator/runtime can apply a deterministic shrinkage mapping to raw confidence before threshold rules. This is useful for reproducible control flow.

The mapping is **not empirical evidence of statistically calibrated probability**. Public wording should call it a confidence transformation/shrinkage map unless a separate calibration study establishes more.

## Escalation

When an `uncertainty:` condition triggers `ask_human`, current v0 records an escalation and resolves the run to `needs_human`; it does not fabricate a human approval response.

`needs_human` means human review remains required. It does not establish that a human answered, approved, or completed a durable suspend/resume workflow.

## v0 conformance

A v0 artifact is **conformant** when the bundled auditor's implemented checks accept it under the documented assumptions and supported format versions.

The current check vocabulary includes selected properties such as:

| Code | Bundled check |
|------|--------|
| A1 | invoked action names are compatible with the plan |
| A2 | approval-gated invocations have the required recorded grant |
| A3 | denied action names are not recorded as invoked |
| T1/T2 | supported trace sequence/phase ordering properties |
| T3 | hash-chain and configured signature/seal checks |
| E1 | citation/evidence consistency |
| U1 | uncertainty-rule coverage as implemented |
| V1 | verification-record consistency as implemented |
| S1 | reported status consistency as implemented |
| O1 | output/schema consistency |
| P1/P2 | goal/stage and supported-format-version checks |

The authoritative list is the module documentation/implementation in `intentflow/auditor.py`.

Conformance does **not** mean the auditor independently proves that the run “stayed inside” every real-world security boundary. The auditor and runtime share v0 formats/design assumptions, and the bundled checker cannot establish complete mediation, external truth, model reasoning correctness, or properties that are not encoded in its checks.

## Integrity vs authenticity vs truth

These are separate concepts:

- **Hash-chain integrity** — edits that do not recompute the chain break the recorded links.
- **Artifact authenticity** — configured HMAC/Ed25519 verification can authenticate supported sealed bytes to a key identity under cryptographic/key-management assumptions.
- **External truth/correctness** — whether evidence was true, an API behaved correctly, or the agent's conclusion was semantically right.

A bare unsigned hash chain is not producer authentication; a party able to rewrite the artifact may recompute an unsigned chain. A valid signature authenticates bytes/key identity, not the truth of the signed statement.

See [`trace-signing.md`](trace-signing.md) and [`limitations.md`](limitations.md).

## Cassette

A cassette records backend/judge responses so the reference parsing/governance path can be replayed deterministically in CI without API keys. Reproducible replay does not imply that future live-model behavior will be identical.

## Content digest

Collected evidence can carry a SHA-256 digest of the exact summary recorded for the model path. The digest helps bind the trace to the recorded content under the reference implementation.

A digest proves neither that the source content was truthful nor that the model interpreted it correctly.

## v0/v1 boundary

v0 terminology must not be silently upgraded into the stronger v1 research claims. v1 is testing whether a portable exact action/approval/receipt/postcondition assurance contract provides material value beyond a strong policy + signed-attestation baseline.

See [`../INCUBATION.md`](../INCUBATION.md) and [`v1-baseline-experiment.md`](v1-baseline-experiment.md).

## Related

- [`architecture.md`](architecture.md) — current reference architecture and trust boundaries.
- [`language-reference.md`](language-reference.md) — v0 syntax.
- [`../CLAIMS.md`](../CLAIMS.md) — claims-to-evidence matrix.
- [`limitations.md`](limitations.md) — explicit non-claims and limitations.
