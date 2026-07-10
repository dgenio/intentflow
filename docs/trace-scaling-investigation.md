# Investigation: trace memory and trace-id hashing cost (#47)

- **Status:** Complete
- **Issue:** [#47](https://github.com/dgenio/intentflow/issues/47)
- **Benchmark:** [`scripts/bench_trace.py`](../scripts/bench_trace.py) (run
  directly; not part of the default test suite)
- **Related:** #82 (streaming trace sink), #110 (canonical hashing)

## Question

Two things scale with run size and were never measured:

1. `Trace` holds every event in an in-memory list; the whole trace is returned
   in the result and written to disk at the end.
2. `_summarize()` derived `trace_id` by re-serializing the entire
   `{plan, trace}` document and hashing it — **O(trace length)** per run.

Do either become a problem for large goals or long pipelines, and can `trace_id`
be derived from the chain root the `Trace` already maintains?

## Method

`scripts/bench_trace.py` compiles a synthetic goal with *N* optional evidence
sources and *N* phrase-verification rules (which drive trace length), runs it on
the deterministic simulator, and measures wall time, peak `tracemalloc` heap,
event count, and the cost of deriving `trace_id` both ways.

## Results

Representative run (simulator backend, warm interpreter):

| evidence | rules | events | run_ms | peak_kb | old_id_µs | new_id_µs | speedup |
|---------:|------:|-------:|-------:|--------:|----------:|----------:|--------:|
|        4 |     4 |     32 |    2.9 |      48 |     159.0 |      42.2 |    3.8× |
|       25 |    25 |     74 |    6.2 |     113 |     374.1 |      84.1 |    4.4× |
|      100 |   100 |    224 |   18.5 |     351 |    1182.0 |     228.6 |    5.2× |
|      400 |   400 |    824 |   68.0 |    1335 |    5239.6 |     886.0 |    5.9× |

(Absolute times vary by machine; the *trends* are the finding.)

## Conclusions

1. **`trace_id` re-serialization was the removable cost, and it is removed.**
   The historical full-document derivation grew ~33× (159 → 5240 µs) as the
   trace grew from 32 to 824 events. `trace_id` is now derived as
   `sha256(plan_digest + chain_root)`: the chain root already commits —
   incrementally, one link per recorded event — to the whole trace, so no
   trace re-serialization is needed. Cost drops 3.8–5.9× and no longer scales
   with trace length (only with plan size, which is intrinsic to identifying a
   run). Determinism is preserved (identical runs → identical id), and audit
   semantics are untouched: the auditor never consumes `trace_id`. **Change
   made in this PR.**

2. **Trace memory is linear (~1.6 KB/event) and fine for typical runs, but
   unbounded for long ones.** A few dozen events cost tens of KB — negligible.
   Peak heap grows linearly with event count because the trace is retained in
   full. For very long pipelines or high-evidence runs this is a real ceiling.
   This is exactly what the opt-in JSONL streaming sink (#82) addresses: events
   can be flushed to disk as they are recorded instead of accumulating, and the
   hash chain makes a partially-written stream verifiable as a prefix. **No
   change to in-memory retention here; #82 is the remediation and is
   implemented separately in this PR.**

3. **No further optimization is warranted now.** Compile/run time is dominated
   by the per-event work itself, not by hashing or memory, at the sizes a
   governance workload realistically produces. Revisit only if profiling of a
   real large deployment shows otherwise.
