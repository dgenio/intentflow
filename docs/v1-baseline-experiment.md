# IntentFlow v1 strong-baseline experiment

This document is the reproducible decision template for issues #149 and #154.

Its purpose is to prevent IntentFlow from proving its value against a weak comparator.

## Question

> Does the proposed portable assurance contract detect a material class of agent-action failure that a strong policy + exact request/approval/receipt + signed-attestation design cannot represent or verify cleanly?

If not, stop or narrow the v1 protocol direction.

## Baseline transaction

For each scenario, construct the strongest reasonable baseline using existing mechanisms before adding IntentFlow-specific semantics.

The baseline should contain, where applicable:

1. **Policy identity and decision**
   - policy/ruleset identity or digest;
   - decision and reason;
   - principal/action/resource context.
2. **Exact request identity**
   - exact request bytes or an explicitly defined canonical digest domain;
   - action/tool identity;
   - target/resource identity;
   - relevant pre-state identity.
3. **Approval**
   - approver identity/role;
   - exact request binding;
   - validity window;
   - single-use nonce/consumption state when required.
4. **Execution receipt**
   - executor identity;
   - request binding;
   - observed result/reference;
   - timestamps/state identifiers needed by the scenario.
5. **Postcondition observation**
   - read-back of the relevant external state;
   - source/trust assumption;
   - binding to the request/receipt.
6. **Authenticated record**
   - signed structured attestation/envelope using established primitives where practical;
   - precise authenticated payload bytes;
   - version/type handling.

Do not omit a capability merely because IntentFlow also proposes it.

## Baseline design record

For every scenario version a record with:

```text
scenario_id:
protected_action:
policy_mechanism:
request_identity_mechanism:
approval_binding:
single_use_mechanism:
receipt_binding:
postcondition_observation:
authenticated_envelope:
trusted_components:
known_external_assumptions:
known_unsupported_properties:
```

## Required adversarial matrix

Every case must declare the exact mutation, the expected strong-baseline verdict, and the proposed additional IntentFlow semantic if one is needed.

| Failure class | Example mutation | Baseline must attempt to detect |
| --- | --- | --- |
| Request substitution | title/body/arguments changed after approval | approval no longer authorizes execution |
| Policy/plan substitution | weaker/different policy identity substituted | authenticated transaction no longer matches authorized policy |
| Tool/server substitution | different tool descriptor or server handles request | executor/tool identity mismatch |
| Approval replay | same approval reused | second execution rejected/not conformant |
| Cross-request approval | approval for A attached to B | request digest/binding mismatch |
| Stale pre-state | target state changed between approval and execution | explicit state-binding/profile decision |
| Receipt substitution | receipt from different request/run | receipt/request mismatch |
| Post-state substitution | read-back does not match authorized result | postcondition failure |
| Missing obligation | required approval/postcondition omitted | incomplete/non-conformant result |
| Partial-as-success | interrupted execution marked terminal success | completeness/status failure |
| Downgrade | unsupported/weaker critical version used | fail closed |
| Payload confusion | different parsed payload evaluated than signed bytes | authenticity/conformance failure |
| Contradictory status | disposition fields disagree | structural/state failure |

Add cases only when they correspond to a concrete threat/property. Do not inflate the corpus to make the protocol look comprehensive.

## Per-case comparison record

Use this shape or an equivalent machine-readable representation:

```text
case_id:
scenario_id:
failure_class:
mutation:
materiality: low|medium|high
threat_rationale:

strong_baseline:
  expected_verdict: accept|reject|incomplete|unsupported
  detection_mechanism:
  assumptions:
  implementation_complexity:

candidate_intentflow:
  extra_semantic_needed: yes|no|uncertain
  semantic:
  why_baseline_is_insufficient:
  portable_or_profile_specific:
  added_complexity:

review_decision:
  differentiated: yes|no|uncertain
  rationale:
```

## Materiality rule

A difference only counts toward the category gate when it is:

- security/reliability relevant to a realistic governed agent action;
- not merely cosmetic or a naming difference;
- not trivially fixable by adding one obvious field/check to the strong baseline record;
- generalizable beyond one implementation quirk;
- small enough that the proposed portable semantics remain comprehensible and independently implementable.

## Category decision table

Before implementing the first standalone verifier, publish a reviewed table:

| Failure class | Strong baseline result | Candidate IntentFlow result | Extra semantic | Material difference? |
| --- | --- | --- | --- | --- |
| ... | ... | ... | ... | ... |

Then choose exactly one programme disposition:

### STOP

The strong baseline covers the material threats. Publish the result and do not create a new protocol.

### PROFILE EXISTING STANDARDS

Agent-specific field/profile conventions are useful, but they can be expressed over existing standards without a new general protocol. Move the useful contract toward `weaver-spec` or the appropriate standards-compatible profile.

### NARROW PROTOCOL

A small implementation-neutral semantic gap survives. Define only the minimum artifact semantics required by that gap in #151.

### CONTINUE

Multiple material gaps survive and justify a portable assurance contract. Even then, minimize the contract before verifier/language expansion.

## Review requirements

The category decision should not rely only on the author of IntentFlow.

Where practical:

- ask at least one security/protocol reviewer unfamiliar with the implementation to challenge the strong baseline and proposed gap;
- preserve disagreement;
- let reviewers strengthen the baseline before declaring differentiation;
- record which findings are implementation defects versus protocol-level deficiencies.

## Serialization/signing questions to answer before declaring a gap solved

For every retained candidate semantic:

- What exact bytes are authenticated?
- What exact bytes are hashed/referenced?
- Is canonicalization required? Why?
- Could two languages produce different digests?
- Does verification ever parse/re-serialize a signed payload and then accidentally verify the substitute?
- Which version/extension changes fail closed?
- Which facts are observations from trusted systems rather than externally proven truth?

## What this experiment does not prove

Even a successful category gate does not prove:

- an LLM reasoned correctly;
- the action was a good product/business decision;
- external evidence was truthful;
- GitHub/MCP/crypto implementations are correct;
- complete mediation exists outside the declared enforcement profile;
- IntentFlow is an industry standard.

It only justifies spending the next increment of effort on the smallest portable assurance semantics that survived a strong comparison.