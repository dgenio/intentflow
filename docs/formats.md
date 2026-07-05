# IntentFlow artifact formats and versioning

IntentFlow emits two machine-readable contract artifacts. Third parties consume
them without trusting the runtime, so their shapes and versions are part of the
public contract.

| Artifact | Produced by | Version field | Version constant | Schema |
|----------|-------------|---------------|------------------|--------|
| **Execution plan** | `intentflow compile` (`compiler.compile_program`) | `format_version` | `compiler.PLAN_FORMAT_VERSION` | [`schemas/plan.schema.json`](../schemas/plan.schema.json) |
| **Run result / trace (witness)** | `intentflow run` (`runtime.GoalRuntime.run`) | `format_version` | `trace.TRACE_FORMAT_VERSION` | [`schemas/result.schema.json`](../schemas/result.schema.json) |

Both fields share the name `format_version` but are **versioned independently**:
the plan format and the witness format evolve on separate schedules (a new trace
event type bumps the trace format, not the plan format). Neither tracks the
package version (`intentflow.__version__`), which is also stamped into artifacts
(`intentflow_version`) purely for provenance.

## Versioning policy (pre-1.0)

While IntentFlow is pre-1.0, the compatibility policy is **exact match**:

- The auditor declares the versions it can verify in
  `auditor.SUPPORTED_PLAN_FORMATS` and `auditor.SUPPORTED_TRACE_FORMATS`.
- Auditing a plan or result whose `format_version` is not in the corresponding
  supported set yields a non-conformant verdict with a `P2` violation naming the
  mismatch (rather than silently auditing a shape the auditor may not
  understand — a conformance verdict on an unknown format would be unreliable).

Exact match is deliberate pre-1.0: a minor format bump may change semantics an
auditor must react to, so optimistic "semver-compatible" acceptance is unsafe
until the formats stabilize. Post-1.0 this policy can widen to a documented
semver-compatible window; that change will itself be a versioned, documented
decision.

### When you bump a format version

1. Change the shape in `compiler.py` (plan) or `runtime.py` (result/trace).
2. Bump `PLAN_FORMAT_VERSION` or `TRACE_FORMAT_VERSION`.
3. Update the corresponding schema under `schemas/` and its tests.
4. Add the new version to the auditor's supported set. If old artifacts must
   still audit, keep the prior version in the set and branch on it — do not drop
   a supported version without a migration note here.

### Re-running or migrating old artifacts

An artifact produced by an out-of-range version is reported, not guessed at.
Re-compile the source (`intentflow compile`) or re-run it (`intentflow run`)
with a matching IntentFlow release to produce a current, auditable artifact.
There is no in-place migration of old witnesses; the source program plus a
current runtime reproduces an equivalent one.

## Consuming the schemas

The schemas are JSON Schema **draft 2020-12** and live under
[`schemas/`](../schemas/). They are the authoritative description of each
artifact's shape — an independent auditor, trace viewer, or storage layer in any
language can validate against them.

The schemas are intentionally strict at the top level (`additionalProperties:
false`, so shape drift is caught) and typed on the verifiable trace/witness
structures (hash-chain links are 64-hex, sequence numbers are positive
integers, statuses are an enum). Rich nested *plan policy* objects are typed as
objects but not exhaustively constrained, so the schema documents the contract
without freezing every internal field prematurely — a deliberate pre-1.0 choice.

`tests/test_schemas.py` validates every bundled example's plan, goal result, and
pipeline result against these schemas, so they cannot drift from what the code
emits without a test failing. `jsonschema` is a dev-only dependency; the runtime
core stays dependency-free.
