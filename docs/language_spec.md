# IntentFlow Language Specification

**Spec version:** 0.2 (matches `plan_version` in compiled output)
**File extension:** `.iflow`

IntentFlow is a declarative language for *governed cognitive processes*. A
program does not describe computation steps; it declares what a competent,
accountable reasoning process looks like — its goal, the evidence it must
gather, the actions it may take, the checks its conclusions must pass, what
to do when it is unsure, and the typed output it promises. The compiler
turns the declaration into an inspectable execution plan; the runtime
executes it with a full audit trace.

---

## 1. Lexical structure

### 1.1 Lines

The grammar is line-oriented. Every construct occupies exactly one line:
block headers (`goal Name {`), block closers (`}`), section headers
(`evidence:`), and statements. Blank lines are ignored.

### 1.2 Comments

`#` starts a comment that runs to the end of the line. Comments may appear
anywhere — on their own line or trailing a statement:

```text
# a whole-line comment
goal Demo {
  evidence:
    require logs  # a trailing comment
}
```

A `#` inside a double-quoted string is **not** a comment:

```text
meta:
  description "fixes #42"   # this part IS a comment
```

### 1.3 Strings

Double-quoted strings may appear inside statements (most commonly in
`meta:`). `\"` escapes a quote. Strings are line-scoped; they cannot span
lines.

### 1.4 Identifiers

Goal names, pipeline names, action names, evidence sources, signals, and
output field names are identifiers: `[A-Za-z_][A-Za-z0-9_]*`. Goal and
pipeline names are conventionally `PascalCase`; everything else is
conventionally `snake_case`.

### 1.5 Numbers

Thresholds are decimal literals (`0.65`, `1`, `.5`). Confidence thresholds
must lie in `[0, 1]`; values outside that range are an analyzer error
(IFLOW019).

---

## 2. Program structure

A program is one or more `goal` blocks, optionally followed by `pipeline`
blocks:

```text
goal Name {
  <sections>
}

pipeline Name {
  stage GoalA
  stage GoalB
}
```

* The opening brace must be on the `goal`/`pipeline` line; the closing `}`
  must stand alone.
* Duplicate **pipeline** names are a parse error. Duplicate **goal** names
  parse (so tooling can still inspect the file) and are reported by the
  analyzer as an error (IFLOW016).
* A file with no goals is a parse error.

## 3. Sections

A goal contains named sections, each opened by `name:` on its own line.
Unknown section names and duplicate sections are parse errors. All sections
are optional in the grammar, but the analyzer enforces minimums (a goal
without an `objective:` is an error; missing `evidence:`/`verify:`/
`uncertainty:`/`output:` are warnings).

Canonical order (the formatter normalizes to this):

| # | Section | Purpose |
|---|---|---|
| 1 | `meta:` | optional metadata (description, owner, version, tags) |
| 2 | `objective:` | what the goal is trying to achieve |
| 3 | `context:` | context/memory policy |
| 4 | `evidence:` | evidence requirements and stances |
| 5 | `model:` | free-text reasoning discipline directives |
| 6 | `actions:` | action governance (allow / deny / require_approval) |
| 7 | `verify:` | verification rules the result must pass |
| 8 | `uncertainty:` | what to do when unsure |
| 9 | `output:` | the typed output contract |

### 3.1 `meta:` — optional metadata

```text
meta:
  description "governed open-source issue triage"
  owner "maintainers"
  version "1.2"
  tags triage, github
```

Valid keys: `description`, `owner`, `version`, `tags` (comma-separated).
Unknown keys are an error (IFLOW020).

### 3.2 `objective:`

Free text; multiple lines are joined into one sentence. Required (IFLOW001).

```text
objective:
  triage a GitHub issue safely and propose a maintainer-ready response
```

### 3.3 `context:`

```text
context:
  max_tokens 10000
  prefer recent_comments
  preserve maintainer_intent
```

* `max_tokens N` — context budget. Values below 256 or above 200000 draw an
  analyzer warning (IFLOW015).
* `prefer X` — prioritize `X` when the context is under pressure.
* `preserve X` — `X` must never be evicted.

