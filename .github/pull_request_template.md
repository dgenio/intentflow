<!-- Thanks for contributing to IntentFlow! Please fill this in. -->

## What changed

<!-- A short description of the change, and the issue it addresses (Closes #NNN). -->

## Why

<!-- The motivation / problem this solves. -->

## How verified

<!-- Exact commands run and their results, e.g. `python -m pytest -q` → N passed. -->

## Design invariants checklist

Confirm the change respects IntentFlow's governance contract (see
[CONTRIBUTING.md](../CONTRIBUTING.md)); check or mark N/A:

- [ ] Governance stays enforced outside the model (the gate authorizes from the
      plan, not from model output).
- [ ] Judged checks still fail closed; failed verification is never reported as
      success.
- [ ] Traces remain append-only and hash-chained; no unchained side channel for
      hashed material.
- [ ] The runtime core stays dependency-free (new deps are optional extras).
- [ ] Behavior changes have tests that fail without the change.
- [ ] Docs / examples updated if user-facing behavior changed (and the doc/
      example sweeps still pass).

## Notes / risks

<!-- Anything reviewers should know: tradeoffs, follow-ups, breaking changes. -->
