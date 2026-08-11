# IntentFlow

[![Read the Weaver Stack overview on Towards AI](https://img.shields.io/badge/Read_the_overview-Towards_AI-black?logo=medium&logoColor=white)](https://pub.towardsai.net/the-weaver-stack-one-contract-layer-for-safe-llm-agents-7f733cad5eac)

**An experimental language and reference runtime for explicit agent governance.**

IntentFlow v0 lets you declare a goal, evidence requirements, action-name
policy, verification rules, uncertainty handling, and a typed output contract.
The reference runtime executes those declarations through explicit phases and
can emit a hash-chained trace. The bundled auditor performs **selected offline
consistency and conformance checks under documented assumptions**; it does not
prove an agent's reasoning, external truth, complete mediation, or correct
execution by third-party systems.

v0 is now **legacy/experimental** and frozen except for bounded correctness,
security, reliability, packaging, and honesty fixes. A narrower v1 research
programme is testing whether portable action-assurance artifacts add material
value beyond a strong policy + signed-attestation baseline. See
[`INCUBATION.md`](INCUBATION.md), [`ROADMAP.md`](ROADMAP.md),
[`CLAIMS.md`](CLAIMS.md), and [`docs/limitations.md`](docs/limitations.md).

```text
.iflow source -> parser -> analyzer (IFLOW diagnostics) -> compiler ->
execution plan (JSON) -> runtime (13-phase machine) -> traced result ->
replay / audit
```

![Run a goal, save the witness, hand-edit the trace, and watch `intentflow audit` catch it — offline and deterministic.](docs/assets/demo.svg)

**New here?** [Get started in 5 minutes](docs/quickstart.md) — install to an
audited run, ending by tampering with a trace and watching the bundled auditor
catch one supported inconsistency class.

```bash
pip install intentflow
intentflow run examples/opensource_triage.iflow --simulate --trace-out result.json
intentflow audit examples/opensource_triage.iflow result.json   # CONFORMANT
python -c "import json; d=json.load(open('result.json')); d['result']['citations']=['E99']; json.dump(d, open('result.json','w'))"
intentflow audit examples/opensource_triage.iflow result.json   # NONCONFORMANT (E1: phantom citation)
```

## Install

Install the published package from PyPI. The core has zero runtime dependencies:

```bash
pip install intentflow
```

Install only the user-facing capability you need:

```bash
pip install "intentflow[openai]"  # OpenAI-compatible backend
pip install "intentflow[llm]"     # Anthropic backend
pip install "intentflow[sign]"    # signed traces / verification support
```

Editable installs, tests, docs tooling, and supply-chain audit tooling are
maintainer workflows and live in [CONTRIBUTING.md](CONTRIBUTING.md), not in the
public install path.

Or run it in a container without touching your Python — see
[Run in Docker](#run-in-docker).

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
| Action governance | `actions:` (`allow`/`require_approval`/`deny`) | the `ActionGate`, outside the model for mediated calls |
| Verification | `verify:` (`check`, `require`, free text) | implemented machine checks + judged tier; see #160 |
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
| `intentflow audit <file> <result.json>` | check supported v0 consistency/conformance invariants |

`run` flags: `--backend simulate|mock|openai|anthropic|replay`, `--goal`,
`--pipeline`, `--workspace DIR`, `--approve ACTION`,
`--approve-interactive`, `--approve-webhook URL`, `--judge`,
`--cassette/--record-cassette`, `--sign-trace`, `--trace-dir`,
`--trace-out`, `--json`, `--verbose`.

## Run statuses

Every handled run ends in exactly one reference-runtime status, and the exit code follows it:

| Status | Meaning | Exit |
| --- | --- | --- |
| `completed` | output produced and the current overall verification result passed | 0 |
| `needs_human` | an uncertainty rule escalated (`ask_human`); this is not evidence a human answered | 0 |
| `blocked` | policy stopped the action (`block_action`) | 1 |
| `failed_validation` | analyzer errors; nothing executed | 1 |
| `failed_verification` | an evaluated verification check failed | 1 |
| `backend_error` | backend failed / unusable output | 1 |

**Known v0 verification-completeness gap:** issue #160 tracks that a declared
mandatory check can currently be `skipped`/unevaluable without necessarily
forcing the overall verification result to fail. Until that is fixed, inspect
individual check statuses and do not interpret `verification.passed=true` as
proof that every declared mandatory rule was evaluated.

## Simulation mode (default)

The `simulate` backend is deterministic mock cognition: it honors the
goal's typed output schema, cites the evidence that was actually collected,
reports a fixed raw confidence (0.72, transformed to 0.676 by the current
shrinkage map), and labels everything `[simulated]`. It exists so the *control
structure* — gating, confidence transformation, verification, escalation, and
tracing — is testable end to end with no network. The shrinkage map is not, by
itself, empirical evidence of probabilistic calibration.

The core package is intentionally dependency-free; see
[`docs/architecture.md#zero-runtime-dependency-core`](docs/architecture.md#zero-runtime-dependency-core)
for the policy and test guard.

```bash
intentflow run examples/production_diagnosis.iflow \
    --workspace examples/workspace --trace-dir traces --verbose
# -> needs_human: transformed confidence 0.676 < 0.7, by design
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

Real backends sit behind the same reference-runtime governance path and return
a full `BackendResponse` (raw text, parsed JSON, model, latency, token usage,
finish reason). This does not establish complete mediation outside that path.
The OpenAI-compatible backend honors `OPENAI_BASE_URL` / `OPENAI_MODEL`
(Azure, vLLM, Ollama) and requests structured JSON output.
`--record-cassette` captures real replies; `--backend replay --cassette`
replays them deterministically in CI with no keys.

## Traces, replay, audit

`--trace-dir DIR` (one file per result) and `--trace-out FILE` (one explicit
path) both write the **same** self-contained witness envelope: trace id,
timestamp, source path + hash, plan hash, backend, status, and the run result —
all 13 phases, diagnostics, messages, evidence, the backend response, parsed
output, verification results, uncertainty decisions, action-gate decisions, and
the hash-chained event log (optionally HMAC/Ed25519-signed when configured). A
multi-goal run has no single witness for `--trace-out`, so use `--trace-dir` or
`--goal NAME` to select one.

For long or crash-prone runs, `--trace-stream FILE` appends each event to a
JSONL file as it happens (flushed per event), so some abrupt failures may leave
a chain-checkable prefix. Process, host, or storage failures can still leave an
incomplete or missing artifact; v0 does not guarantee a complete witness for
every possible run.

```bash
intentflow replay traces/TriageGitHubIssue-*.json   # the run as a story
intentflow audit  examples/opensource_triage.iflow traces/TriageGitHubIssue-*.json
```

`audit` recompiles the source and checks the **specific v0 invariants implemented
by the bundled auditor**: selected action/approval consistency, citation and
evidence relationships, status/check consistency, trace-chain integrity,
supported format versions, and configured signatures where applicable.

The auditor is developed in the same project and shares v0 formats/design
assumptions with the runtime. A conformant result therefore means the bundled
checks accepted the artifact under their documented assumptions; it does not
prove complete mediation, external truth, model reasoning correctness, or the
correctness of third-party systems. See [`CLAIMS.md`](CLAIMS.md) and
[`docs/limitations.md`](docs/limitations.md).

The two artifacts — the execution plan and the run result/trace — are an open,
versioned v0 format. Their JSON Schemas live under [`schemas/`](schemas/) and the
versioning policy is documented in [`docs/formats.md`](docs/formats.md).

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
dataclass?* A dataclass can hold the same fields. v0's intended value is that
some governance declarations are compiled into explicit runtime checks and
trace records rather than existing only as prompt prose.

1. **The program declares a governance contract for the reference runtime.**
   `deny close_issue` is enforced by `ActionGate` for calls routed through that
   gate. The model cannot talk that gate into approving a denied action, but v0
   does not prove that every external mutation path is mediated.
2. **The trace is an inspectable record.** Runs that successfully record trace
   output can produce a hash-chained, optionally signed event log in a defined
   v0 format.
3. **The bundled auditor checks selected invariants offline.** It can detect
   supported inconsistencies and tampering classes, but it is not an
   independently developed formal verifier and does not prove external truth.

See [`docs/design_principles.md`](docs/design_principles.md),
[`CLAIMS.md`](CLAIMS.md), and [`docs/limitations.md`](docs/limitations.md).

### Compared to the alternatives

| | What you write | Where governance lives | Audit/assurance surface |
| --- | --- | --- | --- |
| **Python function** | exact instructions | in your code | ordinary code/logging |
| **Prompt template** | interpolated strings | mostly prompt prose | output/log dependent |
| **Agent framework** | functions to wire up | framework + application code | framework-specific |
| **IntentFlow v0 goal** | evidence, actions, checks, uncertainty, typed output | reference compiler/runtime + prompt plan | hash-chained record + bundled consistency checks under documented assumptions |

## Examples

Six programs ship with the repo — see [`docs/examples.md`](docs/examples.md):

* [`opensource_triage.iflow`](examples/opensource_triage.iflow) — flagship; completes.
* [`production_diagnosis.iflow`](examples/production_diagnosis.iflow) — escalates to a human by design.
* [`code_review.iflow`](examples/code_review.iflow) — typed structured review output.
* [`research_synthesis.iflow`](examples/research_synthesis.iflow) — intentionally triggers analyzer warnings.
* [`high_risk_deploy.iflow`](examples/high_risk_deploy.iflow) — intentionally `blocked` by policy.
* [`incident_pipeline.iflow`](examples/incident_pipeline.iflow) — two goals composed with a statically checked evidence chain.

For domain examples with narrated governance choices — change review, support
triage, dependency-upgrade risk, and a security-alert pipeline — see the
[example gallery](examples/gallery). Two of them (`change_review`,
`support_triage`) double as **model-routing / human-escalation policy**
examples: declared policy with a replayable decision path.

The [tamper-evidence demo](docs/tamper-demo.md)
([`examples/tamper_demo.py`](examples/tamper_demo.py)) forges a witness four ways
and shows the bundled auditor catching those supported inconsistency classes.

## Documentation

Full docs (also published as a [site](docs/index.md) via MkDocs):

- [Quickstart](docs/quickstart.md) — 5 minutes, offline.
- [Language reference](docs/language-reference.md) — every section, statement, and diagnostic.
- [Concepts & glossary](docs/concepts.md) — contract, witness, envelope, trust tiers.
- [Embedding](docs/embedding.md) — drive it from Python.
- [Backends](docs/backends.md) — OpenAI / Azure / vLLM / Ollama / Anthropic + cassettes.
- [Threat model](docs/threat-model.md) & [security policy](SECURITY.md).
- [Claims and evidence](CLAIMS.md) · [v0 limitations](docs/limitations.md).
- [Incubation contract](INCUBATION.md) · [v1 baseline experiment](docs/v1-baseline-experiment.md).
- [API stability](docs/api-stability.md) · [CLI conventions](docs/cli-conventions.md).
- [Where IntentFlow fits](docs/ecosystem.md) — alongside orchestration, guardrails, policy engines.

## Honest status & current limitations

v0 is an experimental but working reference language/runtime and is now frozen
except for bounded maintenance. Known limits include: line-oriented grammar, no
compound conditions, a fixed confidence shrinkage map rather than demonstrated
statistical calibration, `object` outputs untyped inside, limited uncertainty
control flow, linear pipelines, and the verification-completeness gap tracked in
#160. The simulator mocks cognition; it never pretends otherwise.

The stronger v1 direction is explicitly **unproven**. Its first job is to beat a
strong policy + exact request/approval/receipt + signed-attestation baseline on
material assurance, or stop/narrow if it cannot. See [`INCUBATION.md`](INCUBATION.md).

## Roadmap

Roadmap ownership lives in [ROADMAP.md](ROADMAP.md).

For the architecture model and design notes, see
[`docs/architecture.md`](docs/architecture.md).

## Project layout

```text
intentflow/
  iflow_ast.py    syntactic AST + typed cognitive IR (JSON-serializable)
  _grammar.py     shared line-based grammar (parser + formatter)
  parser.py       .iflow -> AST (line/column errors, strings, comments)
  analyzer.py     static analyzer: coded diagnostics IFLOW001-022
  actions.py      action registry: side-effect/risk metadata + heuristics
  compiler.py     AST -> versioned execution plan (risk profile, prompt plan)
  backends.py     BackendResponse contract: simulate/mock/openai/anthropic/replay
  judges.py       LLM-judge runner for 'judged' verification rules
  tools.py        governed tools, the ActionGate, approval channels
  runtime.py      13-phase reference runtime and hash-chained trace production
  auditor.py      bundled v0 trace consistency/conformance checks
  explain.py      plain-English rendering of a program
  formatter.py    canonical, idempotent, comment-preserving formatter
  api.py          Python embedding (load / run / register_tool)
  cli.py          parse|validate|lint|compile|inspect|explain|format|run|replay|audit
examples/         six programs + a real evidence workspace; gallery/ + tamper_demo.py
tests/            no network, no API keys
docs/             quickstart, language reference, concepts, architecture, ADRs
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
  note = {An experimental language and reference runtime for explicit agent governance}
}
```

## Run in Docker

```bash
docker build -t intentflow .
docker run --rm intentflow run examples/opensource_triage.iflow --simulate
```

The image bakes in the package and examples; the demo path needs no network or
keys. A [`.devcontainer`](.devcontainer/devcontainer.json) is included for
Codespaces / VS Code.

## Community

- **Questions & "how would I model X?"** → [Discussions](https://github.com/dgenio/intentflow/discussions)
  (see [`docs/community.md`](docs/community.md)).
- **Contributing** → [`CONTRIBUTING.md`](CONTRIBUTING.md) — dev setup, the design
  invariants, and how to pick a [good first issue](https://github.com/dgenio/intentflow/labels/good%20first%20issue).
- **Conduct** → [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).
- **Security** → report privately, see [`SECURITY.md`](SECURITY.md).

## License

[MIT](LICENSE).
