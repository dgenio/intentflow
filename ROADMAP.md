# IntentFlow roadmap

This file is the canonical roadmap source for IntentFlow.

The roadmap sections in the README and `docs/architecture.md` intentionally link here to avoid drift across multiple copies.

IntentFlow is currently split into:

- **v0:** legacy/experimental implementation, frozen except for bounded correctness, security, reliability, packaging, and honesty fixes;
- **v1:** an incubation/research programme testing whether portable action assurance adds material value beyond a strong policy + signed-attestation baseline.

See [`INCUBATION.md`](INCUBATION.md) and issue #149 for the graduation and abandonment gates.

## Recently shipped in v0

- Typed outputs, analyzer, phase runtime, replay/explain shipped in commit `f6bfd6a` (v0.6.0).
- Blocking action approval gates (pre-grant, interactive TTY, synchronous webhook) shipped in commit `cb6168c`.
- Hash-chained traces with optional HMAC sealing, later key ids/rotation and Ed25519 support.
- Python embedding API and governed Python tool registration.
- LLM judge runner with a separate trust tier.
- OpenAI-compatible cognition backend.
- Versioned plan/result schemas, witness-envelope/versioning work, and shared trace/event vocabulary.

These features are historical implementation evidence. They do **not** establish the stronger v1 assurance thesis.

## Phase 0 — contain v0 credibility risks

Before serious v1 assurance distribution, complete the bounded issues that directly contradict or overstate assurance expectations:

1. #54 — `ask_human` must never fabricate a human response;
2. #160 — mandatory verification that is skipped/unevaluable must fail closed or report explicit incompleteness;
3. #159 — correct public assurance claims and publish a limitations/claims-to-evidence matrix.

Other v0 work is allowed only when it is a bounded security/correctness/reliability/packaging fix or is required to keep public claims accurate.

### Deferred former v0 roadmap work

The former active roadmap is no longer a product priority:

- learned confidence calibration (#8);
- context policy compiler/budget expansion (#9);
- richer verification predicate expansion (#58);
- DAG pipeline expansion (#7);
- general async/polling approval UX (#2), unless needed for a concrete safety/adoption requirement;
- plan/compiler optimization (#106).

These may be reconsidered only if the incubation result creates a demonstrated need. They are not current evidence of progress toward the v1 product thesis.

## Phase 1 — define the strongest baseline

Before building new IntentFlow-specific semantics, construct/document the strongest reasonable competitor:

```text
policy decision
+ exact request identity/binding
+ approval identity/validity/single-use semantics where needed
+ execution receipt
+ relevant postcondition/read-back
+ signed structured attestation
```

Use established standards/primitives where practical. Do not compare IntentFlow against a weak boolean policy plus an ad-hoc logfile.

The baseline is a real competitor. If it already covers the meaningful threat classes, that is a successful negative result.

## Phase 2 — adversarial corpus and category kill gate

#154 owns the baseline/adversarial corpus.

Required failure classes include:

- request/argument substitution;
- plan/policy substitution;
- tool/server/descriptor substitution;
- approval replay/double use;
- approval bound to the wrong request/run/state;
- stale pre-state;
- receipt/post-state substitution;
- missing mandatory obligation;
- incomplete execution presented as success;
- downgrade/unknown-critical-version handling;
- authenticated-payload/signature confusion;
- contradictory terminal/disposition state.

For every case, record the strong-baseline verdict and whether additional IntentFlow semantics are materially needed.

### Category kill gate

Proceed to new protocol implementation only if at least one realistic, material, security-relevant failure class:

1. cannot be represented or reliably verified by the strong baseline without effectively reinventing the proposed portable assurance contract; and
2. can be addressed by a small, generalizable, implementation-neutral semantic addition.

If the gate fails:

- stop broader protocol/language investment;
- publish the negative result;
- move useful profiles/conventions toward `weaver-spec` or compatible existing standards;
- reduce IntentFlow v1 to a research/reference artifact or archive it.

## Phase 3 — minimize the portable contract

Only after the category gate passes:

- #151 defines the smallest artifact/semantic set required by the demonstrated gap;
- names such as `AssurancePlan`, `ActionRequest`, `Approval`, `ExecutionReceipt`, and `DecisionAttestation` are hypotheses, not mandatory architecture;
- every retained semantic must map to a threat/property from #154;
- exact authenticated bytes, digest domains, canonicalization requirements, version behavior, and external assumptions must be explicit.

Do not preserve the old five-artifact taxonomy or canonicalization choices from sunk cost.

## Phase 4 — first standalone verifier

#155 is blocked until the category gate passes and #151/#154 stabilize the retained semantics.

Build one offline verifier independent from compiler/runtime/gateway/v0-auditor code.

It should distinguish, where applicable:

- authenticity;
- structural validity;
- contract/conformance;
- profile checks;
- completeness/terminal status.

A first verifier proves executable semantics, not ecosystem independence.

## Phase 5 — controlled enforcement proof

#157 is profile zero: a controlled GitHub issue-creation mutation through a credential-isolated reference enforcer.

It exists to prove mechanics:

```text
assurance contract
-> exact request
-> bound approval
-> real controlled enforcement
-> postcondition read-back
-> authenticated attestation
-> standalone verifier accepts
-> tamper/replay/substitution variant rejects
```

GitHub issue creation is deliberately understandable and safe, but is not sufficient market validation.

Before graduation, require a second controlled scenario where request/approval/state substitution has clearer operational consequence.

## Phase 6 — formal falsification where useful

### Alloy (#152)

Use Alloy only after the category gap is identified and a small transaction/state model exists. Its purpose is to expose replay/substitution/omission/downgrade/state-machine defects cheaply.

Every useful counterexample becomes a #154 corpus case.

### Lean (#153)

Lean is explicitly blocked until:

- the category gate passes;
- retained semantics are stable;
- the first verifier works;
- a proof-value hypothesis is documented.

Continue theorem work only when it exposes meaningful defects or materially increases confidence relative to its maintenance cost.

## Phase 7 — independence gate

#156 is a second verifier only after semantic stability.

Prefer an implementation written by an external contributor/team from the normative spec/corpus. If dgenio implements TypeScript internally, describe it accurately as language/implementation independence—not ecosystem validation.

Standards-like claims remain blocked until at least one producer, consumer, verifier, or enforcer exists outside the dgenio-maintained implementation set.

## Phase 8 — test `.iflow` last

#158 is not the product thesis.

After protocol/verifier value is demonstrated, compare equivalent authoring tasks using:

1. canonical JSON + schema/editor tooling;
2. typed Python/TypeScript builders;
3. `.iflow`.

Measure authoring time, security-relevant errors, review comprehension, translation mismatch, and maintenance burden.

Keep `.iflow v1` only if it is materially safer/simpler. Dropping the DSL while retaining a valuable portable assurance contract is a successful incubation outcome.

## Phase 9 — standards consideration

Do not call IntentFlow a standard because one repository has schemas or two same-maintainer implementations agree.

Standards-like positioning requires:

- stable implementation-neutral artifacts;
- public conformance/adversarial corpus;
- an external independent implementation/consumer;
- real interoperability need outside dgenio-controlled components;
- governance/versioning that can accept outside input without one implementation becoming normative by accident.

Stable contracts may graduate to `weaver-spec` if neutral ownership better serves interoperability.

## Graduation criteria

The v1 direction graduates only if all are true:

1. strong-baseline comparison demonstrates a real semantic/assurance gap;
2. minimal portable semantics close that gap without becoming a general policy/workflow language;
3. the first verifier handles the retained adversarial/normative corpus correctly;
4. a controlled real enforcement path emits a verifiable attestation;
5. a second operationally meaningful scenario shows the value is not demo-specific;
6. independent producer/consumer/verifier/enforcer evidence exists beyond same-maintainer ports;
7. any retained authoring frontend demonstrates measurable value over JSON/builders;
8. the assurance artifacts/verifier can be used without requiring the whole Weaver Stack.

## Narrow / abandonment criteria

Stop or narrow when evidence shows that:

- strong policy + signed attestation covers the same meaningful threats;
- the proposed protocol mainly renames existing policy/attestation concepts;
- useful semantics are better expressed as a profile over existing standards;
- external users value enforcement but do not need portable assurance artifacts;
- independent implementations cannot agree without implementation-specific interpretation;
- `.iflow` adds syntax without authoring safety/usability;
- formal-method maintenance exceeds practical assurance benefit.

Successful narrowed outcomes include:

- a small assurance profile moved to `weaver-spec`;
- a standalone verifier without a DSL/runtime;
- a public research corpus with v1 archived;
- a much smaller action-assurance protocol.

## WIP rule

Until the category kill gate passes, active v1 work is limited to:

- v0 credibility containment (#54, #160, #159);
- minimal threat/claims vocabulary (#150);
- strong baseline and adversarial corpus (#154);
- only the minimum #151 work needed to express/test a demonstrated candidate gap.

Second verifier, Lean, `.iflow v1`, workflow expansion, context/calibration work, compiler optimization, and broad launch/standards positioning remain blocked.

This roadmap treats **discovering that IntentFlow should be smaller—or should not exist as a new protocol—as a successful incubation result**.