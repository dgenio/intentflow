"""Smoke test for the embedding tutorial's runnable example (see #86).

Keeps docs/embedding.md honest: the script it documents must run offline and
audit conformant.
"""

from __future__ import annotations

from examples.embedding.run_governed import main, run
from intentflow.auditor import audit_document


def test_embedding_example_runs_and_audits_conformant() -> None:
    document, result = run()
    assert result["status"] == "completed"
    # Both governed tools produced evidence through the gate.
    assert [item["origin"] for item in result["evidence"]] == [
        "tool:read_ticket",
        "tool:lookup_account",
    ]
    assert audit_document(document, result, sign_key=b"embedding-demo-key")[
        "conformant"
    ] is True


def test_embedding_example_main_exits_zero() -> None:
    assert main() == 0
