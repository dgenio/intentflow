# IntentFlow v0 limitations

IntentFlow v0 is a **legacy/experimental reference implementation**. This document describes the main boundaries that matter when interpreting its governance, verification, and trace artifacts.

For precise positive claims and evidence, see [`../CLAIMS.md`](../CLAIMS.md). For the narrower v1 research programme, see [`../INCUBATION.md`](../INCUBATION.md).

## Limitations matrix

| Area | What v0 does | Important limitation |
| --- | --- | --- |
| Action mediation | Calls routed through `ActionGate` are checked against allowed/approval-required/denied action names | It does not prove every possible application/tool path is mediated; action-name policy is not exact argument binding |
| Approval | Approval-gated `ActionGate` calls can use pre-grant, TTY, webhook, or callback approvers | The approval contract is a v0 implementation mechanism, not a portable exact-request assurance transaction |
| `ask_human` | A triggered rule records an escalation and resolves the run to `needs_human` | It is not a durable suspend/resume workflow and `needs_human` does not mean a human answered |
| Verification | Machine checks and optional judged checks produce per-rule records | Until #160 is fixed, a mandatory rule that becomes `skipped`/unevaluable may not force overall verification failure |
| Judged rules | A configured model judge can evaluate judged rules in a separate trust tier | A judge opinion is not a machine proof; without a judge a rule may be skipped |
| Confidence | The runtime applies a deterministic shrinkage mapping before threshold rules | This is not empirical/statistical calibration; the numeric value should not be presented as calibrated probability |
| Evidence trust | Evidence has provenance/stance metadata and untrusted content is structured for prompts | Prompt instructions and metadata do not prove source truth or prevent every prompt-injection effect |
| `distrust` | Distrusted sources are represented explicitly in the plan/runtime | Any enforcement claim is limited to machine checks actually implemented; do not generalize prompt guidance into formal trust guarantees |
| Context policy | Context declarations influence prompt planning and some analyzer/runtime behavior | v0 is not a complete context-isolation or information-flow enforcement system |
| Hash chain | Trace events are linked so post-hoc edits break the recorded chain unless links are recomputed | Unsigned chains establish internal integrity structure, not producer authenticity |
| Signatures | Optional HMAC/Ed25519 mechanisms can authenticate supported trace artifacts under configured keys | Signatures authenticate bytes/key identity, not semantic correctness or external truth |
| Bundled auditor | Recomputes selected v0 format/action/evidence/status/trace/signature consistency checks | It shares project formats/assumptions with the runtime and is not an independently developed standards verifier |
| External execution | Tool events record what the reference runtime observed/invoked through its path | A trace does not prove an external service behaved truthfully or that no out-of-band mutation occurred |
| Failure artifacts | Configured successful/handled paths can produce replayable artifacts; streamed traces can preserve valid prefixes | Process kill, host/storage failure, or failure before durable recording can still leave incomplete or missing artifacts |
| Pipelines | v0 can run linear composed stages and retain per-stage results/traces | This is not a general workflow engine or proof of distributed transaction semantics |
| Schemas/versioning | Plan/result formats have schemas/version checks | Schema validity is structural; it does not establish semantic safety or future standards compatibility |
| Simulation | Offline simulator exercises control structure deterministically | Simulated cognition/evidence behavior is not evidence about real-model quality or production outcomes |

## Complete mediation

The strongest v0 enforcement claim applies only to actions that actually pass through the reference `ActionGate`.

An application that exposes credentials, direct SDK clients, shell commands, or another mutation path outside that gate can bypass the v0 action-name policy entirely. v0 does not provide hardware/process isolation or prove that all actions in a deployment are forced through the gate.

## Approval binding

The current action gate records approval for an **action invocation**. That is useful operational control, but it should not be confused with a portable contract proving that an approval was cryptographically bound to every exact request argument, tool descriptor, relevant pre-state, execution receipt, and postcondition.

That stronger question belongs to the v1 falsification programme. The v1 programme must still prove that those extra semantics are necessary beyond a strong policy + signed-attestation baseline.

## Human escalation

Current `ask_human` behavior is deliberately conservative:

- it records the condition/question;
- it marks the run `needs_human`;
- it does not fabricate an approval response.

The remaining limitation is workflow completeness: v0 does not provide a durable state machine for requested/answered/denied/expired escalation. A `needs_human` result should be treated as unresolved human authority, not as approval.

## Verification completeness (#160)

Current v0 differentiates `pass`, `fail`, and `skipped` verification records. However, overall verification currently treats the absence of explicit `fail` as success. Therefore a declared mandatory check that becomes `skipped`—for example an unsupported metric or judged rule with no judge—can leave the overall checklist marked passed.

Until #160 lands:

- inspect individual check statuses;
- do not treat `verification.passed=true` as proof every declared mandatory rule was evaluated;
- do not describe successful v0 verification as complete mandatory-obligation proof.

This is the highest-priority remaining v0 correctness gap in the assurance story.

## Confidence is not empirically calibrated

The v0 shrinkage map is deterministic and useful for exercising control-flow thresholds. It has not, by itself, established statistical calibration against observed outcome frequencies. Public wording should call it a **confidence transform** or **shrinkage mapping**, not proof of calibrated probabilities.

## Trace integrity vs authenticity vs truth

These are separate properties:

1. **Hash-chain integrity** can reveal edits that do not recompute the chain.
2. **Configured signatures** can authenticate the sealed bytes to a key identity under cryptographic/key-management assumptions.
3. Neither property proves the external evidence was truthful, the model reasoned correctly, or the external action actually happened exactly as described.

A signed false statement is still a false statement.

## Bundled auditor trust boundary

The bundled auditor is useful because it can re-evaluate selected invariants without executing the model/tool path again. But it is developed in the same repository, shares the same v0 format vocabulary, and may share conceptual defects with the runtime.

Therefore describe it as a **bundled consistency/conformance checker**, not as an independently developed formal verifier.

The v1 programme requires stronger implementation independence before any standards-like claim.

## Evidence and prompt injection

Evidence is untrusted data. Structural delimiting, provenance, digests, and explicit prompt language reduce ambiguity and improve auditability, but they do not prove the model will never be influenced by adversarial evidence content.

Action gating remains a separate control and is only effective for mediated actions.

## Crash and durability limits

A configured trace stream can preserve a hash-chain-verifiable prefix when events were successfully flushed. This is not a guarantee that every process/host/storage failure produces a complete artifact.

Avoid phrases such as “every run always emits a witness” without stating the failure/storage assumptions.

## What v0 is useful for

Within these boundaries, v0 remains useful as:

- an experimental language/runtime for making governance declarations explicit;
- a reference implementation for action-name gating, trace recording, and offline replay/checking;
- a source of adversarial lessons for the narrower v1 action-assurance experiment;
- a research/demo environment for separating prompt guidance, deterministic checks, approval gates, and audit records.

It should not be sold as proof-carrying cognition, formal verification of agent reasoning, or a mature interoperability standard.

## Relationship to v1

v1 deliberately starts from the opposite direction: build the strongest existing-policy/attestation baseline first, attack it, and only introduce new portable semantics if a material assurance gap survives.

See:

- [`../INCUBATION.md`](../INCUBATION.md);
- [`../ROADMAP.md`](../ROADMAP.md);
- [`v1-baseline-experiment.md`](v1-baseline-experiment.md).