Anything else is an error (IFLOW020).

### 3.4 `evidence:`

```text
evidence:
  require issue_body
  require comments
  optional related_issues
  prefer primary_sources
  distrust unsupported_claims
```

Stances:

* `require X` — must be collected before reasoning; if it cannot be
  collected (the gate blocks the tool, or the tool fails), the
  `missing_evidence` signal is raised.
* `optional X` — used when available; its absence raises nothing.
* `prefer X` — a soft preference, surfaced in the prompt plan.
* `distrust X` — may be read but must never be the sole support for a
  claim.

A goal with no `require` lines gets IFLOW014 (warning); exactly one gets
IFLOW009 (warning). In pipelines, `require GoalName.field` consumes an
earlier stage's output (statically checked).

### 3.5 `model:`

Free-text reasoning directives, embedded verbatim in the prompt plan's
system block:

```text
model:
  separate observation from inference
  propose hypotheses with confidence
```

### 3.6 `actions:`

```text
actions:
  allow read_issue
  allow search_repo
  require_approval post_comment
  deny close_issue
```

* `allow X` — the runtime may invoke `X`.
* `require_approval X` — `X` blocks until a human approval channel grants
  it; fail-closed.
* `deny X` — `X` can never run; the gate raises and traces the attempt.

The same action with two different modes is an error (IFLOW006). Allowing a
side-effecting action without approval is a warning (IFLOW010); allowing an
overly broad action (`execute_code`, `run_command`, `shell`, `eval`,
`sudo`) is a warning (IFLOW011). Action risk metadata comes from the
action registry (`intentflow/actions.py`), with name heuristics for
unregistered actions.

### 3.7 `verify:`

```text
verify:
  require cites_evidence
  require maintainer_safe_tone
  check confidence >= 0.65
  proposed fix must include rollback path
```

Three statement forms:

* `check <metric> <op> <number>` — a **machine** threshold check. `<op>` is
  one of `< <= > >= ==`. `confidence` always refers to the calibrated run
  confidence; any other metric must name a numeric output field (else
  IFLOW007).
* `require <name>` — a named requirement. `require cites_evidence` is
  **machine**-checked (the result must cite collected evidence ids). Any
  other name is **judged**: evaluated by an LLM judge when one is
  configured (`--judge`), otherwise recorded as *skipped* — never silently
  passed (IFLOW021, info).
* Free text — classified by the compiler: text containing a citation verb
  becomes `cites_evidence`; text containing "rollback" becomes a machine
  `requires_phrase` check; everything else is judged.

The runtime always prepends an implicit machine check `V0`: *the output
conforms to the declared schema*. A failed machine check makes the run end
in `failed_verification`; it can never be reported as success.

### 3.8 `uncertainty:`

```text
uncertainty:
  if confidence < 0.65 ask_human
  if missing_evidence ask_human
  if security_risk block_action
```

Two condition forms:

* `if <metric> <op> <number> <action>` — threshold on the calibrated
  confidence (or a numeric output field).
* `if <signal> <action>` — a symbolic signal. Known signals:
  * `missing_evidence` — a required evidence source could not be collected;
  * `security_risk` — the compiled risk profile is `high`, or the backend
    flagged `"security_risk": true`;
  * `competing_hypotheses` — the backend reported non-empty
    `"alternatives"`.

  Unknown signals are recorded in the trace but never evaluated (IFLOW008).

Actions are either built-in escalation primitives or a declared
allowed/approval-gated action (anything else: IFLOW018). Primitives:

| Action | Runtime effect |
|---|---|
| `ask_human` | record an escalation; the run ends `needs_human` |
| `block_action` | record a block; the run ends `blocked` |
| `escalate`, `abort`, `halt`, `defer`, `retry`, `run_discriminating_test`, `present_both_views`, `request_more_evidence`, `gather_more_evidence` | recorded in the trace (no executor yet) |

### 3.9 `output:` — typed output fields

```text
output:
  summary: string
  likely_cause: string?
  confidence: number
  suggested_response: markdown
  proposed_labels: list[string]
```

Each statement is `name: type`. Supported types:

```
string    string?
number    number?
boolean   boolean?
markdown  markdown?
list[string]
list[number]
object    object?
```

`?` marks the field optional: it may be `null` or omitted (the runtime
fills it with `null`). `markdown` is a string whose content is expected to
be Markdown. Any other type text is an error (IFLOW005); duplicate field
names are an error (IFLOW004).

A bare `name` (no type) is legacy syntax that defaults to `string` and
draws IFLOW017 (info).

If `confidence` is used in `verify:`/`uncertainty:` but not declared as an
output field, the analyzer warns (IFLOW003). When declared, the runtime
writes the **calibrated** confidence into it.

## 4. Pipelines

```text
pipeline IncidentResponse {
  stage DiagnoseIncident
  stage ProposeRemediation
}
```

Stages run in order. A later stage may `require GoalName.field`; the
compiler statically verifies the field is produced by an earlier stage.
Execution stops at the first stage that does not end `completed`, and the
pipeline takes that stage's status.

## 5. Compilation

`intentflow compile` produces a JSON document:

```json
{
  "intentflow_version": "0.5.0",
  "plan_version": "0.2",
  "source": "examples/opensource_triage.iflow",
  "source_hash": "<sha256 of the source text>",
  "goals": [ { ...one plan per goal... } ],
  "pipelines": [ {"name": "...", "stages": ["..."]} ]
}
```

Each goal plan contains: `objective`, `metadata`, `context_policy`,
`evidence_policy`, `action_policy`, `model_directives`,
`verification_policy`, `uncertainty_policy`, `calibration`,
`output_schema`, `risk_profile`, `trace_policy`, `prompt_plan` (one
inspectable block per governance concern), and `execution_phases`.

The **risk profile** is computed from the policies: a `level`
(`low`/`medium`/`high`), `side_effect_actions`, `blocked_actions`,
`approval_required`, and `missing_safety_controls`. Allowing a side-effect
or overly broad action without approval makes the level `high`.

## 6. Execution

Every run moves through 13 canonical phases:

```
parse -> analyze -> compile -> prepare_context -> collect_evidence ->
build_messages -> call_backend -> parse_output -> verify_output ->
apply_uncertainty_policy -> enforce_action_policy -> finalize -> trace
```

and ends in exactly one status:

| Status | Meaning |
|---|---|
| `completed` | output produced, verification passed |
| `needs_human` | an uncertainty rule escalated (`ask_human`) |
| `blocked` | policy blocked the run (`block_action`) |
| `failed_validation` | analyzer errors; nothing executed |
| `failed_verification` | a machine verification check failed |
| `backend_error` | the backend failed or returned unusable output |

Status precedence when several apply: `backend_error` > `blocked` >
`needs_human` > `failed_verification` > `completed`.

Raw model confidence is **calibrated** (currently shrinkage toward 0.5,
factor 0.8) before any threshold fires. Citations to evidence ids that were
never collected are dropped (and traced).

## 7. Invalid examples

```text
goal Bad1 {            # IFLOW001: no objective
  output:
    a: string
}

goal Bad2 {
  objective:
    x
  output:
    a: blob            # IFLOW005: invalid output type
}

goal Bad3 {
  objective:
    x
  actions:
    allow deploy_change
    deny deploy_change # IFLOW006: conflicting policies
}

goal Bad4 {
  objective:
    x
  uncertainty:
    if confidence < 1.5 ask_human   # IFLOW019: threshold out of [0, 1]
}
```

See `intentflow/analyzer.py` for the full diagnostic table (IFLOW001–022).

## 8. Current limitations

* The grammar is line-oriented; statements cannot span lines.
* Conditions cannot be combined (`if A and B` is not supported).
* Uncertainty primitives other than `ask_human`/`block_action` are recorded
  but have no executor.
* `list[...]` supports only `string` and `number` items; no nested types,
  no typed `object` schemas.
* Calibration is a fixed shrinkage map, not learned.
* The runtime does not yet execute external side-effecting tools; it
  *governs* them (gate, approvals, trace) and collects read-only evidence
  through them.
* Pipelines are linear; no fan-out/fan-in.
