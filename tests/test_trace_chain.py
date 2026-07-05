"""Hash-chained / signed trace tests: tamper-evidence that holds standalone,
without the program, plus HMAC signature verification."""

from __future__ import annotations

import copy

from intentflow.auditor import _check_trace_chain, audit_document
from intentflow.compiler import compile_program
from intentflow.parser import parse_file
from intentflow.runtime import GoalRuntime
from intentflow.trace import GENESIS_HASH


def _doc_and_result(sign_key: bytes | None = None, key_id: str | None = None):
    document = compile_program(parse_file("examples/production_diagnosis.iflow"))
    result = GoalRuntime(
        document["goals"][0], printer=None, workspace="examples/workspace",
        sign_key=sign_key, key_id=key_id,
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
    sigs = result["trace_chain"]["signatures"]
    assert [s["algo"] for s in sigs] == ["hmac-sha256"]
    assert "key_id" not in sigs[0]  # keyless seal
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
    assert result["trace_chain"]["signatures"] == []
    assert audit_document(document, result)["conformant"] is True


# -- key ids and rotation (issue #80) ---------------------------------------


def test_key_id_seal_verifies_with_matching_key_from_a_set() -> None:
    document, result = _doc_and_result(sign_key=b"prod1-secret", key_id="prod1")
    sig = result["trace_chain"]["signatures"][0]
    assert sig["algo"] == "hmac-sha256"
    assert sig["key_id"] == "prod1"
    # A rotation set holding several keys verifies by picking the one named.
    keys = {"prod1": b"prod1-secret", "prod2": b"prod2-secret"}
    report = audit_document(document, result, keys=keys)
    assert report["conformant"] is True


def test_rotated_witness_still_verifies_after_new_key_added() -> None:
    # Old witness signed with the retired key; verifier keeps it in the set.
    document, result = _doc_and_result(sign_key=b"old-secret", key_id="2026-06")
    keys = {"2026-07": b"new-secret", "2026-06": b"old-secret"}
    assert audit_document(document, result, keys=keys)["conformant"] is True


def test_unknown_key_id_is_a_distinct_violation() -> None:
    document, result = _doc_and_result(sign_key=b"secret", key_id="retired")
    report = audit_document(document, result, keys={"current": b"secret"})
    msgs = [v["message"] for v in report["violations"]]
    assert any("unknown key id" in m for m in msgs)
    assert not any("signature is invalid" in m for m in msgs)


def test_wrong_key_for_known_id_is_invalid_signature() -> None:
    document, result = _doc_and_result(sign_key=b"right", key_id="prod1")
    report = audit_document(document, result, keys={"prod1": b"wrong"})
    msgs = [v["message"] for v in report["violations"]]
    assert any("signature is invalid" in m and "prod1" in m for m in msgs)


def test_key_id_seal_needs_the_named_key_not_the_default() -> None:
    # A key-id'd seal is not verifiable by the keyless default key alone.
    document, result = _doc_and_result(sign_key=b"secret", key_id="prod1")
    report = audit_document(document, result, sign_key=b"secret")  # no keys map
    assert any(v["code"] == "T3" for v in report["violations"])


def test_parse_key_set_env() -> None:
    from intentflow.cli import _parse_key_set

    parsed = _parse_key_set(" prod1 = s1 , prod2=s2 ,bad, =nokey, id3= ")
    assert parsed == {"prod1": b"s1", "prod2": b"s2"}
