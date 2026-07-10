# change_review — governed change-management review

**Domain:** production change review · **Audience:** SRE / platform engineers

Decides whether a proposed production change is safe to ship. A good first read
for how routing policy is *declared*, not prompted.

## Why these governance choices

- **`require diff`, `require config`; `optional related_issues`.** The diff and
  environment config are load-bearing, so they are required; prior related
  issues help but their absence should not block a review, so they are optional.
- **`distrust unreviewed_claims`.** Anything not backed by the diff or config
  cannot be the sole support for shipping.
- **`allow read_diff / inspect_code / search_repo`** — read-only tools the
  review needs. **`require_approval deploy_change`** — actually shipping is
  gated on a human. **`deny delete_database`** — destructive actions are off the
  table entirely, regardless of the model.
- **`check confidence >= 0.6`** plus **`proposed change must include rollback
  path`** — a change is only auto-approved when the model is calibrated-confident
  *and* the recommendation carries a rollback. With the workspace provided the
  run completes; raise the threshold and it escalates instead.
- **`if security_risk ask_human`** — a security signal always routes to a person.

## Run it

```bash
intentflow run examples/gallery/change_review/program.iflow \
    --workspace examples/gallery/change_review/workspace --trace-dir traces
intentflow audit traces/<latest>.json
```
