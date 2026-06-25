# IntentFlow

**A language for governed cognitive processes.**

[![Read the Weaver Stack overview on Towards AI](https://img.shields.io/badge/Read_the_overview-Towards_AI-black?logo=medium&logoColor=white)](https://pub.towardsai.net/the-weaver-stack-one-contract-layer-for-safe-llm-agents-7f733cad5eac)

> Python programs deterministic computation.
> IntentFlow programs governed cognition.

IntentFlow is not a chatbot wrapper and not a prompt template. It is a
small language that compiles cognitive intent — a goal, its evidence
requirements, its action policy, its verification rules, its uncertainty
handling, and its typed output contract — into an **auditable, governed,
executable agent plan**. The runtime executes that plan through explicit
phases and emits a hash-chained trace that a third party can independently
verify.

```text
.iflow source -> parser -> analyzer (IFLOW diagnostics) -> compiler ->
execution plan (JSON) -> runtime (13-phase machine) -> traced result ->
replay / audit
```

## Install

```bash
pip install -e .            # core: zero runtime dependencies
pip install -e ".[dev]"     # + pytest
pip install -e ".[openai]"  # + OpenAI-compatible backend
pip install -e ".[llm]"     # + Anthropic backend
```

## Quickstart

```bash
intentflow validate examples/opensource_triage.iflow
intentflow inspect  examples/opensource_triage.iflow
intentflow explain  examples/opensource_triage.iflow
intentflow compile  examples/opensource_triage.iflow --out plan.json
intentflow run      examples/opensource_triage.iflow --backend simulate --trace-dir traces
intentflow replay   traces/TriageGitHubIssue-*.json
intentflow audit    examples/opensource_triage.iflow traces/TriageGitHubIssue-*.json
```

Every command above works offline, deterministically, with no API key.

## First example

```text
goal TriageGitHubIssue {
  objective:
    triage a GitHub issue safely and propose a maintainer-ready response

  context:
    max_tokens 10000
    prefer recent_comments
    preserve maintainer_intent

  evidence:
    require issue_body
    require comments
    require repo_context
    optional related_issues
    distrust unsupported_claims

  actions:
    allow read_issue
    allow search_repo
    allow draft_comment
    require_approval post_comment
    deny close_issue

  verify:
    require cites_evidence
    require maintainer_safe_tone
    require no_unverified_claims
    check confidence >= 0.65

  uncertainty:
    if confidence < 0.65 ask_human
    if missing_evidence ask_human
    if security_risk block_action

  output:
    summary: string
    likely_cause: string?
    confidence: number
    suggested_response: markdown
    proposed_labels: list[string]
}
```

Reading this file tells you — and `intentflow explain` will say it in plain
English — what the goal is, what evidence is mandatory, what the agent may
do, what is forbidden, what needs a human, how the result is checked, and
exactly what typed output it promises.

## Language concepts

| Concern | Section | Enforced by |
| --- | --- | --- |
| Goal | `objective:` | analyzer (required) |
| Context policy | `context:` | runtime (prompt plan), analyzer bounds |
| Evidence | `evidence:` (`require`/`optional`/`prefer`/`distrust`) | action gate + `missing_evidence` signal |
| Reasoning discipline | `model:` | prompt plan |
| Action governance | `actions:` (`allow`/`require_approval`/`deny`) | the `ActionGate`, outside the model |
| Verification | `verify:` (`check`, `require`, free text) | machine checks + judged tier |
| Uncertainty | `uncertainty:` (`if <cond> <action>`) | run status control flow |
| Output contract | `output:` (typed fields) | implicit `V0` schema check |

Typed output fields are part of the language: `string`, `number`,
`boolean`, `markdown` (each with optional `?`), `list[string]`,
`list[number]`, `object`, `object?`. The full grammar, diagnostics table,
and invalid examples live in [`docs/language_spec.md`](docs/language_spec.md).

## CLI

| Command | Purpose |
| --- | --- |
| `intentflow parse <file>` | print the AST as JSON |
| `intentflow validate <file> [--json]` | static analyzer: coded diagnostics (IFLOW001–022) |
| `intentflow lint <file> [--strict]` | advisory tier only (warnings/info) |
| `intentflow compile <file> [--out plan.json]` | emit the versioned execution plan |
| `intentflow inspect <file> [--json]` | at-a-glance summary of a goal |
| `intentflow explain <file> [--json]` | translate the program into plain English |
| `intentflow format <file> [--check\|--write]` | idempotent canonical formatter |
| `intentflow run <file> [...]` | execute through the 13-phase runtime |
| `intentflow replay <trace.json> [--json]` | readable summary of a saved trace |
| `intentflow audit <file> <result.json>` | independently verify a run against the plan |

`run` flags: `--backend simulate|mock|openai|anthropic|replay`, `--goal`,
`--pipeline`, `--workspace DIR`, `--approve ACTION`,
`--approve-interactive`, `--approve-webhook URL`, `--judge`,
`--cassette/--record-cassette`, `--sign-trace`, `--trace-dir`,
`--trace-out`, `--json`, `--verbose`.

## Run statuses

Every run ends in exactly one status, and the exit code follows it:

| Status | Meaning | Exit |
| --- | --- | --- |
| `completed` | output produced, verification passed | 0 |
| `needs_human` | an uncertainty rule escalated (`ask_human`) | 0 |
| `blocked` | policy stopped the run (`block_action`) | 1 |
| `failed_validation` | analyzer errors; nothing executed | 1 |
| `failed_verification` | a machine check failed | 1 |
| `backend_error` | backend failed / unusable output | 1 |

The runtime can never report a failed verification as success — the auditor
checks for exactly that cover-up (violation `S1`/`V1`).

## Simulation mode (default)

The `simulate` backend is deterministic mock cognition: it honors the
goal's typed output schema, cites the evidence that was actually collected,
reports a fixed raw confidence (0.72, calibrated to 0.676), and labels
everything `[simulated]`. It exists so the *control structure* — gating,
calibration, verification, escalation, tracing — is testable end to end
with no network.

The core package is intentionally dependency-free; see
[`docs/architecture.md#zero-runtime-dependency-core`](docs/architecture.md#zero-runtime-dependency-core)
for the policy and test guard.

```bash
intentflow run examples/production_diagnosis.iflow \
    --workspace examples/workspace --trace-dir traces --verbose
# -> needs_human: calibrated confidence 0.676 < 0.7, by design
```

With `--workspace`, evidence is collected by real read-only tools *through
the action gate*: a goal that requires `logs` but does not allow
`read_logs` gets a traced `action_blocked` and a `missing_evidence` signal
— not the file contents.

## Real backend mode

```bash
OPENAI_API_KEY=... intentflow run examples/opensource_triage.iflow --backend openai
ANTHROPIC_API_KEY=... intentflow run examples/opensource_triage.iflow --backend anthropic
```

Real backends sit behind the identical governance path and return a full
`BackendResponse` (raw text, parsed JSON, model, latency, token usage,
finish reason). The OpenAI-compatible backend honors `OPENAI_BASE_URL` /
`OPENAI_MODEL` (Azure, vLLM, Ollama) and requests structured JSON output.
`--record-cassette` captures real replies; `--backend replay --cassette`
replays them deterministically in CI with no keys.

## Traces, replay, audit

`--trace-dir` writes a self-contained artifact per run: trace id,
timestamp, source path + hash, plan hash, backend, status, all 13 phases,
diagnostics, messages, evidence, the backend response, parsed output,
verification results, uncertainty decisions, action-gate decisions, and the
hash-chained event log (optionally HMAC-signed with `--sign-trace`).

```bash
intentflow replay traces/TriageGitHubIssue-*.json   # the run as a story
intentflow audit  examples/opensource_triage.iflow traces/TriageGitHubIssue-*.json
```

`audit` recompiles the source and proves — without trusting the runtime,
the backend, or the model — that no denied action ran, every gated action
had a prior approval, every citation points at collected evidence, no
verification failure was hidden, the status is consistent with the trace,
and the trace chain is intact.

## Use from Python

```python
import intentflow

program = intentflow.load("examples/opensource_triage.iflow")
result = program.run(backend="simulate")
assert result["status"] == "completed"

# register a Python function as a governed action (runs through the gate):
program.register_tool("lookup_user", serves=("user_record",),
                      handler=lambda src: "enterprise plan")

report = intentflow.audit_document(program.compile(), result)
assert report["conformant"]
```

Six examples ship with the repo: `examples/code_review.iflow`,
`examples/high_risk_deploy.iflow`, `examples/incident_pipeline.iflow`,
`examples/opensource_triage.iflow`, `examples/production_diagnosis.iflow`,
and `examples/research_synthesis.iflow`, plus `examples/workspace/` with
real evidence files for governed collection. The test suite runs every
example against that workspace so required evidence sources stay backed by
files instead of simulated placeholders.

## Design philosophy

The honest objection to any "agent DSL" is: *couldn't this be a Python
dataclass?* A dataclass can hold the same fields; it cannot give them
semantics that survive the model boundary. IntentFlow's answer:

1. **The program is a contract.** `deny close_issue` is enforced by the
   `ActionGate` outside the model. The gate never reads model output, so
   the model cannot talk its way past it.
2. **The trace is a witness.** Every run emits a hash-chained, optionally
   signed event log in a defined format.
3. **Conformance is independently verifiable.** `intentflow audit` proves a
   run stayed inside its envelope using only the source and the trace.

See [`docs/design_principles.md`](docs/design_principles.md).

### Compared to the alternatives

| | What you write | Where governance lives | Auditable? |
| --- | --- | --- | --- |
| **Python function** | exact instructions | in your code | yes, but it isn't cognition |
| **Prompt template** | interpolated strings | prose the model may ignore | output only |
| **Agent framework** | functions to wire up | your head + your prompts | ad-hoc logging |
| **IntentFlow goal** | evidence, actions, checks, uncertainty, typed output | compiled program text, enforced outside the model | every run emits a replayable witness |

## Examples

Five programs ship with the repo — see [`docs/examples.md`](docs/examples.md):

* [`opensource_triage.iflow`](examples/opensource_triage.iflow) — flagship; completes.
* [`production_diagnosis.iflow`](examples/production_diagnosis.iflow) — escalates to a human by design.
* [`code_review.iflow`](examples/code_review.iflow) — typed structured review output.
* [`research_synthesis.iflow`](examples/research_synthesis.iflow) — intentionally triggers analyzer warnings.
* [`high_risk_deploy.iflow`](examples/high_risk_deploy.iflow) — intentionally `blocked` by policy.
* [`incident_pipeline.iflow`](examples/incident_pipeline.iflow) — two goals composed with a statically checked evidence chain.

## Honest status & current limitations

This is an experimental but working language. Known limits (also in the
spec): line-oriented grammar, no compound conditions, calibration is a
fixed shrinkage map, `object` outputs are untyped inside, uncertainty
primitives beyond `ask_human`/`block_action` are recorded but not executed,
side-effecting tools are governed but not yet executed, and pipelines are
linear. The simulator mocks cognition; it never pretends otherwise.

## Roadmap

Roadmap ownership now lives in [ROADMAP.md](ROADMAP.md).

For the architecture model and design notes, see
[`docs/architecture.md`](docs/architecture.md).

## Project layout

```text
intentflow/
  iflow_ast.py    syntactic AST + typed cognitive IR (JSON-serializable)
  parser.py       .iflow -> AST (line/column errors, strings, comments)
  analyzer.py     static analyzer: coded diagnostics IFLOW001-022
  actions.py      action registry: side-effect/risk metadata + heuristics
  compiler.py     AST -> versioned execution plan (risk profile, prompt plan)
  backends.py     BackendResponse contract: simulate/mock/openai/anthropic/replay
  judges.py       LLM-judge runner for 'judged' verification rules
  tools.py        governed tools, the ActionGate, approval channels
  runtime.py      13-phase machine, 6 statuses, hash-chained trace
  auditor.py      independent trace conformance checking
  explain.py      plain-English rendering of a program
  formatter.py    canonical, idempotent, comment-preserving formatter
  api.py          Python embedding (load / run / register_tool)
  cli.py          parse|validate|lint|compile|inspect|explain|format|run|replay|audit
examples/         six programs + a real evidence workspace
tests/            ~230 tests; no network, no API keys
docs/             language spec, design principles, examples, roadmap
```

## Citing IntentFlow

IntentFlow includes [`CITATION.cff`](CITATION.cff) so GitHub can render
repository citation metadata. For papers and reports, cite the repository
version you used. For example:

```bibtex
@software{intentflow,
  title = {IntentFlow},
  author = {{IntentFlow contributors}},
  version = {0.6.0},
  url = {https://github.com/dgenio/intentflow},
  note = {An experimental language for governed cognitive processes}
}
```

## License

MIT.
