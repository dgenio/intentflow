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

IntentFlow is **not** trying to replace Python. Python programs *deterministic
computation*; IntentFlow programs *governed cognition*. They compose — an
IntentFlow goal can call Python functions as governed actions, and Python can
compile and run an IntentFlow goal.

| | What you write | Determinism | Where governance lives | Auditable? |
| --- | --- | --- | --- | --- |
| **Python function** | exact instructions | fully deterministic | in your code | yes, but it isn't cognition |
| **Prompt template** | interpolated strings | none | inside prose the model may ignore | no — output only |
| **Agent framework** | functions to wire up | partial | in your head + your prompts | partial, ad-hoc logging |
| **IntentFlow goal** | declared evidence, actions, checks, uncertainty | governed: gates & checks outside the model | in the *program text* — compiled & enforced | yes — every run emits a replayable witness |

- **Not a framework.** Frameworks give you functions to call; the governance
  still lives in your head and your prompts. IntentFlow makes governance the
  *program text* — diffable, reviewable, lintable.
- **Not prompt templating.** Templates interpolate strings. IntentFlow
  compiles to a typed cognitive IR where `require_approval deploy_change`
  is a machine-enforced policy, not a sentence the model might ignore.
- **Not a chatbot wrapper.** There is no chat loop. There is a plan with
  phases, gates, and checks, and a trace of what actually happened.

Concretely, an IntentFlow goal compiles into an **agent plan**: a JSON
execution plan with a staged prompt plan (one inspectable block per concern —
system role, objective, evidence, allowed actions, denied actions,
verification, uncertainty handling, output format), an action policy the
runtime enforces *outside* the model, and a risk profile a reviewer reads
before approving a run.

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

## The deep angle: programs as contracts, traces as witnesses

The honest objection to any "agent DSL" is: *couldn't this just be a Python
dataclass?* A dataclass can hold the same fields. What it cannot do is give
the fields **semantics that survive the model boundary**. IntentFlow's
answer has three parts:

1. **The program is a contract.** `require_approval deploy_change` is not
   data the runtime may consult; it is a policy the
   [`ActionGate`](intentflow/tools.py) enforces *outside the model*. A tool
   the goal does not allow cannot run — the model cannot talk its way past
   the gate, because the gate never reads model output.
2. **The trace is a witness.** Every run emits an append-only trace in a
   defined format: every tool invocation, approval, rule evaluation, check
   result, and escalation, in canonical phase order.
3. **Conformance is independently verifiable.** `intentflow audit` replays
   a result against the recompiled plan and proves — without trusting the
   runtime, the backend, or the model — that the run stayed inside its
   envelope: no denied action ran, every gated action has a prior approval
   grant, every citation points at collected evidence, no verification
   failure was dropped from the result, the output contract was met.

This is *proof-carrying agent behavior*: the same move that audit logs +
seccomp profiles made for processes, applied to cognition. A dataclass can
describe an envelope; it cannot make violations of the envelope detectable
by a third party. That property has to live in a language + runtime + trace
format that agree with each other — which is exactly what IntentFlow is.

## Current features

- **Parser** for `.iflow` files: line-based grammar, `#` comments, parse
  errors with file and line numbers; `goal` blocks and `pipeline` blocks.
- **Typed AST + cognitive IR**: `Goal`, `Pipeline`, `EvidenceRequirement`,
  `ActionPolicy`, `VerificationRule`, `UncertaintyRule`, `ContextPolicy`,
  `OutputSpec`.
- **Compiler** to a JSON execution plan: normalized objective, evidence by
  stance, allowed / approval-gated / denied actions, **typed verification
  checks** (machine-checkable `cites_evidence` / `requires_phrase` /
  `threshold_check` vs LLM-judged — the distinction is part of the plan),
  uncertainty policy, **calibration policy**, a **risk profile**, output
  contract, and a **staged prompt plan** with one inspectable block per
  governance concern (system → objective → evidence → allowed actions →
  denied actions → verify → uncertainty → output).
- **Goal composition**: pipelines whose evidence chains
  (`require DiagnoseIncident.root_cause`) are **statically checked** — a
  stage cannot require an output no earlier stage produces.
