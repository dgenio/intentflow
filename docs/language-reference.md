# IntentFlow language reference

The normative reference for `.iflow` as **implemented** — every block, section,
statement form, special vocabulary, diagnostic, and lint rule the toolchain
accepts today. For the narrative spec and design rationale see
[`language_spec.md`](language_spec.md); for a hands-on path see
[`quickstart.md`](quickstart.md). Sources of truth: `intentflow/parser.py`
(syntax), `intentflow/iflow_ast.py` (node shapes), `intentflow/compiler.py`
(lowering + validation), `intentflow/analyzer.py` and `intentflow/linter.py`
(diagnostics).

## File conventions

- Extension: `.iflow`. Encoding: UTF-8.
- One statement per line; the grammar is line-based.
- `#` starts a comment to end of line, except inside a double-quoted string.
- Indentation is not significant to the parser (the formatter normalizes it to
  2 spaces per level); block structure comes from `{ … }` and `section:` headers.

## Grammar summary (EBNF-style)

```
program      = { goal | pipeline } ;
goal         = "goal" identifier "{" { section } "}" ;
pipeline     = "pipeline" identifier "{" { "stage" identifier } "}" ;
section      = section-name ":" { statement } ;
section-name = "meta" | "objective" | "context" | "evidence"
             | "model" | "actions" | "verify" | "uncertainty" | "output" ;
identifier   = letter | "_" , { letter | digit | "_" } ;
statement    = <one non-empty line, form depends on the section> ;
```

Block headers match, exactly: `^goal <name> {$`, `^pipeline <name> {$`,
`^stage <name>$`, `^<section>:$` (see `intentflow/_grammar.py`).

## Blocks

### `goal Name { … }`

The unit of governed cognition. Contains sections (below), each at most once;
a duplicate section is a syntax error (`IFLOW005`). Section order in source is
free — the formatter reorders to the canonical order (meta, objective, context,
evidence, model, actions, verify, uncertainty, output).

### `pipeline Name { … }`

An ordered composition of goals. Each line is `stage GoalName`; stages run in
order, later stages seeing earlier stages' outputs as evidence.

```iflow
pipeline Incident {
  stage DiagnoseProductionIssue
  stage ProposeRemediation
}
```

## Sections

### `meta:` (optional)
Free-form metadata. The recognized statement is `description "<text>"`.

```iflow
meta:
  description "root-cause analysis for a failing job"
```

### `objective:`
One or more free-text lines stating the goal's purpose. Compiled into the
system/objective prompt blocks.

```iflow
objective:
  identify the most likely root cause of a failing production job
```

### `context:`
Tuning hints. Recognized statements: `max_tokens <n>`, `prefer <source>`,
`preserve <source>`. Out-of-range `max_tokens` warns (`IFLOW015`).

```iflow
context:
  max_tokens 12000
  prefer recent_logs
  preserve user_decisions
```

### `evidence:`
Declares what the run must gather before reasoning. Statement forms — one per
**stance**:

| Stance | Form | Meaning |
|--------|------|---------|
| require | `require <source>` | must be collected; a blocked/missing required source raises the `missing_evidence` signal |
| optional | `optional <source>` | collected if available; absence is not an error |
| distrust | `distrust <source>` | may inform but must not be the *sole* support for a conclusion |

```iflow
evidence:
  require logs
  require config
  optional related_issues
  distrust speculation_without_sources
```

A goal with no `require`d evidence warns `IFLOW014`; exactly one warns
`IFLOW009` (single basis).

### `model:`
Free-text modeling instructions (e.g. `propose hypotheses with confidence`,
`separate observation from inference`). Compiled into the prompt; no special
keywords.

### `actions:`
The behavior envelope. Statement forms — one per **mode**:

| Mode | Form | Meaning |
|------|------|---------|
| allow | `allow <action>` | the action may run through the gate |
| deny | `deny <action>` | the action is forbidden; a requested denied action is blocked |
| require_approval | `require_approval <action>` | allowed only with a matching approval grant |

```iflow
actions:
  allow read_logs
  allow inspect_code
  require_approval deploy_change
  deny delete_database
```

Broad/destructive-looking actions (e.g. `execute_code`) warn `IFLOW011`.

### `verify:`
Rules the output must satisfy. Two tiers:

