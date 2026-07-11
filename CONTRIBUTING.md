# Contributing to IntentFlow

Thanks for your interest. IntentFlow is a small, zero-dependency codebase with
strong governance invariants — this guide covers setup, style, and the design
contract reviewers hold PRs to.

## Development setup

```bash
git clone https://github.com/dgenio/intentflow
cd intentflow
pip install -e ".[dev]"
python -m pytest
```

The runtime core has **zero third-party dependencies**; provider SDKs, signing,
schema validation, docs, and audit tooling are optional extras
(`.[llm]`, `.[openai]`, `.[sign]`, `.[docs]`, `.[audit]`). `.[dev]` pulls in
`pytest`, `jsonschema`, and `cryptography` so the whole suite runs.

## Design invariants (read before changing runtime code)

These are the contract the project is built on. A PR that weakens one will be
asked to change:

1. **Governance is enforced outside the model.** The ActionGate authorizes
   actions from the compiled plan, never from model output. A model cannot widen
   its own envelope.
2. **The gate never reads model output** to decide what is allowed.
3. **Judged checks are never silently passed.** An unparseable or failed
   judgment fails closed.
4. **Traces are append-only, hash-chained snapshots.** Don't mutate a trace
   after the fact or add unchained side channels for hashed material.
5. **The core stays dependency-free.** New third-party imports go in an optional
   extra, guarded by `tests/test_dependency_policy.py`.
6. **Failed verification is never reported as success** (audited as `S1`/`V1`).

See [`docs/architecture.md`](docs/architecture.md),
[`docs/concepts.md`](docs/concepts.md), and
[ADR 0002](docs/adr/0002-minimal-grammar-and-deterministic-simulator.md) for the
reasoning; [`docs/api-stability.md`](docs/api-stability.md) for the public/internal
boundary.

## Style and typing

- Python ≥ 3.10, fully type-hinted (the package ships `py.typed`).
- Match the surrounding code: naming, error handling, and test style. No lint or
  type-check tool is wired into CI yet (that's tracked separately); keep code
  clean by imitation.
- CLI changes follow [`docs/cli-conventions.md`](docs/cli-conventions.md).

## Tests are required for behavior changes

- Every behavior change needs a test that fails without the change.
- Match the existing pytest style (function tests, `parametrize`, the fixtures
  in `tests/`). Examples and docs snippets are kept honest by
  `tests/test_examples.py`, `tests/test_gallery.py`, and `tests/test_docs.py` —
  new examples must pass those sweeps.
- Run the full suite (`python -m pytest`) before opening a PR.

## Codebase map

One line per module (see [`README.md`](README.md) "Project layout" for more):

| Module | Role |
|--------|------|
| `parser.py`, `_grammar.py`, `iflow_ast.py` | source → AST |
| `analyzer.py`, `linter.py` | static diagnostics (`IFLOW###`) |
| `compiler.py` | AST → execution plan |
| `runtime.py` | the phase machine that executes a plan |
| `backends.py`, `judges.py`, `reliability.py` | cognition, judged verification, transport |
| `tools.py` | the ActionGate, tools, approvers |
| `trace.py`, `signing.py` | the hash-chained witness and its seals |
| `auditor.py` | independent conformance verification |
| `cli.py`, `api.py`, `explain.py`, `formatter.py` | interfaces |

## Pull requests

- Keep PRs focused; reference the issue they address.
- Fill in the PR template, including the invariants checklist.
- Questions and "how would I model X?" belong in
  [Discussions](https://github.com/dgenio/intentflow/discussions), not issues.

## Good first issues

Look for the [`good first issue`](https://github.com/dgenio/intentflow/labels/good%20first%20issue)
label. These are scoped to be startable without maintainer help; see
[`docs/labels.md`](docs/labels.md) for the full label taxonomy.

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). By
participating you agree to uphold it.
