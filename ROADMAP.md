# IntentFlow Roadmap

This file is the canonical roadmap source for IntentFlow.

The roadmap sections in README and docs/architecture.md intentionally link here
to avoid drift across multiple copies.

## Recently Shipped

- Typed outputs, analyzer, phase runtime, replay/explain shipped in commit f6bfd6a (v0.6.0).
- Blocking approval gates (pre-grant, interactive TTY, synchronous webhook)
  shipped in commit cb6168c. Remaining async/polling follow-up: #2.
- Hash-chained traces with optional HMAC sealing shipped in commit cb6168c.
  Public-key signature follow-up: #81.
- Python embedding API and governed Python tool registration shipped in
  commit cb6168c.
- LLM judge runner with separate trust tier shipped in commit cb6168c.
- OpenAI-compatible cognition backend shipped in commit 70e9af2.

## Active Roadmap

1. Learned confidence calibration map from scored runs (#8)
2. Context policy compiler and budget enforcement (#9)
3. Richer machine-checkable verification predicates (#58)
4. DAG pipelines with static evidence-chain guarantees (#7)
5. Asynchronous or polling approval flow for gated actions (#2)
6. Ed25519 public-key trace signatures alongside HMAC (#81)
7. Plan-level compiler optimizations for token, latency, and risk (#106)
