# IntentFlow Examples

Five example programs ship with the repository, plus `examples/workspace/`
— a directory of real evidence files that the built-in read-only tools
serve through the action gate when you pass `--workspace`.

Run any of them after `pip install -e .`.

## `opensource_triage.iflow` — the flagship

Governed GitHub issue triage. Demonstrates typed outputs, optional
evidence, an approval-gated outward action (`post_comment`), a denied
action (`close_issue`), machine + judged verification, and uncertainty
rules that escalate or block.

```bash
intentflow validate examples/opensource_triage.iflow
intentflow explain  examples/opensource_triage.iflow
intentflow run      examples/opensource_triage.iflow --trace-dir traces
# -> status: completed, exit 0
```

## `production_diagnosis.iflow` — escalation by design

Root-cause analysis with real evidence collection. In simulate mode the
calibrated confidence (0.676) lands below the goal's 0.7 threshold, so the
run deliberately ends `needs_human`: an unsure diagnosis must not
auto-complete.

```bash
intentflow run examples/production_diagnosis.iflow \
    --workspace examples/workspace --trace-dir traces --verbose
# -> status: needs_human (this is the point)
```

The trace shows `read_logs` and `inspect_code` actually reading
`examples/workspace/*.txt` through the gate.

## `code_review.iflow` — structured review output

Read-only review of a diff with typed findings (`findings: list[string]`,
`blocking_issues: list[string]`) and an approval gate on posting.

```bash
intentflow run examples/code_review.iflow --workspace examples/workspace
```

## `research_synthesis.iflow` — warnings, not errors

Intentionally validates with warnings: only one required evidence source
(IFLOW009) and one untyped output field (IFLOW017). Useful to see the
analyzer's advisory tier.

```bash
intentflow validate examples/research_synthesis.iflow   # exit 0, with warnings
intentflow lint     examples/research_synthesis.iflow
```

## `high_risk_deploy.iflow` — blocked by policy

Deliberately dangerous: it allows `deploy_change` without an approval gate.
The analyzer warns (IFLOW010), the compiled risk profile is `high`, and at
runtime `if security_risk block_action` fires:

```bash
intentflow run examples/high_risk_deploy.iflow
# -> status: blocked, exit 1
```

The denied `write_database` action can never run regardless of model
output.

## `incident_pipeline.iflow` — goal composition

Two goals composed into a pipeline. `ProposeRemediation` requires
`DiagnoseIncident.root_cause`; the compiler statically verifies the chain,
and at runtime the first stage's outputs become seeded evidence for the
second.

```bash
intentflow run examples/incident_pipeline.iflow --pipeline IncidentResponse
```

## After any run

```bash
intentflow replay traces/<artifact>.json        # readable execution story
intentflow replay traces/<artifact>.json --json # machine-readable
intentflow audit  examples/opensource_triage.iflow traces/<artifact>.json
```
