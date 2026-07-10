# Public API and stability guarantees

IntentFlow is pre-1.0 (`Development Status :: 2 - Pre-Alpha`). This document
draws the line between the **supported public API** — what you can build on and
expect us to keep working — and **internal implementation detail** that may
change without notice. It exists so adopters can rely on a surface and
maintainers can refactor internals without fear.

## What "stable" means here

- **Public API**: the names listed below, imported from the top-level
  `intentflow` package. Within a `0.x` line we avoid breaking these; when we
  must, the change is called out in `CHANGELOG.md` and, where feasible, a
  deprecated alias is kept for one release.
- **Internal**: everything else — submodule paths (`intentflow.runtime`,
  `intentflow.backends`, …), any name starting with an underscore, and any
  module named with a leading underscore (e.g. `intentflow._grammar`). These
  can change shape, move, or disappear between any two releases. Import them at
  your own risk.

Until 1.0, even the public surface may change between minor versions, but only
deliberately and with a changelog note — never silently.

## Supported public API

Import these from `intentflow` (not from submodules):

### Load, compile, run
- `load`, `load_source` — load a program from a file or string
- `IntentFlowProgram` — the embedding handle (validate / compile / inspect /
  explain / run)
- `execute_program`, `run_pipeline` — run a parsed program or pipeline
- `compile_program`, `compile_goal`, `ExecutionPlan` — produce an execution plan

### Analyze and audit
- `analyze_program`, `analyze_goal`, `Diagnostic` — static analysis (the
  `IFLOW###` diagnostics)
- `audit_document`, `audit_result` — verify a witness against a plan

### Governance extension points
- `ToolRegistry`, `Tool` — register governed Python actions
- `Approver` — implement a custom approval channel
- `Judge` — implement a custom judged-verification tier

### Errors
- `ParseError`, `CompileError`, `BackendError`, `ActionDenied`

### Version
- `__version__`

The full `__all__` in `intentflow/__init__.py` re-exports more names than this
for convenience (concrete backends, approver implementations, trace primitives,
etc.). Those convenience exports are usable, but only the names above carry the
stability promise; the rest track their defining module and may move.

## Internal boundaries we do not cross

Two guarantees keep the internals honest:

- **No cross-module private imports.** Modules do not import another module's
  underscore-prefixed names. The lexical grammar shared by the parser and the
  formatter lives in a dedicated internal module, `intentflow._grammar`, rather
  than the formatter reaching into `intentflow.parser`'s private regexes.
- **Zero-runtime-dependency core.** `pip install intentflow` pulls in no
  third-party packages; provider SDKs, signing, and schema validation are
  optional extras. This is enforced by `tests/test_dependency_policy.py`.

## Deprecated aliases

These names remain importable for one release and are scheduled for removal
(tracked in [#107](https://github.com/dgenio/intentflow/issues/107)):

- `SimulationRuntime` → use `GoalRuntime` / `execute_program`
- `SimulatorBackend` → use `SimulatedCognition` (or `make_backend("simulate")`)
- `OpenAICompatibleBackend` → use `OpenAICompatibleCognition`

Prefer the replacements in new code.
