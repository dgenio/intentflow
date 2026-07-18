# Tamper-evidence demo

IntentFlow's deepest claim is that a run's **witness** can be verified by
someone who did not produce it — so a cover-up fails. This walkthrough makes it
concrete. The script is
[`examples/tamper_demo.py`](../examples/tamper_demo.py); run it offline:

```bash
python examples/tamper_demo.py
```

It runs `examples/production_diagnosis.iflow` on the simulate backend, keeps the
witness, then applies four realistic forgeries to fresh copies and audits each.

## What you'll see

```
Honest run of examples/production_diagnosis.iflow: status='needs_human'
  audit -> CONFORMANT

[CAUGHT] forge: hide a failed verification check
         auditor: V1 — check V1 failed in the trace but the result does not report the failure

[CAUGHT] forge: inject an unapproved gated action
         auditor: A2 — approval-gated action 'deploy_change' invoked without a prior approval grant

[CAUGHT] forge: cite nonexistent evidence
         auditor: E1 — result cites evidence that was never collected: E99

[CAUGHT] forge: launder an escalated run as completed
         auditor: S1 — status is 'completed' but the run recorded escalations

All forgeries caught.
```

## The four forgeries

Each is framed as a real motive, and each trips a specific auditor rule
(`intentflow/auditor.py`):

1. **Hide a failed verification check (`V1`).** The operator wants a failed
   check to disappear so the run looks clean. The auditor sees the trace record
   a failure the result claims passed, and flags the contradiction.
2. **Inject an unapproved gated action (`A2`).** A `deploy_change` is slipped
   into the trace without the approval grant it requires. Approval-gated actions
   must have a prior grant; this one doesn't.
3. **Cite nonexistent evidence (`E1`).** A conclusion is dressed up with a
   citation (`E99`) to evidence that was never collected. Every citation must
   point at real collected evidence.
4. **Launder an escalated run as completed (`S1`).** A run that escalated
   (`needs_human`) is relabeled `completed`. The reported status must be
   consistent with what the trace records.

## Why it can't drift

`tests/test_tamper_demo.py` imports the demo's `scenarios()` and asserts every
forgery is still caught with its expected code. If the auditor or the trace
shape changes such that a forgery would slip through, the test fails — so this
walkthrough can never quietly start lying.

See [`concepts.md`](concepts.md) for the auditor-code table and the
integrity-vs-authenticity distinction, and [`trace-signing.md`](trace-signing.md)
for sealing a witness so its *authenticity* (not just integrity) is verifiable.
