# IntentFlow architecture

## The conceptual stack

```
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
trace is append-only and in canonical phase order (T1/T2), citations point
at collected evidence (E1), every uncertainty rule was evaluated or
recorded (U1), every verification rule was checked and no failure was
hidden from the result (V1), and the output contract was met exactly (O1).

Because the auditor needs only the source and the result JSON, conformance
can be verified without trusting the runtime, the backend, or the model —
proof-carrying agent behavior, in the spirit of audit logs + seccomp
profiles for processes.

## Future directions

- **Blocking approval gates.** `--approve` pre-grants exist today; gated
  actions should also support interactive TTY prompts and webhook-style
  asynchronous approval, with the grant recorded in the trace either way.
- **Signed traces.** The auditor detects tampering relative to the plan;
  hash-chaining + signing each trace event would make witnesses
  tamper-*evident* on their own, enabling third-party audit of runs you
  did not execute.
- **Learned confidence calibration.** Replace the shrinkage placeholder
  with a calibration map learned from scored historical runs (held-out
  scoring, ensembling, verifier models), per backend and per domain.
- **Richer verification predicates.** Grow the machine-checkable vocabulary
  (`consistent_with(source)`, numeric bounds on outputs) and add an
  LLM-judge runner for judged rules — reported in a separate trust tier
  from machine checks, never merged with them.
- **Memory/context compiler.** Lower `context:` policy into concrete
  behavior: retrieval priorities for `prefer`, eviction immunity for
  `preserve`, hard budget enforcement for `max_tokens`.
- **DAG execution.** Pipelines are linear today with statically checked
  evidence chains; generalize to DAGs with fan-out/fan-in and the same
  static guarantees.
- **Python integration.** An embedding API (`intentflow.load(...).run(...)`)
  plus the inverse: registering Python functions as governed actions in the
  tool registry.
- **Compiler optimizations.** Because cost, latency, and risk are visible in
  the IR, they are optimizable: token-budget-aware evidence ordering, phase
  fusion when no gate separates them, early-exit when confidence already
  exceeds every threshold, and risk-weighted scheduling of approval gates.
