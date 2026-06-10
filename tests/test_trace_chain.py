"""Hash-chained / signed trace tests: tamper-evidence that holds standalone,
without the program, plus HMAC signature verification."""

from __future__ import annotations

import copy

import pytest

from intentflow.auditor import _check_trace_chain, audit_document
from intentflow.compiler import compile_program
from intentflow.parser import parse_file
from intentflow.runtime import GENESIS_HASH, GoalRuntime


def _doc_and_result(sign_key: bytes | None = None):
    document = compile_program(parse_file("examples/diagnose.iflow"))
    result = GoalRuntime(
        document["plans"][0], printer=None, workspace="examples/workspace",
        sign_key=sign_key,
    ).run()
    return document, result


def test_honest_chain_verifies_standalone() -> None:
    _, result = _doc_and_result()
    assert result["trace"][0]["prev_hash"] == GENESIS_HASH
    assert _check_trace_chain(result["trace"], result["trace_chain"]) == []


def test_altering_an_event_breaks_the_chain() -> None:
    document, result = _doc_and_result()
    tampered = copy.deepcopy(result)
    # Flip an evidence summary deep in the trace — no plan needed to catch it.
    for event in tampered["trace"]:
        if event["event"] == "evidence_collected":
            event["detail"]["summary"] = "FORGED"
            break
    violations = _check_trace_chain(tampered["trace"], tampered["trace_chain"])
    assert any(v.code == "T3" for v in violations)
    # And the full audit flags it too.
    report = audit_document(document, tampered)
    assert any(v["code"] == "T3" for v in report["violations"])


def test_deleting_an_event_breaks_the_chain() -> None:
    _, result = _doc_and_result()
    tampered = copy.deepcopy(result)
    del tampered["trace"][4]
    assert any(v.code == "T3" for v in _check_trace_chain(tampered["trace"]))


def test_reordering_events_breaks_the_chain() -> None:
    _, result = _doc_and_result()
    tampered = copy.deepcopy(result)
    tampered["trace"][3], tampered["trace"][4] = (
        tampered["trace"][4], tampered["trace"][3],
    )
    assert any(v.code == "T3" for v in _check_trace_chain(tampered["trace"]))


def test_signed_trace_verifies_with_key() -> None:
    key = b"topsecret"
    document, result = _doc_and_result(sign_key=key)
    assert result["trace_chain"]["signature"] is not None
    report = audit_document(document, result, sign_key=key)
    assert report["conformant"] is True


def test_signed_trace_without_key_is_nonconformant() -> None:
    document, result = _doc_and_result(sign_key=b"topsecret")
    report = audit_document(document, result)  # no key supplied
    assert any(v["code"] == "T3" for v in report["violations"])


def test_bad_signature_is_detected() -> None:
    document, result = _doc_and_result(sign_key=b"topsecret")
    report = audit_document(document, result, sign_key=b"wrongkey")
    assert any("signature is invalid" in v["message"] for v in report["violations"])


def test_unsigned_trace_needs_no_key() -> None:
    document, result = _doc_and_result()
    assert result["trace_chain"]["signature"] is None
    assert audit_document(document, result)["conformant"] is True
