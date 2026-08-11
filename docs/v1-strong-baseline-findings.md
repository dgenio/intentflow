# IntentFlow v1 strong-baseline findings — preliminary

Status: **research / category falsification input**, not a normative v1 specification.

This note records the first standards-grounded pass for #149/#154. Its job is to make the baseline as strong as possible before IntentFlow introduces new protocol semantics.

## Preliminary decision

**Current default disposition: `PROFILE EXISTING STANDARDS`, unless the adversarial corpus proves a material gap that requires a new portable protocol.**

The first research pass suggests that much of the originally proposed v1 stack can already be represented as:

```text
policy decision
+ exact content-addressed request
+ explicit approval record
+ execution/read-back receipt
+ agent-action assurance predicate
+ in-toto Statement
+ DSSE authentication
+ profile-specific verifier
```

That would still leave real design work in the **agent-action predicate/profile, binding semantics, completeness rules, and verifier**, but it does not justify inventing a new signing envelope or assuming five independent top-level IntentFlow artifacts.

The category gate remains open. The adversarial corpus must try to disprove this preliminary conclusion.

## Primary sources reviewed

### Open Policy Agent decision logs

OPA decision logs record policy query events including the policy queried, query input, bundle metadata, and other audit/debugging information. When decision logging is enabled, API responses include a `decision_id`.

Source: <https://www.openpolicyagent.org/docs/management-decision-logs>

Implication for the baseline:

- IntentFlow should not claim novelty merely for recording a policy decision, policy/query context, or a stable decision identifier.
- An OPA-style decision record can be one input to the assurance transaction.
- OPA decision logging alone does **not** provide exact request-bound approval, single-use consumption, execution receipt, postcondition binding, or signed transaction completeness; those must be added by the application/profile if required.

### DSSE — Dead Simple Signing Envelope

DSSE is designed to sign arbitrary data, authenticating both message bytes and message type. Its design explicitly avoids signature-time canonicalization to reduce attack surface.

Source/spec repository: <https://github.com/secure-systems-lab/dsse>

Implication for the baseline:

- IntentFlow should not invent another general signing envelope unless the adversarial corpus demonstrates a capability DSSE cannot provide.
- The verifier must consume the authenticated payload bytes and type, not a separately reserialized substitute.
- Canonicalization, if retained, should be used only for **digest/reference identity** of semantic JSON objects where cross-producer stable digests are actually required—not because the signature envelope itself needs it.

### in-toto Attestation Framework

The current in-toto Attestation Framework separates:

- a type-specific **Predicate** containing arbitrary metadata;
- a **Statement** binding the attestation to a subject and identifying `predicateType`;
- an authentication/serialization **Envelope**;
- optional **Bundle** grouping.

The framework explicitly supports new predicate types when existing predicates do not cover a use case. Its intended consumers include automated policy engines.

Sources:

- framework: <https://github.com/in-toto/attestation/blob/main/spec/README.md>
- Statement v1: <https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md>
- Envelope: <https://github.com/in-toto/attestation/blob/main/spec/v1/envelope.md>
- predicate guidance/catalog: <https://github.com/in-toto/attestation/blob/main/spec/predicates/README.md>

Implication for the baseline:

- A new **agent-action assurance predicate/profile** is a serious competitor to a new general IntentFlow protocol.
- The predicate can carry the action-specific transaction semantics while the in-toto Statement/DSSE layers handle typed authenticated metadata.
- IntentFlow must demonstrate why a new top-level artifact framework is materially better than an in-toto-compatible predicate plus verifier before claiming a new protocol category.

### JCS / RFC 8785

RFC 8785 defines a deterministic JSON canonicalization scheme for cryptographic hashing/signing use cases and constrains inputs to I-JSON. The RFC has verified errata, including a security-relevant note around negative zero serialization.

Sources:

- RFC: <https://www.rfc-editor.org/rfc/rfc8785.html>
- errata: <https://www.rfc-editor.org/errata/rfc8785>

Implication for the baseline:

- JCS is a viable tool when two independent implementations need to derive the same digest from the same semantic JSON object.
- It is **not automatically required** for DSSE-authenticated payloads because DSSE authenticates payload bytes/type directly.
- If the agent-action profile uses JCS for request/policy/receipt digests, the profile needs cross-language vectors and explicit treatment of the RFC's I-JSON/numeric constraints and verified errata.
- The simpler alternative—digesting exact serialized request bytes—should be preferred when semantic reserialization across producers is unnecessary.

