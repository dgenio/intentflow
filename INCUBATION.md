# IntentFlow incubation contract

IntentFlow v1 is an **incubating protocol/research hypothesis**, not a proven standard and not a commitment to preserve the current language/runtime architecture.

The objective is to discover the smallest useful interoperability/security primitive—or discover quickly that existing policy and attestation mechanisms are sufficient.

## Hypothesis

A portable action-assurance transaction can bind an agent action, approval, execution evidence, and relevant postconditions tightly enough that an independent verifier detects materially important replay, substitution, omission, downgrade, or completeness failures that a strong policy + signed-attestation baseline cannot cover cleanly.

The hypothesis is about **portable assurance artifacts and verification**, not about the `.iflow` language.

## Strong baseline

Before adding new IntentFlow-specific semantics, compare against a deliberately strong composition containing, where relevant:

- policy/plan decision and identity;
- exact action/request bytes or digest binding;
- approver identity, validity, scope, and single-use nonce;
- execution receipt;
- relevant pre-state/postcondition observation;
- signed structured attestation/envelope using established primitives where practical.

The baseline is a real competitor. Do not weaken it to manufacture differentiation.

## Phase 0 — v0 credibility containment

v0 is legacy/experimental and frozen except for bounded security, correctness, reliability, packaging, and honesty fixes.

Before serious v1 assurance distribution:

- #54 must stop fabricating human escalation responses;
- #160 must fail closed or report explicit incompleteness for mandatory verification that was not evaluated;
- #159 must correct public assurance claims and publish limitations/claims-to-evidence mapping.

Historical v0 implementation is not evidence that the v1 thesis has already been validated.

## Current experiment

The source of truth is issue #149, with #154 owning the strong-baseline/adversarial corpus.

Sequence:

1. define the strongest reasonable baseline;
2. attack it with realistic substitution/replay/omission/completeness cases;
3. run the category kill gate;
4. only if a material gap survives, minimize the portable artifact semantics;
5. build one standalone verifier;
6. prove one controlled real enforcement path;
7. validate a second, operationally meaningful scenario;
8. obtain genuinely independent implementation/consumer evidence;
9. use formal methods only when they buy information;
10. test `.iflow` against JSON/builders last.

## Category kill gate

Do not proceed to broad protocol/verifier/language expansion unless at least one **material, realistic, security-relevant** failure class:

1. cannot be represented or reliably verified by the strong baseline without effectively reinventing the proposed portable assurance contract; and
2. is addressed by a small, generalizable, implementation-neutral semantic addition.

These are not sufficient differentiation by themselves:

- renamed schemas;
- a nicer CLI;
- more verbose logs;
- a custom DSL;
- a check that can be trivially added to the baseline record;
- a formal proof of a property the baseline already expresses just as clearly.

If the gate fails, publish the negative result and stop broader protocol/language investment.

## Artifact minimization

If the category survives, #151 defines the **smallest** portable contract justified by the demonstrated gap.

Names such as `AssurancePlan`, `ActionRequest`, `Approval`, `ExecutionReceipt`, and `DecisionAttestation` are candidate vocabulary, not mandatory architecture.

Every retained field must answer:

- which threat/property requires it;
- why the strong baseline is insufficient;
- why it belongs in a portable contract rather than an implementation log;
- what an independent verifier can establish from it;
- what remains an external assumption.

## Byte-level trust boundary

For every signed or digest-referenced artifact, the specification must state unambiguously:

- exact authenticated bytes;
- exact hashed bytes;
- whether/why canonicalization is required;
- cross-language vectors for retained canonicalization boundaries;
- version/critical-extension behavior;
- that a verifier never substitutes a separately parsed/re-serialized object for the authenticated payload.

## Independence

Two implementations written by the same maintainer provide implementation/language diversity, not full ecosystem independence.

Before standards-like positioning require at least one producer, consumer, verifier, or enforcer outside the dgenio-maintained implementation set.

Prefer an external implementation from the normative specification/corpus over another internally ported verifier.

## Formal methods

### Alloy

Use after a candidate category gap and small transaction model exist. Every useful counterexample feeds the adversarial corpus.

### Lean

Blocked until:

- the category gate passes;
- semantics stabilize;
- the first verifier works;
- a concrete proof-value hypothesis exists.

Continue only if theorem work exposes meaningful defects or provides assurance worth its maintenance burden.

Formal work never proves GitHub/MCP/crypto implementations, human wisdom, external evidence truth, or LLM reasoning correctness.

## `.iflow` is optional

After protocol value is demonstrated, compare equivalent authoring tasks using:

1. canonical JSON + schema/editor tooling;
2. typed builders;
3. `.iflow`.

Retain `.iflow v1` only if it materially improves authoring safety, review comprehension, or usability relative to its parser/compiler/spec maintenance cost.

Dropping the DSL while retaining a useful protocol/verifier is a successful incubation outcome.

## Graduation criteria

IntentFlow v1 graduates only if all are true:

1. strong-baseline comparison demonstrates a real semantic/assurance gap;
2. minimal portable semantics close the gap without becoming a general policy/workflow language;
3. the standalone verifier handles legitimate and adversarial corpus cases correctly;
4. a controlled real enforcement path emits a verifiable attestation;
5. a second operationally meaningful controlled scenario shows the value is not demo-specific;
6. external independent implementation/consumer evidence exists beyond same-maintainer ports;
7. any retained authoring frontend demonstrates measurable value over JSON/builders;
8. the artifacts/verifier work without requiring the whole Weaver Stack.

Stars, schema count, theorem count, same-maintainer cross-language agreement, or a polished demo are not graduation criteria.

## Narrow / abandonment criteria

Stop or narrow when evidence shows that:

- strong policy + signed attestation covers the same meaningful threats;
- the new protocol mostly renames existing policy/attestation concepts;
- useful semantics are better expressed as a profile over an existing standard;
- external users value enforcement but do not need portable assurance artifacts;
- independent implementations cannot agree without implementation-specific interpretation;
- `.iflow` adds syntax but not authoring safety/usability;
- formal-method maintenance exceeds practical assurance benefit.

Successful narrowed outcomes include:

- a small assurance profile moved to `weaver-spec`;
- a standalone verifier without a DSL/runtime;
- a public adversarial research corpus with IntentFlow v1 archived;
- a much smaller action-assurance protocol.

## WIP rule

Until the category kill gate passes, active v1 work is limited to:

- v0 credibility containment (#54, #160, #159);
- minimal threat/claims vocabulary (#150);
- strong baseline + adversarial corpus (#154);
- only the minimum #151 work needed to express/test a demonstrated candidate gap.

Second verifier, Lean, `.iflow v1`, general runtime/workflow expansion, calibration/context-policy work, compiler optimization, and broad standards/launch work remain blocked.

## Canonical references

- #149 — falsification-first v1 epic
- #154 — strong baseline and adversarial corpus
- #151 — minimum artifact semantics, only if the category survives
- #155 — first standalone verifier, post-gate
- #157 — controlled enforcement mechanics proof
- #156 — second verifier / independence gate
- #152 — Alloy, post-gap
- #153 — Lean, post proof-value gate
- #158 — `.iflow` user test, last

When speculative feature roadmaps conflict with this contract, the falsification and abandonment gates take precedence.