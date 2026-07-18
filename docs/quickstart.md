# Quickstart — from install to an audited run in 5 minutes

No API key, no network. Everything below uses the deterministic **simulated**
backend, so it runs the same on every machine. It ends at IntentFlow's "aha"
moment: hand-edit a run's trace and watch the auditor catch it.

## 1. Install

```bash
pip install intentflow
```

The core has zero third-party dependencies. Check it:

```bash
intentflow --help
```

## 2. Write a minimal goal

Save this as `triage.iflow` (it exercises evidence, an approval-gated action,
verification, an uncertainty escalation, and a typed output):

```iflow
goal TriageBug {
  objective:
    decide whether an incoming bug report is actionable

  evidence:
    require issue_body
    require comments

  actions:
    allow read_issue
    require_approval close_issue

  verify:
    require cites_evidence
    check confidence >= 0.6

  uncertainty:
    if confidence < 0.6 ask_human
    if missing_evidence ask_human

  output:
    verdict: string
    confidence: number
    rationale: markdown
}
```

## 3. Compile and read the plan

```bash
intentflow compile triage.iflow
```

The plan is the **contract**: the objective, the evidence policy, the action
envelope (allowed / denied / approval-gated), verification rules, and the typed
output schema — all inspectable before anything runs.

## 4. Run it and save the witness

```bash
intentflow run triage.iflow --simulate --trace-out result.json
```

`result.json` is the **witness**: the structured output plus a hash-chained
trace of every phase the run went through.

## 5. Audit the witness (conformant)

```bash
intentflow audit triage.iflow result.json
```

You'll see a `CONFORMANT` verdict — the run stayed inside its contract.

## 6. Tamper with the witness, then audit again (caught)

Forge the result — claim a citation to evidence that was never collected — and
re-audit:

```bash
python -c "import json; d=json.load(open('result.json')); \
d['result']['citations']=['E99']; json.dump(d, open('result.json','w'))"
intentflow audit triage.iflow result.json
```

Now the audit reports `NONCONFORMANT` with the specific violation (`E1`: the
result cites evidence that was never collected). You did not have to trust the
runtime — the witness is checked against the contract.

## Where to go next

- [`language-reference.md`](language-reference.md) — every section, statement
  form, and diagnostic.
- [`concepts.md`](concepts.md) — contract, witness, envelope, trust tiers.
- [`embedding.md`](embedding.md) — drive IntentFlow from Python.
- [`backends.md`](backends.md) — swap the simulator for a real model.
- The [`examples/`](../examples) directory — six governed programs to read and run.