- **Static analysis** (`intentflow lint`): destructive actions allowed
  without safeguards, unreachable or duplicate uncertainty thresholds,
  conditions and rules that cannot be enforced.
- **Governed runtime**: cognition is a pluggable backend — deterministic
  simulation (default), a real Claude model via `--backend anthropic`, or any
  OpenAI-compatible endpoint via `--backend openai` (OpenAI, Azure, local
  vLLM/Ollama through env vars) — but governance is not pluggable. Evidence
  collection runs through the action gate, raw confidence is calibrated
  before uncertainty rules fire, judged verification rules are recorded as
  *skipped*, never silently passed, and `ask_human` / approval gates are
  control flow. Each run also returns a flat **summary** (confidence,
  verification status, uncertainty status, actions requested/blocked,
  trace id).
- **Blocking approval gates** (`tools.Approver`): approval-gated actions can
  be pre-granted (`--approve`), prompted interactively on a TTY
  (`--approve-interactive`), or resolved by a synchronous webhook
  (`--approve-webhook URL`). Every decision — and the channel it came
  through — is recorded in the trace; fail-closed by default.
- **LLM-judge runner** (`--judge`): `judged` verification rules can be
  evaluated by an LLM judge (`simulate`, `openai`, or `anthropic`) in a
  **separate trust tier** — judged verdicts carry the judge's name and a
  rationale and are reported apart from machine checks, never merged with
  them. With no judge they stay *skipped*, never silently passed.
- **Hash-chained, optionally signed traces**: every trace event is linked by
  `sha256(prev || event)`, so an edited, deleted, or reordered event is
  detectable *standalone* — the auditor recomputes the chain without the
  program. `--sign-trace` (with `IFLOW_TRACE_KEY`) HMAC-seals the root so a
  third party can prove a trace was produced by a key holder.
- **Python embedding** (`intentflow.load(...).run(...)`): load, validate,
  compile, inspect, and run goals/pipelines from Python, and register Python
  functions as governed actions — they still execute through the action gate.
- **Recorded backends** (cassettes): `--record-cassette` captures a real
  model's replies; `--backend replay --cassette` replays them deterministically
  so the real parsing/governance path is testable in CI without API keys.
- **Real governed tools**: with `--workspace`, evidence sources are
  collected by real read-only tools through the gate; a goal that requires
  `logs` but does not allow `read_logs` gets a traced `action_blocked`, not
  the file contents.
- **Trace auditing** (`intentflow audit`): independent conformance checking
  of any run result against the program, including tamper detection
  (hidden verification failures, unapproved gated actions, dangling
  citations, broken trace sequences, **broken hash chains**, and **invalid
  signatures** are all caught — all covered by tests).
- **Developer tooling** (`intentflow format`, `intentflow inspect`): an
  idempotent, comment-preserving formatter and an at-a-glance summary of a
  goal's sections, actions, evidence, output fields, and warnings.
- **CLI**: `parse`, `validate` (`--json`), `lint`, `compile`, `inspect`,
  `format` (`--check` / `--write`), `run` (`--backend simulate|anthropic|openai|replay`,
  `--judge`, `--approve` / `--approve-interactive` / `--approve-webhook`,
  `--sign-trace`, `--cassette` / `--record-cassette`, `--trace-dir`), `audit`.

## Install & use

```bash
pip install -e ".[dev]"          # add llm/openai extras for real backends:
#   pip install -e ".[dev,llm]"     -> Anthropic backend
#   pip install -e ".[dev,openai]"  -> OpenAI-compatible backend

intentflow parse    examples/diagnose.iflow      # print the AST as JSON
intentflow validate examples/diagnose.iflow      # semantic checks (--json too)
intentflow lint     examples/diagnose.iflow      # static policy analysis
intentflow inspect  examples/diagnose.iflow      # goals, actions, evidence, warnings
intentflow format   examples/diagnose.iflow --check   # check canonical formatting
intentflow compile  examples/diagnose.iflow      # print the execution plan

# simulated cognition, real governed evidence collection, saved witness:
intentflow run examples/diagnose.iflow --backend simulate \
    --workspace examples/workspace --trace-dir traces/

# independently verify the run stayed inside the program's envelope:
intentflow audit examples/diagnose.iflow traces/DiagnoseProductionIssue-*.json

# composed goals with a statically checked evidence chain:
intentflow run examples/incident_pipeline.iflow --simulate \
    --pipeline IncidentResponse

# real model cognition behind the same governance:
intentflow run examples/diagnose.iflow --backend anthropic   # ANTHROPIC_API_KEY
OPENAI_MODEL=gpt-4o-mini \
intentflow run examples/diagnose.iflow --backend openai      # OPENAI_API_KEY,
                                                              # OPENAI_BASE_URL

python -m pytest                                  # run the test suite
```

