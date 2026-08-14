# Failure artifacts in the v0 runtime

IntentFlow preserves a classified partial witness for **caught runtime failures after tracing has started**. This is a bounded v0 reliability property, not a claim that every possible failure always leaves durable evidence.

When an unexpected tool/runtime phase exception escapes normal handling, the runtime:

1. records the phase and exception type/message;
2. appends a terminal `run_failed` event to the existing hash chain when the trace writer is still usable;
3. seals that same chain, so any configured HMAC/Ed25519 signature commits to the failure classification;
4. builds a partial result with `status: failed` and `complete: false`;
5. raises `RunFailed`, carrying that partial result to the command boundary;
6. writes configured `--trace-dir` / `--trace-out` witnesses with temporary-file + atomic-replace semantics;
7. exits non-zero even when the failure witness was written successfully.

The partial result includes the evidence and outputs captured before failure, the failing phase/type, the available trace, and a small derived failure receipt describing work that was not completed. The receipt is a convenience view over the authenticated result; it is **not** a second attestation.

`intentflow audit` still verifies the trace chain, action-policy evidence, citations, and output consistency that can be checked from the partial result. It does not impose success-only verification/uncertainty coverage requirements on `status: failed` results.

## What is not guaranteed

A durable artifact cannot be promised when the process or host terminates abruptly, storage itself is unavailable, the configured trace sink has already failed, or execution fails before durable tracing begins. A JSONL `--trace-stream` may still contain a chain-verifiable prefix in some of those cases, but a valid prefix is not the same thing as a complete or classified failure witness.

The artifact also proves only what IntentFlow recorded. It does not prove whether an external system performed a side effect unless that fact is independently represented in the captured evidence.
