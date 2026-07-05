# Trace signing and key management

A trace is tamper-*evident* on its own: the hash chain (`trace.link_hash`) lets
anyone recompute it and catch an edit, deletion, or reordering with no plan
required. But the chain links live inside the trace, so a forger who edits an
event can recompute every downstream link — the bare chain is integrity, not
authenticity. **Sealing** the root out of band closes that gap.

`seal()` produces a `signatures` list over the chain root:

```json
"trace_chain": {
  "algo": "sha256-chain",
  "length": 38,
  "root": "6617fca4…",
  "signatures": [
    { "algo": "hmac-sha256", "key_id": "prod-2026-07", "signature": "…" }
  ]
}
```

An unsigned run seals with an empty `signatures` list.

## HMAC sealing with key ids and rotation (#80)

HMAC sealing proves a **shared-secret** holder sealed the trace (a semi-trusted
verifier who also holds the secret can detect edits). Key ids make rotation
safe: without them, rotating the signing key silently invalidates every prior
witness, which teaches users never to rotate — the wrong lesson for a security
feature.

### Signing

```bash
export IFLOW_TRACE_KEY="…the current secret…"
export IFLOW_TRACE_KEY_ID="prod-2026-07"     # optional but recommended
intentflow run program.iflow --sign-trace --trace-out witness.json
```

The seal records `key_id` when `IFLOW_TRACE_KEY_ID` is set. Omit it and the seal
is a keyless HMAC entry (verifiable only by the single default key).

### Verifying

```bash
# Single-key case: the default (keyless) key.
export IFLOW_TRACE_KEY="…the secret…"
intentflow audit program.iflow witness.json

# Rotation set: id=secret pairs, comma-separated. A key-id'd seal is verified
# by the matching key from the set, so old witnesses stay verifiable after a
# key change as long as their key stays in the set.
export IFLOW_TRACE_KEYS="prod-2026-07=…new…,prod-2026-06=…old…"
intentflow audit program.iflow witness.json
```

An unknown `key_id` and a wrong key produce **distinct** non-conformant
messages ("signed with unknown key id …" vs "signature is invalid …"), and key
material is never echoed in output.

### Rotation procedure

1. Generate the new secret; give it a new id (e.g. a date).
2. Add it to `IFLOW_TRACE_KEYS` on verifiers, **keeping the retiring id** so
   witnesses signed with it still verify.
3. Switch signers to the new `IFLOW_TRACE_KEY` / `IFLOW_TRACE_KEY_ID`.
4. Once no live witness needs the retired id, drop it from the verifier set.

## Ed25519 public-key signatures (#81)

HMAC verification requires sharing the signing secret — so only semi-trusted
parties can verify. Ed25519 sealing lets a *genuinely external* party (a
regulator, a customer, a CI system) verify a witness with only the **public**
key, holding no secret and unable to forge.

Ed25519 support lives in `intentflow.signing` and needs the optional `sign`
extra (`pip install "intentflow[sign]"`), which pulls in `cryptography`. The
core install stays dependency-free; importing `intentflow` without the extra
works, and signing without it fails with an actionable error.

### Generating a keypair

No new CLI subcommand is added (CLI-surface restraint); generate a keypair with
a short Python snippet:

```python
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

priv = Ed25519PrivateKey.generate()
open("trace_ed25519.pem", "wb").write(
    priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
)
open("trace_ed25519.pub", "wb").write(
    priv.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
)
```

### Signing and verifying

```bash
# Sign with the private key (PEM path). Combine with --sign-trace to add an
# HMAC entry too, or use it alone for public-key-only sealing.
export IFLOW_TRACE_SIGNING_KEY="trace_ed25519.pem"
export IFLOW_TRACE_KEY_ID="ed-2026-07"        # optional; labels the entry
intentflow run program.iflow --sign-trace-key --trace-out witness.json

# Verify with only the PUBLIC key — no secret in the environment.
export IFLOW_TRACE_PUBLIC_KEY="trace_ed25519.pub"
intentflow audit program.iflow witness.json
```

The auditor verifies an Ed25519 seal against the **trusted** public key supplied
via `IFLOW_TRACE_PUBLIC_KEY`, never the `public_key` embedded in the seal (which
a forger controls). An unknown algorithm or a missing trusted key is a distinct,
non-conformant `T3`.
