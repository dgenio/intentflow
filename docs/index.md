# IntentFlow

**An experimental language for governed LLM workflows.** Compile goals,
evidence, uncertainty, actions, and verification into an auditable agent plan —
then prove, after the fact, that a run stayed inside its contract.

IntentFlow programs are **contracts**; run traces are **witnesses**; anyone can
**audit** a witness against the contract without trusting the runtime that
produced it.

## Start here

- **[Quickstart](quickstart.md)** — install to an audited run in five minutes,
  ending with hand-tampering a trace and watching the auditor catch it. No key,
  no network.
- **[Concepts](concepts.md)** — contract, witness, envelope, trust tiers,
  calibration, conformance.
- **[Language reference](language-reference.md)** — every section, statement
  form, and diagnostic.
- **[Embedding](embedding.md)** — drive IntentFlow from Python.
- **[Ecosystem — where IntentFlow fits](ecosystem.md)** — how it relates to
  orchestration frameworks, guardrails, and policy engines.

## Why it exists

Classical languages describe deterministic procedures. IntentFlow describes
*governed cognitive processes*: what evidence is required, which actions are
allowed or gated, how uncertainty escalates, and what the output must satisfy —
as language semantics, not prompt text. The [architecture](architecture.md)
walks the pipeline from source to witness.
