# IntentFlow Design Principles

## 1. Python programs deterministic computation; IntentFlow programs governed cognition

"Program" is a verb. Python tells a machine exactly what to do; IntentFlow
tells a reasoning process what it must gather, what it may do, how it will
be checked, and when it must stop. The two compose: Python can load and run
IntentFlow goals; IntentFlow goals can call Python functions as governed
actions.

## 2. Governance is program text, not prose

`require_approval post_comment` is not a sentence a model might ignore. It
compiles into a policy the `ActionGate` enforces *outside the model*. The
model never sees the gate and cannot talk its way past it. Anything that
matters — evidence requirements, action policy, verification, escalation —
must be diffable, reviewable, and lintable source code.

## 3. The plan is inspectable before any model runs

`intentflow compile` shows exactly what the agent will be allowed and
required to do: the staged prompt plan (one block per concern), the action
policy, the risk profile, the output schema, the execution phases. A
reviewer reads the plan, not the vibes.

## 4. The runtime is a phase machine with honest statuses

Every run moves through the same 13 phases and ends in exactly one of six
statuses. A failed verification is `failed_verification`, never a quiet
`completed`. A human escalation is `needs_human`, not a log line. A policy
block is `blocked`, not an exception swallowed somewhere.

## 5. Uncertainty is control flow

`if confidence < 0.65 ask_human` is not a prompt suggestion. Raw model
confidence is calibrated first, then thresholds fire, then the run's status
changes. Asking a human is a *normal, first-class outcome* of a governed
process — not a failure mode.

## 6. Two trust tiers, never merged

A machine check (schema conformance, citations, thresholds) is a proof. A
judged check (an LLM judging tone or claims) is an opinion with a named
source. They are computed, reported, and traced separately. With no judge
configured, judged checks are *skipped*, never assumed to pass.

## 7. The trace is a witness

Every run emits an append-only, hash-chained trace: every phase, gate
decision, approval, rule evaluation, check result, and escalation.
`intentflow audit` replays a result against the recompiled plan and proves
— without trusting the runtime, the backend, or the model — that the run
stayed inside its envelope. `intentflow replay` renders any saved trace as
a readable story.

## 8. Deterministic by default

The default backend simulates cognition deterministically and honors the
typed output schema, so the *control structure* of the language is testable
end to end — in CI, with no keys, no network, no flakiness. Real backends
slot into the identical governance path.

## 9. Diagnostics are a product surface

The analyzer's coded diagnostics (IFLOW001–022) carry severity, position,
and a suggestion. A language earns its keep when it catches the policy
contradiction (`allow X` + `deny X`), the unreachable escalation, and the
ungated side effect *before* anything runs.

## 10. No fake claims

If a rule cannot be evaluated, the trace says "recorded, not evaluated". If
a check needs a judge and none is configured, it is "skipped". The
simulator labels every value `[simulated]`. The honest answer is part of
the design.
