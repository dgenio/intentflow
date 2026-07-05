#!/usr/bin/env python3
"""Microbenchmark for trace memory and trace-id hashing cost (issue #47).

Not part of the default test run — invoke directly:

    python scripts/bench_trace.py

It scales a synthetic goal along two axes (declared evidence sources and
verification rules, which together drive trace length) and reports, per size:

* wall-clock time for a full ``GoalRuntime.run()``;
* peak Python heap during the run (``tracemalloc``);
* the number of trace events produced;
* the cost of deriving ``trace_id`` two ways —
  the historical full-document method (re-serialize ``{plan, trace}``) versus
  the current chain-root method (hash the plan digest + the chain root).

The point is to show whether the historical full-document hash grows with trace
length (it does) and that the chain-root derivation removes that growth.
"""

from __future__ import annotations

import hashlib
import json
import time
import tracemalloc

from intentflow.compiler import compile_program
from intentflow.parser import parse_source


def _synthetic_source(n_evidence: int, n_rules: int) -> str:
    """Build a valid .iflow goal with ``n_evidence`` optional evidence sources
    and ``n_rules`` phrase-verification rules, so the trace scales with size."""
    evidence = "\n".join(f"    optional source_{i}" for i in range(n_evidence))
    rules = "\n".join(f"    output must include marker_{i}" for i in range(n_rules))
    return (
        "goal Scale {\n"
        "  objective:\n"
        "    stress the trace with many evidence sources and rules\n"
        "  evidence:\n"
        f"{evidence}\n"
        "  verify:\n"
        "    require cites_evidence\n"
        f"{rules}\n"
        "  output:\n"
        "    answer: string\n"
        "}\n"
    )


def _old_trace_id(plan: dict, trace: list[dict]) -> str:
    """The historical derivation: re-serialize the whole {plan, trace}."""
    return hashlib.sha256(
        json.dumps({"plan": plan, "trace": trace}, sort_keys=True, default=str).encode(
            "utf-8"
        )
    ).hexdigest()[:16]


def _new_trace_id(plan: dict, chain_root: str) -> str:
    """The current derivation: plan digest + incremental chain root."""
    plan_digest = hashlib.sha256(
        json.dumps(plan, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return hashlib.sha256(f"{plan_digest}{chain_root}".encode("utf-8")).hexdigest()[:16]


def _hash_ns(fn, *args, repeat: int = 50) -> int:
    start = time.perf_counter_ns()
    for _ in range(repeat):
        fn(*args)
    return (time.perf_counter_ns() - start) // repeat


def main() -> None:
    # Import here so a missing optional dep can never affect import-time.
    from intentflow.runtime import GoalRuntime

    sizes = [(4, 4), (25, 25), (100, 100), (400, 400)]
    print(
        f"{'evidence':>8} {'rules':>6} {'events':>7} {'run_ms':>8} "
        f"{'peak_kb':>8} {'old_id_us':>10} {'new_id_us':>10} {'speedup':>8}"
    )
    for n_evidence, n_rules in sizes:
        document = compile_program(parse_source(_synthetic_source(n_evidence, n_rules)))
        plan = document["goals"][0]

        tracemalloc.start()
        start = time.perf_counter()
        result = GoalRuntime(plan, printer=None).run()
        run_ms = (time.perf_counter() - start) * 1000
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        trace = result["trace"]
        root = result["trace_chain"]["root"]
        old_us = _hash_ns(_old_trace_id, plan, trace) / 1000
        new_us = _hash_ns(_new_trace_id, plan, root) / 1000
        speedup = (old_us / new_us) if new_us else float("inf")
        print(
            f"{n_evidence:>8} {n_rules:>6} {len(trace):>7} {run_ms:>8.1f} "
            f"{peak // 1024:>8} {old_us:>10.1f} {new_us:>10.1f} {speedup:>7.1f}x"
        )


if __name__ == "__main__":
    main()