- **Machine-checkable** (evaluated deterministically by the runtime):
  - `require cites_evidence` — every citation points at collected evidence.
  - `check <metric> <op> <number>` — e.g. `check confidence >= 0.7`; `<op>` is
    one of `< <= > >= ==`. `<metric>` is `confidence` or a declared numeric
    output field (otherwise `IFLOW007`).
  - `<subject> must include <phrase>` (a `requires_phrase` predicate) — e.g.
    `proposed fix must include rollback path`.
- **Judged** (delegated to an LLM judge tier when `--judge` is set): any other
  `require <free text>` rule. Flagged `IFLOW021` (info: judged, not
  machine-checkable).

```iflow
verify:
  require cites_evidence
  check confidence >= 0.7
  proposed fix must include rollback path
```

A goal with no verify rules warns `IFLOW012`.

### `uncertainty:`
Control flow for doubt. Form: `if <condition> <action>`.

- Conditions: `confidence < <n>` (threshold) or a symbolic signal —
  `missing_evidence`, `security_risk`, `competing_hypotheses`.
- Actions: `ask_human` (escalate), `run_discriminating_test`, `block_action`,
  or an allowed/approval-gated action name.

```iflow
uncertainty:
  if confidence < 0.7 ask_human
  if missing_evidence ask_human
  if competing_hypotheses run_discriminating_test
```

A goal with no uncertainty rules warns `IFLOW013`.

### `output:`
The typed output contract. Form: `<field>: <type>` (a bare `<field>` defaults
to `string` and emits `IFLOW017` info). Types: `string`, `number`, `boolean`,
`markdown`, `list[string]`, `list[number]`, `object`; a trailing `?` marks the
field optional.

```iflow
output:
  root_cause: string
  confidence: number
  recommended_fix: markdown
  risk: string?
```

## Special vocabularies (quick index)

- **Evidence stances**: `require`, `optional`, `distrust`.
- **Action modes**: `allow`, `deny`, `require_approval`.
- **Uncertainty conditions**: `confidence < n`, `missing_evidence`,
  `security_risk`, `competing_hypotheses`.
- **Uncertainty actions**: `ask_human`, `run_discriminating_test`,
  `block_action`, or a governed action name.
- **Machine verification predicates**: `cites_evidence`, `check <metric> <op>
  <n>`, `<subject> must include <phrase>`. Everything else in `verify:` is a
  judged rule.

## Diagnostics

`intentflow validate` reports errors and warnings; `intentflow lint` reports
the advisory tier (warnings + info). Codes as implemented in
`intentflow/analyzer.py`:

| Code | Severity | Fires when |
|------|----------|-----------|
| IFLOW001 | error | a goal has no `objective:` |
| IFLOW002 | warning | goal declares no output schema |
| IFLOW003 | warning | goal gates on `confidence` but declares no confidence-producing output |
| IFLOW004 | error | duplicate output field |
| IFLOW005 | error | output section fails to lower (malformed output) |
| IFLOW006 | error | conflicting policies for one action (e.g. allow + deny) |
| IFLOW007 | warning | `check` references a metric that is neither `confidence` nor a declared output field |
| IFLOW008 | warning | uncertainty condition references an unknown signal |
| IFLOW009 | warning | exactly one required evidence source (single basis) |
| IFLOW010 | warning | an action with side effects is allowed without approval |
| IFLOW011 | warning | an overly broad / destructive-looking action is allowed |
| IFLOW012 | warning | no verification rules (ungrounded trust in inputs) |
| IFLOW013 | warning | no uncertainty rules |
| IFLOW014 | warning | no required evidence |
| IFLOW015 | warning | `max_tokens` implausibly low or high |
| IFLOW016 | error | duplicate goal name in the program |
| IFLOW017 | info | untyped output field (defaults to `string`) |
| IFLOW018 | warning | uncertainty action is neither a built-in primitive nor a governed action |
| IFLOW019 | error | confidence threshold out of range `[0, 1]` |
| IFLOW020 | error | a lowering/compile error surfaced as a diagnostic |
| IFLOW021 | info | verification rule is judged, not machine-checkable |
| IFLOW022 | warning | uncertainty rule is redundant or can never/always trigger |

(Severities are authoritative in `intentflow/analyzer.py` and checked by
`tests/test_analyzer.py`. If you find a discrepancy between this table and the
code, please open an issue rather than editing around it.)

## Related

- [`concepts.md`](concepts.md) — the vocabulary (contract, witness, envelope,
  trust tiers) these constructs implement.
- [`architecture.md`](architecture.md) — how source becomes plan becomes
  witness.
- [`formats.md`](formats.md) — the compiled plan and result/witness shapes.
