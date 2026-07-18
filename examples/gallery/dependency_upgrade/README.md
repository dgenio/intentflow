# dependency_upgrade — dependency-upgrade risk assessment

**Domain:** dependency management · **Audience:** maintainers

Weighs a proposed dependency bump — especially a major version — against the
changelog, a compatibility probe, and the current test baseline.

## Why these governance choices

- **`require config`, `require recent_commits`, `require test_results`.** All
  three are load-bearing: what is changing, what the changelog says, and whether
  the current suite still passes.
- **`distrust vendor_marketing`.** Release notes framed as marketing cannot be
  the sole basis for adopting a breaking change.
- **`require_approval merge_upgrade`.** The upgrade lands only with human
  sign-off; the assessment informs that decision, it does not make it.
- **`check confidence >= 0.7`** with **`if competing_hypotheses
  run_discriminating_test`** — when the risk is genuinely ambiguous, the policy
  runs a discriminating test rather than picking a side. With the simulator this
  escalates (`needs_human`) — a major bump with a non-trivial migration surface
  is exactly what a human should see.
- **Typed output** including `breaking_changes: list[string]` and
  `migration_steps: markdown` — the recommendation is structured, not prose.

## Run it

```bash
intentflow run examples/gallery/dependency_upgrade/program.iflow \
    --workspace examples/gallery/dependency_upgrade/workspace --trace-dir traces
intentflow audit examples/gallery/dependency_upgrade/program.iflow traces/<latest>.json
```