## Candidate strong baseline

The first adversarial corpus should assume this baseline is competently implemented rather than intentionally weak.

### 1. Policy decision

Record:

- policy engine/profile identity;
- policy/ruleset digest or immutable revision;
- decision id;
- principal/action/resource inputs;
- result and reason codes.

OPA may be used as the reference policy decision producer, but the baseline is not OPA-specific.

### 2. Exact request document

Represent the exact action request as an immutable content-addressed document.

Initial preference:

- preserve exact serialized request bytes;
- compute SHA-256 over those exact bytes;
- record media/type identity alongside the digest.

Use JCS only if the experiment demonstrates a real requirement for independent producers to derive a digest from semantically identical JSON with different serialization.

The request should include every field whose substitution matters for the selected profile, for example for GitHub issue creation:

- target owner/repository;
- action/tool identity;
- title;
- body;
- labels;
- principal/run identity;
- relevant expected pre-state/profile fields.

### 3. Approval record

An approval record should contain at minimum where the profile requires human approval:

- approval id;
- approver identity/role;
- exact request digest;
- policy/plan/profile identity;
- validity interval;
- nonce/single-use identifier;
- optional relevant pre-state binding;
- decision (`approve`/`deny`) and reason/note.

The approval should itself be authenticated or included by digest inside the final authenticated attestation.

### 4. Single-use consumption state

This is deliberately separated from the static approval document.

A static signed attestation cannot, by itself, prove that an approval was **never reused elsewhere**. The enforcing system needs state, an atomic consumption mechanism, a transparency/ledger model, or another deployment-specific anti-replay mechanism.

Therefore both the strong baseline **and any IntentFlow protocol** must state the external assumption clearly:

> verifier acceptance of a single transaction is not global proof that the nonce/approval was never consumed in another hidden execution unless the verifier also has authoritative consumption state.

This is a critical non-claim for #149/#151.

### 5. Execution receipt

Record a content-addressed execution receipt including, where meaningful:

- request digest;
- approval id/digest;
- executor/enforcer identity;
- tool/server/descriptor identity;
- observed start/pre-state;
- execution time/result identity;
- external resource identifier returned by the action;
- completion/error classification.

### 6. Postcondition/read-back observation

After execution, read the protected resource through the trusted profile adapter and record the observation that matters for conformance.

For GitHub issue creation this may include:

- repository;
- issue number/URL;
- open/closed state;
- title/body/labels or digests thereof;
- observation timestamp/API identity.

This proves only what the configured observer reported under its trust assumptions. It does not prove GitHub itself is infallible or the issue is a good/unique business decision.

### 7. Agent-action assurance predicate

Preliminary hypothesis: encode the transaction in **one type-specific in-toto predicate** rather than five mandatory top-level IntentFlow artifacts.

Candidate shape, intentionally non-normative:

```json
{
  "_type": "https://in-toto.io/Statement/v1",
  "subject": [
    {
      "name": "agent-action-request",
      "digest": {"sha256": "<request-digest>"}
    }
  ],
  "predicateType": "https://intentflow.dev/attestation/agent-action-assurance/v0.1",
  "predicate": {
    "profile": "https://intentflow.dev/profiles/github-create-issue/v0.1",
    "policyDecision": {"id": "...", "policyDigest": "...", "result": "allow"},
    "approval": {"id": "...", "digest": "...", "nonce": "..."},
    "execution": {"receiptDigest": "...", "executor": "..."},
    "postcondition": {"observationDigest": "..."},
    "disposition": "completed",
    "assumptions": ["..."],
    "obligations": ["..."]
  }
}
```

The actual predicate should be much smaller after the attack corpus reveals which bindings are necessary.

### 8. DSSE envelope

Serialize the in-toto Statement once and authenticate those exact payload bytes with DSSE.

Verifier rule:

> Verify the DSSE signature over the authenticated payload/type first, then parse/evaluate that authenticated payload. Never parse some other JSON object and assume its semantics are covered by the DSSE signature.

## Preliminary adversarial comparison

This table is **not final evidence**. It predicts what the strong baseline should already catch if implemented correctly. #154 must turn each row into concrete vectors and try to falsify these predictions.

