# ADR 0001 — Canonical JSON form for hashed trace and plan material

- **Status:** Accepted (investigation complete; byte-format migration deferred)
- **Date:** 2026-07
- **Issue:** [#110](https://github.com/dgenio/intentflow/issues/110)
- **Related:** #17 (JSON Schemas), #38 (format versioning), #67 (`trace.py`),
  #48 (conformance kit), #103 (independent TypeScript auditor)

## Context

IntentFlow's central claim is third-party verifiability: an auditor that did
not produce a trace can recompute its hash chain and confirm conformance. That
claim becomes *cross-language* the moment a second implementation exists (the
planned TypeScript auditor, #103; the conformance kit, #48). Every hash input
must therefore have a canonical byte form that any language can reproduce.

Today the hashed material is serialized with Python's `json.dumps`:

- `trace.link_hash`: `prev_hash + json.dumps(_event_core(event), sort_keys=True, default=str)`, SHA-256.
- `compiler.plan_hash` / `source_hash`: `json.dumps(document, sort_keys=True)`, SHA-256.

`json.dumps` is **not** a cross-language canonical form:

1. **`default=str`** — any non-JSON-native value reaching a hashed structure is
   silently coerced via CPython's `str()`. The hash then depends on a Python
   `repr`, which no other language can reproduce, and the dependency is
   invisible (no error, no test).
2. **Non-ASCII escaping** — `ensure_ascii=True` (the default) emits `\uXXXX`
   escapes. A conforming serializer that emits raw UTF-8 (as RFC 8785 requires)
   produces different bytes for the same logical string.
3. **Float formatting** — Python uses shortest-round-trip `repr` for floats,
   which is *close* to but not guaranteed identical to the ECMAScript
   `Number.prototype.toString` algorithm RFC 8785 mandates.
4. **Object key ordering** — `sort_keys=True` sorts by Unicode code point; RFC
   8785 sorts by UTF-16 code unit. These agree for the entire Basic
   Multilingual Plane and diverge only for supplementary-plane (non-BMP)
   characters used *as object keys*.

## Decision

**Constrain the hashed domain to JSON-native, float-controlled values now;
defer the serialization byte-format change to a version-gated follow-up.**

1. **Enforce a JSON-native domain (this PR).** `trace.Trace.record` calls
   `trace.assert_json_native` on every event `detail` before it enters the
   chain. Only `dict` (with `str` keys), `list`, `str`, `int`, `float`, `bool`,
   and `None` are permitted; anything else raises `TypeError` at the recording
   call site. This eliminates *reliance* on `default=str` — it is now provably
   unreachable for any recorded event (verified across every bundled example),
   so the retained fallback is defensive dead code, documented as such in
   `link_hash`. The canonical form is thereby well-defined: sorted-key JSON over
   a fixed, small type set.

2. **Adopt RFC 8785 (JCS) as the target profile, for the constrained domain.**
   With the domain restricted to JSON-native values, the gap between today's
   output and JCS narrows to two byte-level items: non-ASCII escaping
   (`ensure_ascii`) and the BMP-only key-sort caveat. For the data IntentFlow
   actually hashes — ASCII event names, ASCII/limited-Unicode detail text, no
   floats in the event *core* — the current output is **already
   JCS-conformant**. The one documented, accepted limitation is that a non-BMP
   character used as a JSON *object key* could sort differently; IntentFlow does
   not produce such keys (all keys are fixed ASCII identifiers).

3. **Do not change hash bytes in this PR.** `link_hash` and `plan_hash` are
   left byte-for-byte identical, because changing them without a format-version
   marker would silently invalidate every existing witness. The version marker
   (`format_version`, #17/#38) ships in this PR; the actual serialization change
   rides a later, version-gated migration where the auditor accepts both forms
   keyed on the marker.

## Consequences

- **Positive:** the hashed domain is now enforced and tested, not accidental;
  the canonical form is documented; cross-language reimplementation has a
  precise target (JCS over the constrained domain); the risky byte-format change
  is decoupled from this PR and gated behind a version marker.
- **Negative:** `default=str` remains in the source as documented dead code
  until the follow-up; a run that (due to a future runtime bug) tries to record
  a non-JSON-native detail now fails loudly mid-run rather than silently
  hashing a coerced value — an intended trade (fail-closed over silent drift).

## Follow-up

Open a `format_version`-gated migration issue to:

- switch serialization to `ensure_ascii=False` (raw UTF-8) and remove
  `default=str`;
- specify the number-formatting profile (or forbid floats in all hashed
  material, not just the event core);
- have the auditor accept both the pre- and post-migration forms keyed on
  `format_version`, with a documented end date;
- add golden artifacts in both forms.
