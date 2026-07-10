# Example gallery: governed agents for real operational domains

Each example is a complete governed program you can read, run, and adapt —
shipped with its own realistic `workspace/` and a README explaining the
governance choices. All run offline on the deterministic simulate backend and
audit conformant (enforced by `tests/test_gallery.py`).

Run any of them:

```bash
intentflow run examples/gallery/<name>/program.iflow \
    --workspace examples/gallery/<name>/workspace --trace-dir traces --verbose
intentflow audit traces/<latest>.json
```

| Example | Domain | Audience | Shows |
|---------|--------|----------|-------|
| [`change_review`](change_review) | Change-management review | SRE / platform | approval-gated deploy, rollback requirement, clean completion |
| [`support_triage`](support_triage) | Support-ticket triage | Support lead | human escalation, approval-gated refund, a judged tone/policy check |
| [`dependency_upgrade`](dependency_upgrade) | Dependency-upgrade risk | Maintainer | risk weighing, discriminating test on competing hypotheses |
| [`security_alert`](security_alert) | Security-alert triage | Security engineer | a two-stage pipeline, `deny` on destructive actions |

## Routing and escalation policy

`change_review` and `support_triage` double as **model-routing / human-escalation
policy** examples: they express, as declared policy rather than prompt text, when
work proceeds automatically, when it is approval-gated, and when it routes to a
human. The trace explains *why* each outcome was reached — a low-confidence run
escalates, a production-boundary action is gated, a refund the policy cannot
authorize goes to a person. See `docs/concepts.md` for the vocabulary.

## Language-feature coverage

Across the gallery, every construct is exercised at least once: all three
evidence stances (`require` / `optional` / `distrust`), all three action modes
(`allow` / `require_approval` / `deny`), threshold and symbolic uncertainty
rules, both machine predicates (`cites_evidence` and a `must include` phrase
check), a judged verification rule, typed output contracts (including `list[…]`
and `boolean`), and a multi-goal pipeline.