| Failure class | Strong-baseline mechanism | Preliminary result |
| --- | --- | --- |
| Request argument substitution | approval + receipt bind exact request digest | baseline should reject |
| Policy/plan substitution | attestation/request/approval bind policy/profile digest | baseline should reject |
| Tool/server descriptor substitution | request/receipt bind descriptor identity/digest | baseline should reject |
| Approval attached to another request | approval request digest mismatch | baseline should reject |
| Expired/not-yet-valid approval | profile verifier checks validity | baseline should reject |
| Approval replay within one authoritative enforcer | atomic nonce consumption state | baseline should reject |
| Hidden replay outside verifier's authoritative state | static attestation alone cannot prove non-occurrence | **external-state limitation shared by both designs** |
| Stale pre-state | request/approval pre-state + enforcer recheck | baseline should reject if profile requires it |
| Receipt substitution | authenticated predicate binds receipt digest/request | baseline should reject |
| Post-state mismatch | verifier checks read-back observation against profile | baseline should reject |
| Missing mandatory obligation | predicate schema/profile verifier completeness rule | baseline should reject/incomplete |
| Partial execution reported as complete | disposition + required receipt/postcondition completeness | baseline should reject |
| Version downgrade / unknown critical semantics | predicate/profile version policy | baseline should reject if fail-closed rules are defined |
| Signed-payload confusion | DSSE binds payload type + exact payload bytes | baseline should reject |
| Unicode/number digest divergence | exact-byte digest avoids semantic canonicalization; JCS vectors if semantic digests retained | baseline design choice, not protocol novelty |

## Where a genuine IntentFlow gap might still exist

The baseline comparison does **not** prove there is no new category. The adversarial corpus should focus on possible gaps such as:

1. **Portable mandatory-obligation semantics.** Is there a small general model for obligations/completeness that is useful across enforcers and materially safer than profile-specific verifier code?
2. **Cross-implementation transaction state semantics.** Do multiple enforcers need a shared finite state machine for `requested -> authorized -> executing -> observed -> complete/incomplete`, and does that state model prevent realistic defects the predicate baseline otherwise repeats inconsistently?
3. **Approval/request/pre-state binding vocabulary.** Is a standardized portable binding object materially useful across OPA, AgentFence, agent-kernel, and other enforcers, or is a predicate schema enough?
4. **Critical-extension/version negotiation.** Does an agent-action assurance profile need reusable fail-closed extension semantics beyond ordinary predicate/profile version dispatch?
5. **Independent verification ergonomics.** Can a generic verifier safely evaluate multiple action profiles without becoming a new general policy language?

Each proposed gap must survive the rule from #149: if adding one obvious field/check to the strong predicate baseline solves it cleanly, that is probably **profile design**, not a new protocol.

## Explicit non-gaps / do not claim as novelty

Based on the primary standards reviewed, IntentFlow should not claim novelty merely for:

- policy decision ids/log records;
- a signed typed payload envelope;
- authenticating payload type as well as bytes;
- an extensible typed predicate carrying arbitrary metadata;
- content-addressed references to evidence/documents;
- a generic statement binding a subject digest to a predicate;
- JSON canonicalization as a concept;
- separate attestation and policy-consumer roles.

## Current category recommendation

Until #154 produces a concrete counterexample that the strong baseline cannot cover cleanly:

> **Treat IntentFlow v1 as an experimental agent-action assurance profile/predicate + verifier research project, not as a new general attestation protocol or language.**

This is deliberately more conservative than the original v1 architecture.

A successful next outcome may be:

- an in-toto-compatible agent-action assurance predicate/profile;
- an implementation-neutral verifier for that profile;
- stable binding vocabulary later moved to `weaver-spec`;
- AgentFence / agent-kernel adapters that emit the predicate;
- no `.iflow v1` language at all.

If the adversarial corpus demonstrates stronger reusable transaction semantics that cannot be expressed cleanly as profile rules, #151 can then justify a narrower portable protocol with evidence rather than architecture preference.

## Next experiment steps

1. Convert every row in the preliminary table into a concrete #154 valid/adversarial vector.
2. Implement the **strong baseline vectors first**, without importing the v0 runtime/auditor.
3. For each case, let reviewers strengthen the baseline before counting a difference as IntentFlow differentiation.
4. Produce the STOP / PROFILE EXISTING STANDARDS / NARROW PROTOCOL / CONTINUE decision table.
5. Do not start #155/#152/#153/#156/#157/#158 until the category gate says the extra semantics are justified.