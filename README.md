# IntentFlow

**An experimental programming language for governed cognitive processes.**

> Classical programming languages describe deterministic procedures.
> LLM-native languages should describe **governed cognitive processes**.

IntentFlow is a small, serious prototype of that idea. Instead of writing
prompts or wiring chains of model calls, you declare *what a competent,
accountable reasoning process looks like* — its goal, the evidence it must
gather, the actions it may take, the checks its conclusions must pass, what
to do when it is unsure, and when a human must be consulted. The compiler
turns that declaration into an inspectable execution plan; the runtime
executes it with a full audit trace.

## Why this exists

Today's LLM systems hide their most important decisions inside
natural-language prompts: what counts as evidence, how confident the model
should be before acting, which tools it may call, what "done" means. Those
decisions are unauditable, untestable, and invisible until something goes
wrong.

IntentFlow's bet is that these concerns belong in a **language**, where they
become:

- **Inspectable before execution** — `intentflow compile` shows exactly what
  the agent will be allowed and required to do, before any model runs.
- **Statically checkable** — conflicting action policies, missing
  objectives, and out-of-range confidence thresholds are compile errors.
- **First-class semantics** — uncertainty, evidence, verification, and human
  escalation are control flow, not afterthoughts buried in prose.

### Why it is not just Python / LangChain / prompt templates

- **Not a framework.** Frameworks give you functions to call; the governance
  still lives in your head and your prompts. IntentFlow makes governance the
  *program text* — diffable, reviewable, lintable.
- **Not prompt templating.** Templates interpolate strings. IntentFlow
  compiles to a typed cognitive IR where `require_approval deploy_change`
  is a machine-enforced policy, not a sentence the model might ignore.
- **Not a chatbot wrapper.** There is no chat loop. There is a plan with
  phases, gates, and checks, and a trace of what actually happened.

## Core thesis

A program in IntentFlow specifies:

| Concern | Section | Example |
| --- | --- | --- |
| Goal | `objective:` | identify the most likely root cause |
| Context/memory policy | `context:` | `max_tokens 12000`, `preserve user_decisions` |
| Evidence requirements | `evidence:` | `require logs`, `distrust speculation_without_sources` |
| Reasoning discipline | `model:` | `separate observation from inference` |
| Governed actions | `actions:` | `allow read_logs`, `require_approval deploy_change` |
| Verification rules | `verify:` | `each hypothesis must cite evidence` |
| Uncertainty handling | `uncertainty:` | `if confidence < 0.7 ask_human` |
| Output contract | `output:` | `root_cause`, `confidence`, `risk` |

Human escalation (`ask_human`) is **normal control flow**, and every run
produces an **auditable trace** as a language/runtime feature, not a logging
add-on.

## Example

```text
goal DiagnoseProductionIssue {
  objective:
    identify the most likely root cause of a failing production job

  context:
    max_tokens 12000
    prefer recent_logs
    preserve user_decisions

  evidence:
    require logs
    require config
    require recent_commits
    distrust speculation_without_sources

  model:
    propose hypotheses with confidence
    separate observation from inference

  actions:
    allow read_logs
    allow inspect_code
    require_approval deploy_change

  verify:
    each hypothesis must cite evidence
    proposed fix must include rollback path

  uncertainty:
    if confidence < 0.7 ask_human
    if competing_hypotheses remain run_discriminating_test

  output:
    root_cause
    confidence
    recommended_fix
    risk
}
```

## Current MVP features

- **Parser** for `.iflow` files: line-based grammar, `#` comments, parse
  errors with file and line numbers.
- **Typed AST + cognitive IR**: `Goal`, `EvidenceRequirement`,
  `ActionPolicy`, `VerificationRule`, `UncertaintyRule`, `ContextPolicy`,
  `OutputSpec`.
- **Compiler** to a JSON execution plan: normalized objective, required
  evidence, allowed / approval-gated / denied actions, verification
  checklist, uncertainty policy, output contract, trace configuration, and
  a *staged* prompt plan (frame → evidence → model → verify → output).
- **Semantic validation**: missing objectives, conflicting action policies,
  malformed uncertainty rules, out-of-range confidence thresholds; warnings
  for goals with no evidence or verification.
- **Simulation runtime** (no LLM API required): executes the plan phase by
  phase with deterministic mock cognition — collects evidence, proposes
  hypotheses with confidence, applies uncertainty rules (including human
  escalation and discriminating tests), runs the verification checklist,
  and emits a structured result plus a complete audit trace.
- **CLI**: `parse`, `validate`, `compile`, `run --simulate`.

## Install & use

```bash
pip install -e ".[dev]"

intentflow parse    examples/diagnose.iflow      # print the AST as JSON
intentflow validate examples/diagnose.iflow      # semantic checks
intentflow compile  examples/diagnose.iflow      # print the execution plan
intentflow run      examples/diagnose.iflow --simulate

python -m pytest                                  # run the test suite
```

Three examples ship with the repo: `examples/diagnose.iflow`,
`examples/code_review.iflow`, and `examples/research_question.iflow`. Each
demonstrates evidence requirements, uncertainty handling, verification, and
action governance — not prompt templating.

## Honest status

This is an **experimental prototype**. The runtime mocks all cognition
deterministically so the *control structure* of the language can be
exercised and tested end to end. The grammar is intentionally minimal. The
value today is the shape of the abstraction: a compiled, inspectable,
verifiable plan for an agent, with uncertainty and escalation as language
semantics.

## Roadmap

1. **Real LLM backend** behind the same phase contract and trace format.
2. **Tool adapters** so `allow read_logs` binds to real, sandboxed tools.
3. **Memory/context compiler** that turns `context:` policy into concrete
   retrieval and eviction behavior.
4. **Confidence calibration** instead of trusting raw model self-reports.
5. **Static analysis** for unsafe action combinations and unreachable
   verification rules.
6. **Graph execution**: goals composed into DAGs with typed hand-offs.
7. **Python interop**: embed goals in Python programs and vice versa.
8. **Compiler optimizations** for token cost, latency, and risk.

See [`docs/architecture.md`](docs/architecture.md) for the conceptual stack
and design notes.

## Project layout

```
intentflow/
  __init__.py     public API
  iflow_ast.py    syntactic AST + cognitive IR nodes
  parser.py       .iflow -> AST
  compiler.py     AST -> validated execution plan (JSON)
  runtime.py      simulation runtime with audit trace
  cli.py          intentflow parse|validate|compile|run
examples/         three demonstration programs
tests/            parser, compiler, runtime, CLI tests
docs/             architecture notes
```

## License

MIT.
