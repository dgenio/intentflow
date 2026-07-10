# Backend configuration guide

How to configure each cognition backend and judge: extras, environment
variables, and copy-paste recipes. The default backend is the deterministic
**simulate** backend, which needs no configuration and no network — everything
in the [quickstart](quickstart.md) uses it.

## Backend matrix

| Backend (`--backend`) | Install extra | Key env vars | Notes |
|-----------------------|---------------|--------------|-------|
| `simulate` (default)  | none          | — | deterministic; the conformance reference |
| `openai`              | `intentflow[openai]` | `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL` | any OpenAI-compatible endpoint |
| `anthropic`           | `intentflow[llm]` | `ANTHROPIC_API_KEY` | Anthropic Claude |
| `replay`              | none          | — | replays a `--cassette`; no key |

Judges (`--judge`) reuse the same providers: `simulate`, `openai`, `anthropic`,
`replay`. A judge is a separate trust tier for `verify:` rules that are not
machine-checkable.

## Environment variables

Every environment variable the codebase reads (enumerate with
`grep -rn "os.environ" intentflow/`):

**Providers (provider-native names):**
- `OPENAI_API_KEY` — key for the `openai` backend/judge.
- `OPENAI_BASE_URL` — point the OpenAI client at another endpoint (Azure, vLLM,
  Ollama, …).
- `OPENAI_MODEL` — model name for the `openai` backend.
- `ANTHROPIC_API_KEY` — key for the `anthropic` backend/judge.

**IntentFlow (project names):**
- `IFLOW_TRACE_KEY`, `IFLOW_TRACE_KEY_ID` — HMAC signing key and its id.
- `IFLOW_TRACE_KEYS` — the audit-time key set for rotation (`id=secret,…`).
- `IFLOW_TRACE_SIGNING_KEY`, `IFLOW_TRACE_PUBLIC_KEY` — Ed25519 private/public
  keys (see [`trace-signing.md`](trace-signing.md)).
- `INTENTFLOW_MAX_ATTEMPTS`, `INTENTFLOW_RETRY_BASE_DELAY`,
  `INTENTFLOW_RETRY_MAX_DELAY`, `INTENTFLOW_RETRY_BACKOFF` — bounded retry policy.
- `INTENTFLOW_HTTP_TIMEOUT`, `INTENTFLOW_HTTP_CONNECT_TIMEOUT` — HTTP timeouts.

(The naming rule — provider-native for providers, `IFLOW_*`/`INTENTFLOW_*` for
project config — is in [`cli-conventions.md`](cli-conventions.md).)

## Recipes

### OpenAI

```bash
pip install 'intentflow[openai]'
export OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini intentflow run triage.iflow --backend openai
```

### Azure OpenAI

```bash
pip install 'intentflow[openai]'
export OPENAI_API_KEY=<azure-key>
export OPENAI_BASE_URL="https://<resource>.openai.azure.com/openai/deployments/<deployment>"
export OPENAI_MODEL=<deployment-name>
intentflow run triage.iflow --backend openai
```

### vLLM (local, OpenAI-compatible)

```bash
pip install 'intentflow[openai]'
export OPENAI_API_KEY=EMPTY
export OPENAI_BASE_URL="http://localhost:8000/v1"
export OPENAI_MODEL=<served-model-name>
intentflow run triage.iflow --backend openai
```

### Ollama (local, OpenAI-compatible)

```bash
pip install 'intentflow[openai]'
export OPENAI_API_KEY=ollama
export OPENAI_BASE_URL="http://localhost:11434/v1"
export OPENAI_MODEL=llama3.1
intentflow run triage.iflow --backend openai
```

### Anthropic

```bash
pip install 'intentflow[llm]'
export ANTHROPIC_API_KEY=sk-ant-...
intentflow run triage.iflow --backend anthropic
```

## No-key path: cassettes

Record a real backend's responses once, replay them forever (in CI, offline):

```bash
# record (needs a key)
intentflow run triage.iflow --backend openai --record-cassette triage.cassette.json
# replay (no key, deterministic)
intentflow run triage.iflow --backend replay --cassette triage.cassette.json
```

A judge shares the same cassette file — a `--judge replay` run answers verdicts
from it too, so an API-driven run is fully replayable (cognition + verdicts).

## Troubleshooting

The exact errors you may hit (quoted from `intentflow/backends.py`):

- `the 'openai' backend requires the optional dependency: pip install
  'intentflow[openai]' (or: pip install openai)` — the extra isn't installed.
- `the 'openai' backend requires OPENAI_API_KEY to be set (set
  OPENAI_BASE_URL/OPENAI_MODEL to target other providers)` — missing key. For
  local servers that ignore auth, set any non-empty value (`EMPTY`/`ollama`).
- `the 'anthropic' backend requires the optional dependency: pip install
  'intentflow[llm]'` — the extra isn't installed.
- `the 'anthropic' backend requires ANTHROPIC_API_KEY to be set` — missing key.
- `the 'replay' backend requires a cassette path` — pass `--cassette`.

Recipes are verified against the code paths, not live services; provider
conventions (Azure especially) drift, so treat them as starting points.
