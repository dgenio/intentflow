"""Optional Ed25519 public-key signing for trace roots (issue #81).

HMAC sealing (``trace.Trace`` + ``--sign-trace``) proves a *shared-secret*
holder sealed a trace, so only parties who hold the secret — and could therefore
forge — can verify. Ed25519 sealing closes that gap: a run is signed with a
private key, and any third party can verify the witness with only the **public**
key, holding no secret and unable to forge. That is the strongest form of the
proof-carrying-witness claim.

This module needs the ``sign`` extra (``pip install "intentflow[sign]"``), which
pulls in ``cryptography``. It is imported lazily so the core package stays
dependency-free: ``import intentflow`` works without the extra, and signing
without it raises an actionable error rather than an ImportError at import time.
"""

from __future__ import annotations

from typing import Any

_EXTRA_HINT = (
    "Ed25519 trace signing needs the optional 'sign' extra; install it with "
    "`pip install \"intentflow[sign]\"`."
)


def _crypto():
    """Import the cryptography primitives lazily, or raise an actionable error.

    Keeping this import inside the function (never at module top level) is what
    lets the zero-dependency core policy hold: nothing under ``intentflow/`` may
    import a third-party package at module import time."""
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519
        from cryptography.exceptions import InvalidSignature
    except ImportError as exc:  # pragma: no cover - exercised via the no-extra test
        raise RuntimeError(_EXTRA_HINT) from exc
    return serialization, ed25519, InvalidSignature


def sign_root(
    root: str, private_key_pem: bytes, key_id: str | None = None
) -> dict[str, Any]:
    """Sign a trace chain ``root`` with an Ed25519 private key (PEM/PKCS8).

    Returns one seal ``signatures`` entry: ``{algo, signature, public_key}`` plus
    ``key_id`` when given. The public key is embedded for reference only —
    verification uses a *trusted* public key supplied out of band, never this
    field."""
    serialization, ed25519, _ = _crypto()
    private_key = serialization.load_pem_private_key(private_key_pem, password=None)
    if not isinstance(private_key, ed25519.Ed25519PrivateKey):
        raise ValueError("IFLOW_TRACE_SIGNING_KEY is not an Ed25519 private key")
    signature = private_key.sign(root.encode("utf-8")).hex()
    public_pem = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )
    entry: dict[str, Any] = {
        "algo": "ed25519",
        "signature": signature,
        "public_key": public_pem,
    }
    if key_id is not None:
        entry["key_id"] = key_id
    return entry


def verify_root(root: str, signature_hex: str, public_key_pem: bytes) -> bool:
    """Verify an Ed25519 ``signature_hex`` over ``root`` with a trusted public
    key (PEM). Returns ``True`` only on a valid signature; any error (wrong key
    type, malformed signature, bad signature) returns ``False``."""
    serialization, ed25519, InvalidSignature = _crypto()
    try:
        public_key = serialization.load_pem_public_key(public_key_pem)
    except Exception:
        return False
    if not isinstance(public_key, ed25519.Ed25519PublicKey):
        return False
    try:
        public_key.verify(bytes.fromhex(signature_hex), root.encode("utf-8"))
        return True
    except (InvalidSignature, ValueError):
        return False


class Ed25519Signer:
    """A :class:`~intentflow.trace.TraceSigner` that seals the root with Ed25519.

    Injected into ``Trace(signers=[...])`` so the stdlib-only ``trace`` module
    never imports ``cryptography``; the crypto is confined to this optional
    module."""

    def __init__(self, private_key_pem: bytes, key_id: str | None = None) -> None:
        self._private_key_pem = private_key_pem
        self._key_id = key_id

    def sign_entry(self, root: str) -> dict[str, Any]:
        return sign_root(root, self._private_key_pem, self._key_id)
