# Embedding IntentFlow in Python

Most teams will not replace their application with a DSL — but they will embed
one. This is the library-shaped companion to the CLI [quickstart](quickstart.md):
how to drive a governed run from your own code, register real tools, plug in a
custom approver and judge, seal the trace, and audit the witness
programmatically.

Every code block here is exercised by the runnable script
[`examples/embedding/run_governed.py`](../examples/embedding/run_governed.py)
(smoke-tested in `tests/test_embedding_example.py`), so it cannot drift. It runs
offline with the simulate backend and a simulated judge — no keys.

## Load a program

```python
from intentflow import load, load_source

program = load("triage.iflow")        # from a file
program = load_source(SOURCE_STRING)  # or from inline source
```

`load`/`load_source` return an `IntentFlowProgram` — the embedding handle. It
exposes `validate()`, `compile()`, `inspect()`, `explain()`, `run()`, and
`run_pipeline()`.

## Register governed tools

Wire your own Python functions to the evidence sources a goal requires. The
handler runs **only** through the ActionGate — a source with no registered tool
(and no workspace) is not silently invented:

```python
def read_ticket(source: str) -> str:
    return fetch_ticket_text()

program.register_tool("read_ticket", serves=("ticket_body",), handler=read_ticket)
```

`register_tool(action, serves, handler, description="")` returns the program, so
calls chain.

## Supply a custom approver

An approval-gated action (`require_approval` in the program) needs a decision.
`CallbackApprover` delegates to any `(action, context) -> bool | ApprovalDecision`
callable — consult a human, a queue, or a policy service:

```python
from intentflow import CallbackApprover

def approval_policy(action: str, context: dict) -> bool:
    return action == "issue_refund"   # your real policy goes here

result = program.run(approver=CallbackApprover(approval_policy))
```

The built-in `PreGrantedApprover` (used by the CLI's `--approve`) is available
too; both fail closed — anything not approved is denied.

## Run with a judge and a sealed trace

```python
result = program.run(
    approver=CallbackApprover(approval_policy),
    judge="simulate",              # a separate trust tier for judged verify rules
    sign_key=b"your-hmac-key",     # HMAC-seal the trace chain
    printer=None,                  # quiet; pass `print` to narrate every phase
)
```

`run(...)` returns the traced result dict. A validation failure yields
`status == "failed_validation"` rather than raising, so you branch on status:

```python
if result["status"] == "completed":
    use(result["outputs"])
elif result["status"] == "needs_human":
    escalate(result["escalations"])
```

## Persist and audit the witness

The result is the witness. Save it, then verify it in a separate step — exactly
what a third party (CI, a reviewer) would do, trusting only the file:

```python
import json
from pathlib import Path
from intentflow import audit_document

Path("witness.json").write_text(json.dumps(result, indent=2))

document = program.compile()
witness = json.loads(Path("witness.json").read_text())
report = audit_document(document, witness, sign_key=b"your-hmac-key")
assert report["conformant"], report["violations"]
```

## Handle denial

When an approver refuses a gated action, the run records the denial and ends in
a non-`completed` status rather than performing the action. If you drive the
gate directly, `ActionDenied` is raised — import it from `intentflow`:

```python
from intentflow import ActionDenied
```

## Pipelines

```python
program = load("examples/incident_pipeline.iflow")
result = program.run_pipeline("IncidentResponse")
for stage in result["stages"]:
    print(stage["goal"], stage["status"])
```

## What's public

Only the names in [`api-stability.md`](api-stability.md) carry a stability
promise. The symbols used above — `load`, `load_source`, `IntentFlowProgram`,
`CallbackApprover`, `audit_document`, `ActionDenied` — are all part of it.
