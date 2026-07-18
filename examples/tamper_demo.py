#!/usr/bin/env python3
"""Tamper-evidence demo: forge a witness, watch the auditor catch it.

IntentFlow's deepest claim is that a run's witness can be checked by someone who
did not produce it — so a cover-up fails. This script makes that visceral:

  1. run a governed goal and keep its witness (the traced result);
  2. apply four realistic forgeries to fresh copies of the witness;
  3. audit each — and show the auditor naming the exact violation.

Runs offline with the deterministic simulate backend, stdlib only. A companion
test (`tests/test_tamper_demo.py`) imports `scenarios()` and asserts every
forgery is caught, so the demo cannot drift from the auditor.

    python examples/tamper_demo.py
"""

from __future__ import annotations

import copy
from typing import Callable

from intentflow.auditor import audit_document
from intentflow.compiler import compile_program
from intentflow.parser import parse_file
from intentflow.runtime import GoalRuntime

EXAMPLE = "examples/production_diagnosis.iflow"
WORKSPACE = "examples/workspace"


def honest_run() -> tuple[dict, dict]:
    """Produce a real document + witness to tamper with."""
    document = compile_program(parse_file(EXAMPLE))
    plan = document["goals"][0]
    result = GoalRuntime(plan, printer=None, workspace=WORKSPACE).run()
    return document, result


# -- forgeries ---------------------------------------------------------------
# Each takes a fresh witness copy, mutates it as a real cover-up would, and
# returns it. The auditor code each one is expected to trip is in `scenarios()`.


def _forge_hide_failed_check(witness: dict) -> dict:
    # Motive: the operator wants the failed verification to disappear, so the
    # run looks like it passed its own checks.
    for event in witness["trace"]:
        if event["event"] == "check_evaluated" and event["detail"].get("id") == "V1":
            event["detail"]["status"] = "fail"  # trace now contradicts the claim
    return witness


def _forge_inject_unapproved_action(witness: dict) -> dict:
    # Motive: slip in a deploy that never got the required human approval.
    witness["trace"].append(
        {
            "seq": len(witness["trace"]) + 1,
            "phase": "collect_evidence",
            "event": "tool_invoked",
            "detail": {"action": "deploy_change"},
        }
    )
    return witness


def _forge_cite_nonexistent_evidence(witness: dict) -> dict:
    # Motive: dress up a conclusion with a citation to evidence never collected.
    witness["citations"] = ["E99"]
    return witness


def _forge_launder_status(witness: dict) -> dict:
    # Motive: relabel an escalated ("needs_human") run as a clean completion.
    witness["status"] = "completed"
    return witness


def scenarios() -> list[tuple[str, str, Callable[[dict], dict]]]:
    """(title, expected auditor code, forgery) tuples — shared with the test."""
    return [
        ("hide a failed verification check", "V1", _forge_hide_failed_check),
        ("inject an unapproved gated action", "A2", _forge_inject_unapproved_action),
        ("cite nonexistent evidence", "E1", _forge_cite_nonexistent_evidence),
        ("launder an escalated run as completed", "S1", _forge_launder_status),
    ]


def main() -> int:
    document, witness = honest_run()

    print(f"Honest run of {EXAMPLE}: status={witness['status']!r}")
    baseline = audit_document(document, witness)
    print(f"  audit -> {'CONFORMANT' if baseline['conformant'] else 'NONCONFORMANT'}\n")

    all_caught = True
    for title, expected_code, forge in scenarios():
        tampered = forge(copy.deepcopy(witness))
        report = audit_document(document, tampered)
        codes = {v["code"] for v in report["violations"]}
        caught = not report["conformant"] and expected_code in codes
        all_caught = all_caught and caught
        message = next(
            (v["message"] for v in report["violations"] if v["code"] == expected_code),
            "(expected violation not found)",
        )
        status = "CAUGHT" if caught else "MISSED"
        print(f"[{status}] forge: {title}")
        print(f"         auditor: {expected_code} — {message}\n")

    print("All forgeries caught." if all_caught else "A forgery slipped through!")
    return 0 if all_caught else 1


if __name__ == "__main__":
    raise SystemExit(main())
