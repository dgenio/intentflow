"""Ed25519 public-key trace signing tests (issue #81).

A witness signed with an Ed25519 private key verifies with only the public key —
no shared secret. These tests need the ``sign`` extra (``cryptography``); they
skip cleanly when it is absent. A separate test asserts the core import path
never pulls in ``cryptography`` at module load, so ``pip install intentflow``
(no extras) still imports and runs.
"""

from __future__ import annotations

import ast
import copy
from pathlib import Path

import pytest

from intentflow.auditor import audit_document
from intentflow.compiler import compile_program
from intentflow.parser import parse_file
from intentflow.runtime import GoalRuntime

cryptography = pytest.importorskip("cryptography")

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: E402
    Ed25519PrivateKey,
)

from intentflow.signing import Ed25519Signer, sign_root, verify_root  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _keypair() -> tuple[bytes, bytes]:
    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    pub_pem = priv.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return priv_pem, pub_pem


def _doc_and_result(signers=None):
    document = compile_program(parse_file("examples/production_diagnosis.iflow"))
    result = GoalRuntime(
        document["goals"][0],
        printer=None,
        workspace="examples/workspace",
        signers=signers,
    ).run()
    return document, result


def test_sign_verify_root_roundtrip() -> None:
    priv_pem, pub_pem = _keypair()
    root = "a" * 64
    entry = sign_root(root, priv_pem, key_id="ed-1")
    assert entry["algo"] == "ed25519"
    assert entry["key_id"] == "ed-1"
    assert verify_root(root, entry["signature"], pub_pem) is True
    assert verify_root("b" * 64, entry["signature"], pub_pem) is False


def test_run_signed_with_ed25519_verifies_with_public_key_only() -> None:
    priv_pem, pub_pem = _keypair()
    document, result = _doc_and_result(signers=[Ed25519Signer(priv_pem, "ed-1")])
    sigs = result["trace_chain"]["signatures"]
    assert [s["algo"] for s in sigs] == ["ed25519"]
    # Verify with ONLY the public key (default trusted key under None).
    report = audit_document(document, result, verifiers={None: pub_pem})
    assert report["conformant"] is True


def test_ed25519_without_public_key_is_nonconformant() -> None:
    priv_pem, _ = _keypair()
    document, result = _doc_and_result(signers=[Ed25519Signer(priv_pem)])
    report = audit_document(document, result)  # no verifiers
    assert any(v["code"] == "T3" for v in report["violations"])
    assert any("no trusted public key" in v["message"] for v in report["violations"])


def test_ed25519_wrong_public_key_is_invalid() -> None:
    priv_pem, _ = _keypair()
    _, other_pub = _keypair()
    document, result = _doc_and_result(signers=[Ed25519Signer(priv_pem)])
    report = audit_document(document, result, verifiers={None: other_pub})
    assert any("ed25519 signature is invalid" in v["message"] for v in report["violations"])


def test_tampered_event_breaks_ed25519_signed_trace() -> None:
    priv_pem, pub_pem = _keypair()
    document, result = _doc_and_result(signers=[Ed25519Signer(priv_pem)])
    tampered = copy.deepcopy(result)
    for event in tampered["trace"]:
        if event["event"] == "evidence_collected":
            event["detail"]["summary"] = "FORGED"
            break
    report = audit_document(document, tampered, verifiers={None: pub_pem})
    assert any(v["code"] == "T3" for v in report["violations"])


def test_dual_signing_hmac_and_ed25519() -> None:
    priv_pem, pub_pem = _keypair()
    document = compile_program(parse_file("examples/production_diagnosis.iflow"))
    result = GoalRuntime(
        document["goals"][0],
        printer=None,
        workspace="examples/workspace",
        sign_key=b"hmac-secret",
        key_id="ed-and-hmac",
        signers=[Ed25519Signer(priv_pem, "ed-and-hmac")],
    ).run()
    algos = sorted(s["algo"] for s in result["trace_chain"]["signatures"])
    assert algos == ["ed25519", "hmac-sha256"]
    report = audit_document(
        document,
        result,
        keys={"ed-and-hmac": b"hmac-secret"},
        verifiers={None: pub_pem},
    )
    assert report["conformant"] is True


def test_core_import_does_not_pull_in_cryptography() -> None:
    # signing.py must import cryptography only inside functions, so the core
    # package imports (and runs the simulator) without the optional extra.
    source = (ROOT / "intentflow" / "signing.py").read_text()
    tree = ast.parse(source)
    top_level_imports: list[str] = []
    for node in tree.body:  # module top level only
        if isinstance(node, ast.Import):
            top_level_imports += [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_level_imports.append(node.module.split(".")[0])
    assert "cryptography" not in top_level_imports
