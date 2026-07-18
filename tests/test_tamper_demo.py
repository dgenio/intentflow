"""The tamper demo must stay in sync with the auditor (see #28).

If a forgery in examples/tamper_demo.py stops being caught — because the
auditor or the trace shape changed — this test fails, so the demo can never
quietly start lying about tamper-evidence.
"""

from __future__ import annotations

import copy

from intentflow.auditor import audit_document

from examples.tamper_demo import honest_run, main, scenarios


def test_every_forgery_is_caught_with_its_expected_code() -> None:
    document, witness = honest_run()
    assert audit_document(document, witness)["conformant"] is True

    for title, expected_code, forge in scenarios():
        tampered = forge(copy.deepcopy(witness))
        report = audit_document(document, tampered)
        assert report["conformant"] is False, title
        codes = {v["code"] for v in report["violations"]}
        assert expected_code in codes, f"{title}: expected {expected_code}, got {codes}"


def test_demo_main_exits_zero() -> None:
    assert main() == 0
