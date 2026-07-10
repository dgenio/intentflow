# ADR 0002 — Minimal line-based grammar and deterministic simulator

- **Status:** Accepted
- **Date:** 2026-07
- **Issue:** [#50](https://github.com/dgenio/intentflow/issues/50)
- **Related:** #14 (language reference), #26 (contributing guide), #48
  (conformance kit), #7/#8 (roadmap features layered on top)

## Context

Two of IntentFlow's foundations are easy to mistake for immaturity and tempting
to "upgrade":

1. **A minimal, line-based grammar.** `intentflow/parser.py` is a hand-written,
   line-oriented parser (`intentflow/_grammar.py` holds the four surface
   patterns). Its docstring says so explicitly: "the grammar is deliberately
   simple and line-based."
2. **A deterministic simulated-cognition backend.** `SimulatedCognition`
   (`intentflow/backends.py`) is the default backend and produces the same
   output for the same plan, with no network and no flakiness.

Both look like things a "serious" language would replace — with a parser
generator and a real model, respectively. This ADR records why they are
deliberate so the decision is reviewed, not drifted past.

## Decision

Keep the minimal line-based grammar and the deterministic simulator as the
project's foundations. Layer richer features (DAG pipelines, richer predicates,
calibration) *on top of* them rather than replacing them.

## Rationale

**The grammar earns its minimalism.**
- Every statement is a line, so every diagnostic carries an exact line number
  (`iflow_ast.Statement.line`), used by the compiler, analyzer, and linter. This
  is what makes `validate`/`lint` output precise and actionable.
- A hand-written parser has no build step, no generated code, and no third-party
  dependency — consistent with the zero-runtime-dependency core
  (`tests/test_dependency_policy.py`).
- The surface is small enough that the [language reference](../language-reference.md)
  is complete and checkable.

**The simulator is the conformance reference.**
- It lets the *entire* control structure — phase machine, gates, verification,
  uncertainty, trace/audit — be tested end-to-end without keys, network, or
  nondeterminism. Nearly the whole test suite depends on this.
- It makes the signature demo (run → tamper → audit) reproducible on any
  machine, offline.
- A conformance kit (#48) needs a deterministic reference to define "correct"
  against; the simulator is it.

## Non-goals

- This ADR does **not** say the grammar or simulator can never change. It says
  change must be justified.
- It does not preclude real backends (they already exist as opt-in extras) or
  richer language features (they are on the roadmap).

## The bar for revisiting

A proposal to replace either foundation must:

1. Show a concrete need the current design cannot meet (not surface novelty).
2. Preserve **line-accurate diagnostics** (for the grammar) and a
   **deterministic conformance reference** (for the simulator).
3. Include a migration plan and pass the conformance kit (#48) once it exists.

## Consequences

- Contributors and reviewers have a written contract to point at when a PR
  proposes swapping in a parser generator or making the default backend
  nondeterministic. `CONTRIBUTING.md` links here for grammar/runtime changes.
- New language features are expected to extend the line-based grammar, not
  replace it; new backends are additive and never displace the simulator as the
  default and the reference.
