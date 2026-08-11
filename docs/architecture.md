# IntentFlow v0 architecture

This document describes the **legacy/experimental v0 reference implementation**. Architecture descriptions are bounded by the implemented checks and assumptions in [`../CLAIMS.md`](../CLAIMS.md) and [`limitations.md`](limitations.md). The narrower v1 research programme is described in [`../INCUBATION.md`](../INCUBATION.md).

## The conceptual stack

```text
Human intent
    ↓
IntentFlow source (.iflow)        — declarative, reviewable, diffable
    ↓
Static analyzer                   — coded diagnostics (IFLOW001–022)
    ↓
Cognitive IR                      — typed nodes: evidence, actions,
                                    uncertainty, verification, context, output schema
    ↓
Execution plan (JSON, v0.2)       — reference contract between language/runtime;
                                    inspectable before anything runs
    ↓
Reference runtime                 — 13-phase machine: parse → analyze → compile →
                                    prepare_context → collect_evidence →
                                    build_messages → call_backend → parse_output →
                                    verify_output → apply_uncertainty_policy →
                                    enforce_action_policy → finalize → trace
    ↓
LLM / mediated tool calls         — simulated by default; supported real backends use
                                    the same reference-runtime path
    ↓
Result + explicit status          — completed | needs_human | blocked |
                                    failed_validation | failed_verification |
                                    backend_error, plus optional trace artifacts
```

The layers make governance intent explicit and move some controls outside prompt prose. They do **not** prove that every application/external action path is mediated or that external evidence/actions are truthful.

## Layer notes

### Source → AST (`parser.py`, `iflow_ast.py`)

The grammar is deliberately line-based and small. A goal is a named block of known sections; every statement keeps its line number so diagnostics in later layers can point back at source. The syntactic AST (`Program`, `Goal`, `Section`, `Statement`) stays close to the text.

### AST → Cognitive IR (`compiler.py` lowering)

Statements are lowered into typed nodes — `EvidenceRequirement` / `EvidencePolicy` (stances: require / optional / prefer / distrust), `ActionRule` / `ActionPolicy` (allow / deny / require_approval), `UncertaintyRule` (threshold or signal conditions mapped to control-flow actions), `VerificationRule` / `VerificationPolicy`, `ContextPolicy`, `GoalMetadata`, `RiskProfile`, `PromptPlan`, and a typed `OutputSchema` (`OutputField` with base type, optionality, list item types).

The analyzer (`analyzer.py`) runs between parsing and compilation and powers `intentflow validate`. This IR is a representation of the governance declarations understood by the v0 compiler/runtime; it should not be mistaken for a formal model of cognition or proof that every declaration is enforced with the same strength.

### IR → Execution plan (`compiler.py`)

The plan is plain JSON: normalized objective, evidence by stance, actions by governance mode, the verification checklist with stable rule ids and typed checks, uncertainty policy, output contract, a derived risk profile, trace policy, and a staged prompt plan.

The prompt plan keeps concerns inspectable — `system`, `objective`, `evidence`, `actions_allowed`, `actions_denied`, `verify`, `uncertainty`, `output` — instead of one opaque mega-prompt. This improves reviewability; prompt text itself is not enforcement.

Verification declarations include implemented machine-check forms such as `cites_evidence`, `requires_phrase`, and `threshold_check`, plus `judged` rules. Judged rules require a judge to be evaluated and otherwise appear as skipped. **Known v0 gap:** #160 tracks that skipped/unevaluable mandatory rules can currently leave the overall checklist marked passed.

Semantic validation runs before plan emission for supported static errors/warnings. Analyzer coverage is intentionally finite; passing validation is not a complete policy/security proof.

### Plan → Execution (`runtime.py`, `backends.py`, `tools.py`)

The runtime is an explicit 13-phase reference machine with six handled statuses. Cognition is a pluggable backend behind `respond(plan, evidence, system, user) -> BackendResponse` (raw text, parsed JSON, model name, latency, token usage, finish reason). Implementations include deterministic simulation, a mock backend, supported real model backends, and cassette replay.

All supported backends feed the same reference runtime. This prevents a backend implementation from choosing the runtime's ActionGate result, but it does **not** establish complete mediation outside the reference application path.

External model/judge calls use explicit timeout/retry controls in `reliability.py`. Exhausted retries become backend errors rather than partial successes. Parsing/judge behavior also contains bounded defensive handling. These are reliability properties of the reference implementation, not formal guarantees about provider services.

Governance behavior lives outside the cognition backend where v0 implements it:

1. **ActionGate mediation.** Registered tool calls made through `ActionGate` are checked against allowed, approval-required, and denied action names. Denied/unlisted actions are blocked before the handler runs. This guarantee applies only to mediated calls; other credentials/SDK/process paths are outside it.
2. **Confidence transformation.** The runtime applies a deterministic shrinkage mapping before uncertainty thresholds. The raw and transformed values can be recorded. The map is a control-flow transform, **not empirical probabilistic calibration**.
3. **Verification records.** Implemented predicates evaluate structured run state; judged rules use a separate model-judge tier when configured. A machine-evaluated predicate is evidence about that predicate only, not proof of semantic correctness or external truth. #160 covers mandatory skipped-check completeness.
4. **Trace recording.** Events successfully recorded by the reference runtime are ordered/hash-linked and snapshot their detail at record time. Process/host/storage failures can still produce incomplete or missing artifacts; avoid calling the trace universally complete.
5. **Uncertainty control flow.** `ask_human` marks the run `needs_human`; current `main` does not fabricate an approval response. `block_action` marks the run blocked. `needs_human` means unresolved human review is required, not that a human answered.

### Zero-runtime-dependency core

The core package is intentionally stdlib-only. `pyproject.toml` keeps base runtime dependencies empty; provider/signing/test tooling lives behind optional extras or maintainer dependency groups.

The import policy is enforced by repository tests. This is a packaging/supply-chain property and does not imply that optional integrations or external services are dependency-free.

### Composition (`pipeline` blocks)

Goals compose into linear pipelines. A later stage may require `GoalName.field` as evidence; the compiler checks supported declaration relationships, and runtime output can be seeded into later-stage evidence.

This is reference workflow composition, not a distributed transaction or formal workflow-correctness guarantee.

### Execution → Audit (`auditor.py`)

The bundled auditor is a **v0 consistency/conformance checker**, not an independently developed formal verifier.

It recompiles supported source and checks the invariants implemented in `intentflow/auditor.py`, including selected properties around:

- action allow/deny/approval records;
- trace order/hash links and configured signatures;
- citations/evidence relationships;
- uncertainty-rule/check coverage as implemented;
- reported status/check consistency;
- supported format versions;
- output-schema consistency.

A conformant verdict means those bundled checks accepted the supplied artifacts under their assumptions. Because the auditor and runtime share project formats/design vocabulary, they may share conceptual defects.

The auditor does **not** establish, by itself:

- complete mediation of all external action paths;
- external API/evidence truth;
- correctness of LLM reasoning;
- correctness of GitHub/MCP/provider implementations;
- exact request-bound authorization beyond the binding implemented by a specific integration;
- completeness of mandatory verification while #160 remains open.

The v1 programme specifically tests whether a smaller portable action-assurance artifact plus genuinely independent verification adds value beyond a strong policy/signed-attestation baseline.

### Trust tiers, approval, and trace integrity

Three mechanisms are distinct:

- **Approval channels (`tools.py`).** Approval-gated `ActionGate` calls can consult pre-grant, TTY, webhook, or callback approvers. These are implementation-level action approvals. They are not yet a portable proof that approval was bound to every exact argument, tool descriptor, state, receipt, and postcondition.
- **Judge tier (`judges.py`).** Judged verification can use a model judge with named rationale. It remains an opinion from another model, not a deterministic proof. Without a judge, the v0 rule is skipped; #160 tracks the overall completeness consequence.
- **Trace integrity/signing (`trace.py`, `signing.py`).** Hash links can detect edits that do not recompute the chain. Unsigned chains provide an integrity structure, not producer authenticity. Configured HMAC/Ed25519 signatures can authenticate supported sealed bytes under their key-management/crypto assumptions. They do not prove the recorded external facts are true.

`--trace-stream` can flush a hash-linked JSONL prefix as events occur. A crash may leave a valid prefix, but a process/host/storage failure can also prevent complete durable recording; a prefix is not a complete-run proof.

### Embedding (`api.py`)

`intentflow.load(...)` exposes validation/compile/inspect/run/pipeline and tool-registration APIs to Python. Registered tools routed through the runtime still use the ActionGate. Application code can still create out-of-band paths, so embedding does not make complete mediation automatic.

Recorded cassettes can replay captured model responses for deterministic regression testing. They test the reference parsing/governance path against recorded responses; they are not evidence that future real-model behavior is identical.

## v0/v1 boundary

v0 remains useful as a research/reference implementation for explicit governance declarations, mediated action-name gates, run-state recording, and adversarial lessons.

v1 is not a feature-completion roadmap for v0. It starts by building the strongest policy/request/approval/receipt/signed-attestation baseline, attacking it, and only retaining new portable semantics if a material assurance gap survives. See [`../ROADMAP.md`](../ROADMAP.md) and [`../INCUBATION.md`](../INCUBATION.md).

## Future directions

Roadmap ownership lives in [ROADMAP.md](../ROADMAP.md). This document stays focused on the current reference architecture and its trust boundaries.