### Use from Python

```python
import intentflow

program = intentflow.load("examples/diagnose.iflow")

# register a Python function as a governed action (runs through the gate):
program.register_tool(
    "lookup_user", serves=("user_record",), handler=lambda src: "enterprise plan"
)

result = program.run(
    backend="simulate",
    workspace="examples/workspace",
    judge="simulate",            # evaluate judged rules (separate trust tier)
    approve={"deploy_change"},   # pre-grant a gated action
    sign_key=b"my-trace-key",    # HMAC-seal the trace
)

report = intentflow.audit_document(program.compile(), result, sign_key=b"my-trace-key")
assert report["conformant"]
```

Five examples ship with the repo: `examples/diagnose.iflow`,
`examples/code_review.iflow`, `examples/research_question.iflow`,
`examples/triage_issue.iflow` (governed open-source issue triage), and
`examples/incident_pipeline.iflow` (two goals composed into a pipeline),
plus `examples/workspace/` with real evidence files for governed
collection.

## Honest status

This is an **experimental prototype**. The default backend mocks cognition
deterministically so the *control structure* of the language is testable
end to end; the Anthropic and OpenAI-compatible backends are real but young
(they share one governance path with the simulator). Calibration is a
placeholder shrinkage map, not a learned one. The grammar is intentionally
minimal. The value today is the shape of the abstraction: a compiled,
inspectable plan, governance enforced outside the model, and runs whose
conformance can be verified by a third party.

## Roadmap

Shipped since the early prototype: blocking approval gates (TTY/webhook),
the LLM-judge runner with a separate trust tier, hash-chained + HMAC-signed
traces, the Python embedding API with governed Python tools, and recorded
(cassette) backends for keyless CI. What's next:

1. **Learned confidence calibration** from scored historical runs, replacing
   the shrinkage placeholder.
2. **Memory/context compiler** that turns `context:` policy into concrete
   retrieval and eviction behavior (`prefer`, `preserve`, `max_tokens`).
3. **Richer machine verification predicates** beyond
   `cites_evidence` / `requires_phrase` / `threshold_check`
   (e.g. `consistent_with(source)`, numeric output bounds).
4. **DAG pipelines** with fan-out/fan-in, building on the linear pipelines
   and static evidence-chain checking that exist today.
5. **Asynchronous/polling approval** (issue a request, resume on callback),
   generalizing today's synchronous webhook approver.
6. **Public-key trace signatures** (Ed25519) so witnesses are verifiable by
   parties who do not share the signing secret, complementing today's HMAC.
7. **Compiler optimizations** for token cost, latency, and risk.

See [`docs/architecture.md`](docs/architecture.md) for the conceptual stack
and design notes.

## Project layout

```
intentflow/
  __init__.py     public API
  iflow_ast.py    syntactic AST + cognitive IR nodes
  parser.py       .iflow -> AST (goals + pipelines)
  compiler.py     AST -> validated execution plan (JSON), pipeline checking
  linter.py       static analysis of policies
  backends.py     pluggable cognition (simulate / Anthropic / OpenAI) + cassettes
  judges.py       LLM-judge runner for 'judged' verification rules
  formatter.py    idempotent, comment-preserving source formatter
  tools.py        governed tools, the ActionGate, and approval channels
  runtime.py      phase-machine runtime with calibration + hash-chained trace
  auditor.py      trace conformance checking (the contract/witness story)
  api.py          Python embedding API (load / run / register_tool)
  cli.py          parse|validate|lint|compile|inspect|format|run|audit
examples/         five demonstration programs + a real evidence workspace
tests/            parser, compiler, runtime, tools, pipeline, lint, audit, CLI,
                  judges, approvals, cassettes, trace chain, embedding API
docs/             architecture notes
```

## License

MIT.
