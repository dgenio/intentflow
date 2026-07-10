#!/usr/bin/env python3
"""Embedding IntentFlow in Python: a governed ticket-triage run.

The companion tutorial is docs/embedding.md. This script is the runnable source
of truth for it — it exercises the whole embedding surface offline (simulate
backend + simulated judge, no keys):

  * load a program from inline source;
  * register two real Python functions as governed actions (they run only
    through the ActionGate);
  * supply a CallbackApprover that consults a real policy function;
  * run with a judge and an HMAC seal on the trace;
  * persist the witness to JSON;
  * audit it programmatically in a separate "verifier" step.

Run it:

    python examples/embedding/run_governed.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from intentflow import ActionDenied, CallbackApprover, audit_document, load_source

# A governed program: two evidence sources served by our own Python tools, an
# approval-gated action, machine verification, and a typed output.
PROGRAM = """\
goal ResolveTicket {
  objective:
    decide how to resolve a customer support ticket

  evidence:
    require ticket_body
    require account_record

  actions:
    allow read_ticket
    allow lookup_account
    require_approval issue_refund

  verify:
    require cites_evidence
    check confidence >= 0.6

  uncertainty:
    if confidence < 0.6 ask_human
    if missing_evidence ask_human

  output:
    resolution: string
    confidence: number
}
"""


def read_ticket(source: str) -> str:
    """A governed tool: fetch the ticket text. Runs only through the gate."""
    return "Customer reports a duplicate charge on their invoice."


def lookup_account(source: str) -> str:
    """A governed tool: fetch the account record."""
    return "Account: enterprise plan; one duplicate charge confirmed in billing."


def approval_policy(action: str, context: dict) -> bool:
    """A real approver: auto-approve small refunds, escalate everything else.

    In a real app this would consult a human, a queue, or a policy service.
    """
    return action == "issue_refund"  # our policy: refunds are pre-authorized here


def run() -> tuple[dict, dict]:
    program = load_source(PROGRAM, name="resolve_ticket")

    # Wire our Python functions to the evidence sources they serve.
    program.register_tool("read_ticket", serves=("ticket_body",), handler=read_ticket)
    program.register_tool(
        "lookup_account", serves=("account_record",), handler=lookup_account
    )

    result = program.run(
        approver=CallbackApprover(approval_policy),
        judge="simulate",
        sign_key=b"embedding-demo-key",
        printer=None,  # quiet mode; pass print to narrate
    )
    document = program.compile()
    return document, result


def verify(document: dict, witness_path: Path) -> dict:
    """A separate verifier: load the persisted witness and audit it. This is
    what a third party (CI, a reviewer) would run — it trusts only the file."""
    witness = json.loads(witness_path.read_text())
    return audit_document(document, witness, sign_key=b"embedding-demo-key")


def main() -> int:
    document, result = run()

    # The governed tools produced evidence through the gate.
    origins = [item["origin"] for item in result["evidence"]]
    print(f"status:   {result['status']}")
    print(f"evidence: {origins}")

    # An approval decision that our policy could have denied.
    try:
        print(f"outputs:  {result['outputs']}")
    except KeyError:
        pass

    # Persist the witness, then verify it from disk in a separate step.
    with tempfile.TemporaryDirectory() as tmp:
        witness_path = Path(tmp) / "witness.json"
        witness_path.write_text(json.dumps(result, indent=2))
        report = verify(document, witness_path)

    verdict = "CONFORMANT" if report["conformant"] else "NONCONFORMANT"
    print(f"audit:    {verdict}")

    # A failure path: an approver that denies the gated action blocks it.
    demo_denied_path()

    return 0 if report["conformant"] else 1


def demo_denied_path() -> None:
    """Show ActionDenied handling when the approver refuses a gated action."""
    program = load_source(PROGRAM, name="resolve_ticket")
    program.register_tool("read_ticket", serves=("ticket_body",), handler=read_ticket)
    program.register_tool(
        "lookup_account", serves=("account_record",), handler=lookup_account
    )
    try:
        # Deny everything: the gated refund can never be approved.
        program.run(approver=CallbackApprover(lambda action, ctx: False))
    except ActionDenied as exc:  # pragma: no cover - defensive; run() traces instead
        print(f"denied path: ActionDenied -> {exc}")
    else:
        print("denied path: gated action was not invoked (nothing to approve)")


if __name__ == "__main__":
    raise SystemExit(main())
