# IntentFlow architecture

## The conceptual stack

```text
Human intent
    ↓
IntentFlow source (.iflow)        — declarative, reviewable, diffable
    ↓
Cognitive IR                      — typed nodes: evidence, actions,
                                    uncertainty, verification, context
    ↓
Execution plan (JSON)             — the contract between language and runtime;
                                    inspectable before anything runs
    ↓
Agent runtime                     — phase machine: context → evidence →
                                    actions → model → uncertainty → verify → output
    ↓
LLM / tool calls                  — mocked today; governed adapters tomorrow
    ↓
Verification / trace / output     — checked result + append-only audit trace
```

Each layer narrows what the layer below is allowed to do. That is the point:
by the time a model is invoked, the *envelope* of acceptable behavior has
already been compiled, validated, and made visible.

## Layer notes

### Source → AST (`parser.py`, `iflow_ast.py`)

The grammar is deliberately line-based and small. A goal is a named block of
known sections; every statement keeps its line number so that diagnostics in
every later layer can point back at source. The syntactic AST (`Program`,
`Goal`, `Section`, `Statement`) stays close to the text.

### AST → Cognitive IR (`compiler.py` lowering)

Statements are lowered into typed nodes — `EvidenceRequirement` (with a
*stance*: require / prefer / distrust), `ActionPolicy` (allow / deny /
require_approval), `UncertaintyRule` (threshold or symbolic conditions
mapped to control-flow actions), `VerificationRule`, `ContextPolicy`,
`OutputSpec`. This IR is the heart of the project: it is a representation of
a *cognitive process under governance*, not a prompt string. Anything that
wants to analyze, optimize, or enforce agent behavior operates here.

### IR → Execution plan (`compiler.py`)

The plan is plain JSON: normalized objective, evidence by stance, actions by
governance mode, the verification checklist with stable rule ids and typed
checks, the uncertainty policy, the output contract, a **risk profile**
(level + factors derived from the action/verification policy), a trace policy,
and a *staged* prompt plan. The prompt plan has one inspectable block per
governance concern — `system`, `objective`, `evidence`, `actions_allowed`,
`actions_denied`, `verify`, `uncertainty`, `output` — instead of one opaque
mega-prompt, so *what the model is told about each concern* is diffable
before any model runs, and a backend assembles those blocks into a concrete
call (`backends.assemble_messages`).

Typed verification checks come in three machine-checkable flavors —
`cites_evidence`, `requires_phrase`, and `threshold_check`
(`check confidence >= 0.7`) — plus `judged` rules that need an LLM judge and
are recorded as skipped, never silently passed.

Semantic validation runs before plan emission: missing objectives,
conflicting action policies, malformed uncertainty rules, and out-of-range
confidence thresholds are errors; missing evidence or verification sections
are warnings.

### Plan → Execution (`runtime.py`, `backends.py`, `tools.py`)

The runtime is an explicit phase machine
(context → actions → evidence → model → uncertainty → verify → output).
Cognition is a pluggable backend behind one narrow, provider-agnostic
contract — ``propose(plan, evidence) -> Proposal`` — with three
implementations: deterministic simulation (the conformance reference; no
network, no flakiness), a real Claude backend, and an OpenAI-compatible
backend (OpenAI, Azure, or local servers such as vLLM/Ollama via
`OPENAI_BASE_URL`). All three assemble the same staged prompt plan and parse
the same strict-JSON reply, so adding a provider is one class and none can
opt out of governance. Governance is **not** pluggable. It lives outside the
backend:

1. **The ActionGate is the enforcement point.** Every tool invocation —
   including evidence collection from a workspace — goes through the gate,
   which consults the compiled action policy. Denied or unlisted actions
   raise; approval-gated actions fail closed without a grant; every
   decision is traced. The gate never reads model output, so the model
   cannot negotiate with it.
2. **Confidence is calibrated before rules fire.** Backends report raw
   confidence; the runtime applies the plan's calibration policy (a
   shrinkage placeholder today, a learned map later) and uncertainty rules
   evaluate the calibrated value. Both numbers appear in the trace.
3. **Verification is typed.** The compiler classifies each rule as
   machine-checkable (`cites_evidence`, `requires_phrase`) or judged.
   Machine checks are evaluated against structured state; judged checks are
   recorded as *skipped* — never silently assumed to pass.
4. **The trace is append-only and complete.** Every phase, rule
   evaluation, escalation, gate decision, and check lands in the trace with
   a sequence number, as an independent snapshot (never a live reference to
   mutable state).
5. **Uncertainty actions are control flow.** `ask_human` produces an
   escalation record; `run_discriminating_test` mutates hypothesis
   confidences and re-ranks. Rules without an evaluator are recorded, never
   silently dropped.

### Composition (`pipeline` blocks)

Goals compose into linear pipelines. A later stage may require
``GoalName.field`` as evidence; the compiler statically checks that the
named goal runs earlier and declares that output. At runtime the upstream
output value is seeded as evidence (origin ``pipeline:GoalName``), and the
combined trace tags every event with its stage.

### Execution → Audit (`auditor.py`)

This is the layer that makes the whole stack more than a config schema.
The program is a **contract**; the trace is a **witness**; the auditor is
an **independent verifier**. ``intentflow audit`` recompiles the source and
replays a result against it, checking: no denied action ran (A3), gated
actions have prior approval grants (A2), only allowed actions ran (A1), the
trace is append-only and in canonical phase order (T1/T2), the trace hash
chain is intact and any HMAC signature verifies (T3), citations point at
collected evidence (E1), every uncertainty rule was evaluated or recorded
(U1), every verification rule was checked and no failure was hidden from the
result (V1), and the output contract was met exactly (O1).

Because the auditor needs only the source and the result JSON, conformance
can be verified without trusting the runtime, the backend, or the model —
proof-carrying agent behavior, in the spirit of audit logs + seccomp
profiles for processes.

### Trust tiers, gates, and tamper-evidence

Three mechanisms keep the runtime honest beyond the plan:

- **Approval channels** (`tools.py`). An approval-gated action consults an
  ``Approver`` — pre-grant, blocking TTY prompt, or synchronous webhook — and
  blocks until it decides. The decision and its channel are traced; no
  decision means denied (fail closed).
- **The judge tier** (`judges.py`). `judged` verification rules can be run by
  an LLM ``Judge``, but their verdicts live in a **separate tier**: each
  carries the judge's name and a rationale, and the verification result keeps
  ``machine`` and ``judged`` tallies apart so a proof is never confused with a
  model's opinion. Without a judge, judged rules are recorded as *skipped*.
- **Hash-chained traces** (`runtime.Trace`). Each event stores
  ``sha256(prev_hash || canonical(event))``; the auditor recomputes the chain
  from genesis, catching accidental corruption, truncation, or reordering with
  no plan required. The links live in the trace, so the bare chain is integrity,
  not authenticity — a forger could recompute it. ``--sign-trace`` HMAC-seals
  the root out of band, so a key holder can *detect* (not prevent) edits.

### Embedding (`api.py`)

``intentflow.load(...)`` exposes the whole stack to Python:
``validate`` / ``compile`` / ``inspect`` / ``run`` / ``run_pipeline``, plus
``register_tool`` to expose a Python function as a governed action. Registered
tools still run *through the action gate*, so Python interop never bypasses
governance. Recorded **cassettes** (`backends.py`) capture a real model's raw
replies once and replay them deterministically, giving the real
parsing/governance path CI coverage without credentials.

## Future directions

Roadmap ownership now lives in [ROADMAP.md](../ROADMAP.md).

This document stays focused on architecture and runtime contracts.
