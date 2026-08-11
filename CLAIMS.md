# IntentFlow v0 claims and evidence

IntentFlow v0 is a **legacy/experimental reference implementation**. This file records what the current code is intended to establish, what evidence supports each statement, and what it explicitly does not claim.

For the falsification-first v1 research programme, see [`INCUBATION.md`](INCUBATION.md) and [`ROADMAP.md`](ROADMAP.md).

## Claim vocabulary

These words are intentionally distinct:

- **integrity** — the recorded artifact has not changed relative to the integrity mechanism being checked;
- **authenticity** — a configured signature/key identity validates the authenticated bytes;
- **conformance** — the bundled auditor's implemented checks accept the supplied plan/result under its documented assumptions;
- **observed execution** — the reference runtime recorded that a call passed through its own mediation path;
- **external truth** — an external system or evidence source actually behaved or reported truthfully;
- **correctness** — the agent's reasoning, result, policy, or business decision was semantically correct.

A v0 conformant artifact is **not** automatically proof of external truth or correctness.

## Implemented claims

### Action-name policy is enforced for calls routed through `ActionGate`

**Statement**

For tool calls invoked through the reference `ActionGate`, actions declared denied or absent from the allowed/approval-gated sets are blocked before the registered handler is called. Approval-gated actions use the configured approver path.

**Evidence**

- implementation: `intentflow/tools.py` (`ActionGate`);
- tests: action-gate / approval tests under `tests/`;
- runtime integration: `intentflow/runtime.py` evidence collection routes registered tools through the gate.

**Assumptions / exclusions**

- complete mediation exists only for calls actually routed through this gate;
- v0 does not prove that arbitrary application code, another process, or an external tool server cannot perform the same mutation outside the gate;
- action-name authorization is not the same as exact argument/request binding.

### Explicit verification failures do not resolve to `completed`

**Statement**

When a v0 verification check returns an explicit `fail`, the reference runtime resolves the run as `failed_verification` unless a higher-priority blocked/backend status applies.

**Evidence**

- implementation: `GoalRuntime._verify_output()` and `_resolve_status()` in `intentflow/runtime.py`;
- bundled auditor includes status/check-consistency checks.

**Known limitation**

Issue #160 tracks the current gap where a declared mandatory check may be `skipped`/unevaluable and therefore not count as an explicit failure. Until #160 lands, do **not** interpret `verification.passed=true` as proof that every declared mandatory rule was evaluated.

### `ask_human` does not fabricate human authority

**Statement**

A triggered v0 `ask_human` uncertainty action records an escalation and resolves the run to `needs_human`; current `main` does not insert an invented human approval response.

**Evidence**

- implementation: `GoalRuntime._execute_uncertainty_action()` in `intentflow/runtime.py`;
- issue #54 was re-audited and closed after the original fabricated-response premise no longer matched current code.

**Assumptions / exclusions**

- v0 does not currently turn uncertainty escalation into a durable suspend/resume human workflow;
- `needs_human` is a status, not evidence that a human answered.

### Trace chain detects post-hoc edits when the chain is not recomputed

**Statement**

The bundled trace integrity mechanism can detect changes that break the recorded hash chain. Optional configured signatures can additionally authenticate the sealed artifact under their documented key assumptions.

**Evidence**

- implementation: `intentflow/trace.py`, signing helpers, and auditor trace checks;
- demo/tests include deliberate artifact mutation cases.

**Assumptions / exclusions**

- an unsigned hash chain is an integrity structure, not proof of who produced it;
- a party able to rewrite an unsigned artifact may recompute an unsigned chain;
- signatures authenticate bytes/key identity, not the truth of external evidence or correctness of the agent's reasoning.

### The bundled auditor performs selected consistency/conformance checks offline

**Statement**

Given supported v0 plan/result artifacts, the bundled auditor can recompute and check the specific invariants implemented in `intentflow/auditor.py`, including selected action, evidence, status, version, trace-chain, and signature consistency properties.

**Evidence**

- implementation: `intentflow/auditor.py`;
- adversarial/tamper tests under `tests/` and the tamper demo.

**Assumptions / exclusions**

- the v0 auditor is part of the same project and shares formats/design assumptions with the runtime;
- it is not an organizationally or independently specified verifier implementation;
- it cannot prove complete mediation, external API truth, the semantic correctness of model output, or properties for which no check is implemented.

### Core installation has no mandatory third-party runtime dependency

**Statement**

The base package is designed to install without provider/signing dependencies; integrations are opt-in extras.

**Evidence**

- `pyproject.toml` dependency policy;
- dependency-policy and install-smoke CI/tests.

## Partial / advisory behavior

### Context policy

Some context declarations influence prompt construction and analyzer/runtime behavior, but they should not be described as a complete formally enforced context-isolation system.

### `distrust` evidence stance

The stance is represented in prompt/runtime metadata, but any machine-enforcement claim must be limited to the checks actually implemented. Do not equate a prompt instruction with a formal source-trust proof.

### Judged verification

Judged rules use a model judge when configured. A judge result is a separate trust tier and is not a machine proof. Without a judge, current v0 may record a rule as skipped; #160 governs fail-closed completeness for mandatory verification.

### Confidence calibration

The current shrinkage mapping is a deterministic transform, not empirical proof of probabilistic calibration. Do not describe v0 confidence as statistically calibrated without an external calibration experiment.

## Explicit non-claims

IntentFlow v0 does **not** claim to prove:

- an LLM's private reasoning is correct;
- external evidence is true;
- GitHub, MCP servers, model providers, or other external systems executed exactly as claimed beyond the configured observations;
- every possible action path is completely mediated;
- an approval applies to exact arguments unless the specific integration binds those arguments;
- a hash chain alone provides producer authenticity;
- every process crash or storage failure produces a complete durable witness;
- the bundled auditor is an independently developed verifier;
- all natural-language verification rules are machine-enforced;
- fixed shrinkage confidence is empirically calibrated;
- v0 is an industry standard or formally verified system.

## v1 hypotheses are not v0 claims

The v1 programme is testing whether a much narrower portable action-assurance contract can add useful exact request/approval/receipt/postcondition semantics beyond a strong policy + signed-attestation baseline.

Those artifacts and stronger claims are **experimental hypotheses** until the category kill gate in #149 passes. See:

- [`INCUBATION.md`](INCUBATION.md);
- [`ROADMAP.md`](ROADMAP.md);
- [`docs/v1-baseline-experiment.md`](docs/v1-baseline-experiment.md).

## Maintenance rule

When public wording uses terms such as **prove**, **proof**, **independent**, **verified**, **calibrated**, or **every run**, reviewers should require a precise scope, executable evidence, and explicit assumptions. `tests/test_public_claims.py` guards a small set of retired overclaims in the README.