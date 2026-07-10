# security_alert — security-alert triage pipeline

**Domain:** security operations · **Audience:** security engineers

A two-stage governed **pipeline**: first classify whether an alert is a likely
true positive, then recommend a proportional containment response. The second
stage builds on the first stage's output as evidence.

## Why these governance choices

- **Composition.** Triage and response are separate goals with separate
  envelopes, composed by the `SecurityAlertResponse` pipeline. Each stage is
  independently auditable; the recommendation stage cannot run without the
  triage stage's result.
- **`distrust attacker_controlled_input`** in both stages — log content is
  potentially attacker-influenced and must never be sole support.
- **Response stage envelope:** **`allow search_repo`** (read-only context),
  **`require_approval disable_account`** (containment that affects a user is
  gated), **`deny wipe_host`** (irreversible destruction is forbidden outright).
- **`response must include a rollback path`** — containment must be reversible;
  a recommendation without one fails verification.
- **`if security_risk ask_human`** in both stages — a security signal always
  escalates. The pipeline ends `needs_human`, routing a real incident to a
  person with a full, tamper-evident trace of the reasoning.
- **`requires_approval: boolean`** in the output makes the gating decision an
  explicit, typed field.

## Run it

```bash
intentflow run examples/gallery/security_alert/program.iflow \
    --pipeline SecurityAlertResponse \
    --workspace examples/gallery/security_alert/workspace --trace-dir traces
intentflow audit traces/<latest>.json
```
