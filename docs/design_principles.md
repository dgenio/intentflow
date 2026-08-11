# IntentFlow v0 Design Principles

These principles describe the **legacy/experimental v0 reference runtime**. They are design intentions bounded by the implemented checks and assumptions documented in [`../CLAIMS.md`](../CLAIMS.md) and [`limitations.md`](limitations.md), not claims of formal verification or an interoperability standard.

## 1. Make governance intent explicit and inspectable

IntentFlow v0 lets a developer write down what a reference agent process should gather, what mediated actions it may request, how outputs are checked, and when the run should escalate or stop. Python can load and run IntentFlow goals; IntentFlow goals can call registered Python functions through the reference action gate.

## 2. Put enforceable controls outside prompt prose where v0 implements them

`require_approval post_comment` compiles into an action policy enforced by the reference `ActionGate` for calls routed through that gate. The model does not decide that gate's allow/deny result. Evidence requirements, action policy, verification declarations, and escalation rules are diffable, reviewable, and lintable source.

This does **not** prove complete mediation: application/tool paths outside the gate remain outside this guarantee.

## 3. Inspect the plan before a model runs

`intentflow compile` shows the staged prompt plan, action policy, risk profile, output schema, and execution phases before the reference runtime invokes cognition. This gives reviewers a concrete artifact to inspect rather than leaving all policy intent implicit in application code and prompts.

## 4. Use explicit runtime statuses

Handled runs move through the reference phase machine and resolve to an explicit status such as `completed`, `needs_human`, `blocked`, `failed_validation`, `failed_verification`, or `backend_error`.

An explicit verification `fail` does not silently become `completed`. **Known v0 limitation:** #160 tracks that a declared mandatory rule may currently be `skipped`/unevaluable without forcing overall verification failure. Until that is fixed, inspect individual check statuses rather than treating `verification.passed=true` as proof of complete mandatory verification.

## 5. Treat uncertainty as visible control flow

A rule such as `if confidence < 0.65 ask_human` can change the run status rather than existing only as prompt prose. v0 applies its configured deterministic confidence transformation before threshold rules fire.

The current shrinkage mapping is **not** empirical evidence of statistically calibrated probability. A `needs_human` status means the run requires human review; it is not evidence that a human has answered or approved.

## 6. Keep deterministic checks and judged opinions distinct

Machine-evaluated checks (for example schema conformance, implemented citation checks, or supported thresholds) and model-judged rules are reported as separate trust tiers.

A deterministic check result is evidence that the **implemented predicate** evaluated that artifact as pass/fail. It is not automatically a proof of semantic correctness, external truth, or properties the predicate does not encode.

With no judge configured, judged checks are recorded as skipped rather than silently labelled as judged-pass. #160 governs the remaining overall-completeness problem for skipped mandatory rules.

## 7. Treat the trace as an inspectable integrity record

Runs that successfully record trace output can emit an append-only, hash-chained event record containing phases, gate decisions, approvals, rule evaluations, check results, and escalations. Optional configured signatures can authenticate supported artifacts under their documented key assumptions.

`intentflow audit` is the **bundled v0 consistency/conformance checker**. It can recompute selected invariants implemented in `intentflow/auditor.py` and detect supported post-hoc inconsistency/tamper classes. It is developed in the same project and shares v0 formats/design assumptions with the runtime; it does not prove complete mediation, external execution/truth, or model reasoning correctness.

`intentflow replay` renders a saved trace as a readable story.

## 8. Keep the control structure reproducible by default

The default backend simulates cognition deterministically and honors the typed output schema, so the reference control structure can be exercised end to end in CI with no keys or network. Real backends use the same reference-runtime path, subject to the external/network assumptions documented in the limitations.

Simulation evidence is not evidence about real-model quality or production outcomes.

## 9. Treat diagnostics as a product surface

The analyzer's coded diagnostics carry severity, position, and suggestions. Static checks can catch supported contradictions and suspicious declarations before the reference runtime executes a goal.

Diagnostics are bounded by the rules actually implemented; they are not a complete policy or security proof.

## 10. Prefer explicit non-claims to silent strengthening

If the runtime cannot evaluate a rule, the per-check record should make that visible. If a judge is absent, judged rules are skipped rather than invented. The simulator labels simulated values.

The remaining v0 gaps belong in [`limitations.md`](limitations.md) and issue tracking rather than being hidden behind stronger language. The v1 programme deliberately starts by comparing against a strong existing-policy/attestation baseline before adding new protocol semantics.