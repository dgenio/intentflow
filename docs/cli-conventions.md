# CLI design conventions and surface budget

This is a guardrail, written *before* the queued flag work lands, so the CLI
grows deliberately instead of accreting inconsistencies that become breaking
changes to fix later. It sets the target; it does not itself remove or rename
existing flags (those are owned by their respective issues).

## Surface budget

The CLI is a small set of subcommands, each doing one thing. `run` is the
widest command; before adding another flag to it, prefer: a sensible default,
reuse of an existing flag, or a new subcommand if the concern is genuinely
separate. New subcommands need a clear, non-overlapping job.

## Flag naming

- Long flags are `--kebab-case` (`--trace-dir`, `--record-cassette`).
- Boolean flags are `store_true` and named for the thing they enable
  (`--sign-trace`, `--verbose`); no `--no-*` negations unless a default must be
  overridden.
- Prefer one obvious spelling. Aliases (e.g. `--simulate` for
  `--backend simulate`) are a cost, not a convenience, and are not added lightly.

## Argument groups

Commands with many flags group them in `argparse` argument groups so `--help`
stays legible. `run` groups its flags as: **backend**, **target selection**,
**approvals**, **judging**, **trace output**, plus general output flags
(`--json`, `--verbose`). Grouping is presentation only — it never changes
parsing.

## `--json` policy

Every **read-only / diagnostic** command offers `--json` for machine-readable
output: `validate`, `lint`, `inspect`, `explain`, and `run` (`--json` prints the
full result). New read-only commands should include `--json` from the start.
Human-readable text remains the default.

## Environment variables

- **Provider-native** names for provider configuration: `OPENAI_API_KEY`,
  `OPENAI_BASE_URL`, `OPENAI_MODEL`, `ANTHROPIC_API_KEY`, etc. — so existing
  provider tooling works unchanged.
- **`IFLOW_*`** (or `INTENTFLOW_*`) for IntentFlow's own configuration:
  `IFLOW_TRACE_KEY`, `IFLOW_TRACE_KEY_ID`, `IFLOW_TRACE_KEYS`,
  `IFLOW_TRACE_SIGNING_KEY`, `INTENTFLOW_MAX_ATTEMPTS`.

Do not introduce a project setting under a provider-style name or vice versa.

## Exit codes

Exit codes are part of the contract (CI depends on them). The convention:

- `0` — success / conformant / no blocking findings.
- `1` — the operation ran but the outcome is a failure the user asked us to
  surface: validation errors, `lint --strict` warnings, a non-`completed` run
  status, a `NONCONFORMANT` audit, a `format --check` diff.
- `2` — the command could not run as invoked: a syntax/`ParseError`, a missing
  file, or bad arguments (argparse's own usage errors also use `2`).

A coherent, enumerated exception → exit-code mapping is owned by
[#66](https://github.com/dgenio/intentflow/issues/66); this doc states the
target so that issue and any CLI-touching change align to it.

## Checklist for a new flag or subcommand

Before adding one, answer:

1. **Who needs it, and can a default serve them instead?**
2. **Which command and which argument group does it belong to?**
3. **What is its `--json` story** (does it change machine-readable output)?
4. **What is its exit-code behavior** against the table above?
5. **Is it tested** in `tests/test_cli.py`?
6. **Is `--help` still legible** after adding it?

Deliberately breaking cleanups (removing the `--simulate` alias, reconciling
`--trace-out`/`--trace-dir`, the exit-code hierarchy) are deferred to the issues
that own them ([#107](https://github.com/dgenio/intentflow/issues/107),
[#66](https://github.com/dgenio/intentflow/issues/66)). This document is the
target they aim at.
