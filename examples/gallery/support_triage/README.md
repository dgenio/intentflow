# support_triage — support-ticket triage with escalation

**Domain:** customer support · **Audience:** support leads

Routes an incoming ticket: resolve it, draft a reply, or escalate to a human —
and gates any refund on approval.

## Why these governance choices

- **`require issue_body`, `require comments`; `optional related_issues`.** The
  ticket and its thread are the basis for any decision; related issues add
  context when present.
- **`distrust unverified_customer_claims`.** The customer's report is input, not
  established fact — it cannot be the sole support for a resolution.
- **`require_approval issue_refund`.** Money movement is always gated on a human
  decision; the model can recommend a refund but never issue one unilaterally.
- **`check confidence >= 0.7`** and **`if confidence < 0.7 ask_human`** — an
  unsure triage routes to a person rather than guessing. With the simulator this
  run escalates (`needs_human`), which is the point: the policy prefers a human
  over a confident-sounding wrong answer.
- **`require response stays empathetic and on policy`** — a *judged* rule (no
  machine predicate can check tone), evaluated by the judge tier when `--judge`
  is set.

## Run it

```bash
intentflow run examples/gallery/support_triage/program.iflow \
    --workspace examples/gallery/support_triage/workspace \
    --judge simulate --trace-dir traces
intentflow audit examples/gallery/support_triage/program.iflow traces/<latest>.json
```
