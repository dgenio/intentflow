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
governance mode, the verification checklist with stable rule ids, the
uncertainty policy, the output contract, trace configuration, and a *staged*
prompt plan (frame → evidence → model → verify → output). Staging matters:
each phase is a separate, governed interaction rather than one opaque
mega-prompt, so the runtime can gate between phases.

Semantic validation runs before plan emission: missing objectives,
conflicting action policies, malformed uncertainty rules, and out-of-range
confidence thresholds are errors; missing evidence or verification sections
are warnings.

### Plan → Execution (`runtime.py`)

The runtime is an explicit phase machine. Today all cognition is mocked
deterministically, which is a feature, not a stopgap: it lets the control
structure — evidence gating, escalation, discriminating tests, verification
failures — be tested end to end without network access or flaky model
output. A real LLM backend must keep the same phase contract and trace
format and replace only the mocked cognition.

Two invariants the runtime maintains:

1. **The trace is append-only and complete.** Every phase, every rule
   evaluation, every escalation, and every check lands in the trace with a
   sequence number. The trace is part of the result, not a side channel.
2. **Uncertainty actions are control flow.** `ask_human` produces an
   escalation record (simulated approval today, a blocking interaction
   tomorrow); `run_discriminating_test` mutates hypothesis confidences and
   re-ranks. Rules without a simulator are recorded, never silently dropped.

## Future directions

- **Real LLM backend.** A `runtime` implementation that drives the staged
  prompt plan against an actual model, parsing structured hypothesis /
  confidence / citation output and feeding it through the same uncertainty
  and verification machinery. The simulator becomes the conformance test for
  this backend.
- **Tool adapters.** `allow read_logs` should bind to a registered, sandboxed
  tool with a schema. `require_approval` becomes a real blocking gate; `deny`
  becomes unreachable code for the agent, enforced outside the model.
- **Memory/context compiler.** Lower `context:` policy into concrete
  behavior: retrieval priorities for `prefer`, eviction immunity for
  `preserve`, hard budget enforcement for `max_tokens`.
- **Confidence calibration.** Raw model self-reported confidence is known to
  be miscalibrated. A calibration layer (held-out scoring, ensembling,
  verifier models) should map reported confidence to calibrated confidence
  before uncertainty rules fire.
- **Static analysis for unsafe actions.** Flag plans where a
  destructive-looking action is allowed without any verification rule
  touching it, where escalation thresholds make `ask_human` unreachable, or
  where evidence requirements cannot support the declared outputs.
- **Graph execution.** Goals as nodes in a DAG with typed hand-offs: the
  verified output of one goal becomes evidence for the next, with trace
  continuity across the graph.
- **Python integration.** An embedding API (`intentflow.load(...).run(...)`)
  plus the inverse: registering Python functions as governed actions.
- **Compiler optimizations.** Because cost, latency, and risk are visible in
  the IR, they are optimizable: token-budget-aware evidence ordering, phase
  fusion when no gate separates them, early-exit when confidence already
  exceeds every threshold, and risk-weighted scheduling of approval gates.
