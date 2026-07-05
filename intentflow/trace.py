"""Trace primitives: the project's third contract artifact.

An IntentFlow run emits an **auditable, append-only, hash-chained trace**. That
trace is a *contract artifact* on the same footing as the source program and the
compiled plan, so its shape and vocabulary live in their own module rather than
buried in the runtime that happens to produce them. The auditor
(:mod:`intentflow.auditor`) — the *independent verifier* — depends on this
module, never on the runtime it is meant to check.

What lives here:

* :data:`GENESIS_HASH`, :func:`link_hash`, and :class:`Trace` — the hash-chain
  primitives that make a run tamper-evident;
* :data:`CANONICAL_PHASES` — the phase order every conformant run must follow;
* :class:`Event` and :data:`KNOWN_EVENTS` — the trace event vocabulary, so the
  ~two dozen event-name strings are defined once and shared by the runtime, the
  action gate, and the auditor instead of being retyped (and mistyped) in three
  modules.

This module imports only the standard library, keeping it a leaf of the import
graph: everything depends on it, it depends on nothing in the package.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

#: Version of the *result/trace (witness) format* — the shape of the run-result
#: envelope a run emits and the auditor consumes. Independent of the plan format
#: version (``compiler.PLAN_FORMAT_VERSION``) and of the package version. Bumped
#: when the witness shape changes in a way an auditor must react to; the
#: auditor's ``SUPPORTED_TRACE_FORMATS`` declares which values it can verify.
#: See ``docs/formats.md``.
TRACE_FORMAT_VERSION = "0.1"

#: The phase order every conformant run must follow (embedded in each plan as
#: ``execution_phases`` and checked by the auditor as T2). The compiler
#: re-exports this as ``EXECUTION_PHASES`` for plan emission.
CANONICAL_PHASES: tuple[str, ...] = (
    "parse",
    "analyze",
    "compile",
    "prepare_context",
    "collect_evidence",
    "build_messages",
    "call_backend",
    "parse_output",
    "verify_output",
    "apply_uncertainty_policy",
    "enforce_action_policy",
    "finalize",
    "trace",
)


class Event:
    """The trace event vocabulary as named constants.

    Every event name recorded by the runtime or the action gate — and every
    name the auditor matches on — comes from here, so a typo becomes an
    ``AttributeError`` at import time instead of a silently missed audit match.
    Plain ``str`` constants (not ``enum.StrEnum``) because the package supports
    Python 3.10, and because the recorded values must stay bare strings for the
    hash chain and JSON serialization.
    """

    # -- lifecycle / phases --
    PHASE_STARTED = "phase_started"
    RUN_STARTED = "run_started"
    RUN_COMPLETED = "run_completed"
    STATUS_RESOLVED = "status_resolved"

    # -- context / evidence --
    POLICY_APPLIED = "policy_applied"
    EVIDENCE_COLLECTED = "evidence_collected"
    EVIDENCE_UNAVAILABLE = "evidence_unavailable"
    SOURCE_DISTRUSTED = "source_distrusted"
    NO_EVIDENCE_REQUIRED = "no_evidence_required"
    MISSING_EVIDENCE = "missing_evidence"
    TOOL_FAILED = "tool_failed"

    # -- prompt / backend / output --
    MESSAGES_BUILT = "messages_built"
    BACKEND_RESPONDED = "backend_responded"
    BACKEND_FAILED = "backend_failed"
    PARSE_FAILED = "parse_failed"
    OUTPUT_PARSED = "output_parsed"
    CITATIONS_DROPPED = "citations_dropped"
    EXTRA_FIELDS_DROPPED = "extra_fields_dropped"

    # -- verification --
    CHECK_EVALUATED = "check_evaluated"
    CHECKLIST_COMPLETED = "checklist_completed"

    # -- uncertainty --
    RULE_EVALUATED = "rule_evaluated"
    RULE_NOT_EVALUABLE = "rule_not_evaluable"
    HUMAN_ESCALATION = "human_escalation"
    ACTION_BLOCKED_BY_POLICY = "action_blocked_by_policy"
    ACTION_RECORDED = "action_recorded"

    # -- action gate (tools.py) --
    ACTION_BLOCKED = "action_blocked"
    APPROVAL_DENIED = "approval_denied"
    APPROVAL_GRANTED = "approval_granted"
    TOOL_INVOKED = "tool_invoked"
    TOOL_COMPLETED = "tool_completed"

    # -- action policy review --
    POLICY_REVIEWED = "policy_reviewed"


#: Every event name the vocabulary defines. ``Trace.record`` checks membership
#: so an unknown event name fails loudly instead of quietly widening the format.
KNOWN_EVENTS: frozenset[str] = frozenset(
    value
    for name, value in vars(Event).items()
    if not name.startswith("_") and isinstance(value, str)
)


#: The first link of every trace hash chain (no prior event).
GENESIS_HASH = "0" * 64

#: Keys that make up an event's *core* — the part that is hash-chained. The
#: ``hash``/``prev_hash`` links and presentation-only tags (e.g. ``stage``)
#: are excluded so the chain is stable across serialization and pipelining.
_CORE_KEYS = ("seq", "phase", "event", "detail")


def _event_core(event: dict[str, Any]) -> dict[str, Any]:
    return {k: event.get(k) for k in _CORE_KEYS}


def assert_json_native(value: Any, _path: str = "detail") -> None:
    """Raise ``TypeError`` unless ``value`` is composed only of JSON-native
    types (``dict`` with ``str`` keys, ``list``, ``str``, ``int``, ``float``,
    ``bool``, ``None``).

    Hashed trace material must be JSON-native so the canonical form is
    well-defined and reproducible: ``json.dumps`` never has to fall back to a
    Python-specific ``str()`` coercion of an arbitrary object, which would make
    the hash silently depend on CPython's ``repr``. Enforcing the domain at
    record time turns "the hash quietly widened to cover a new type" into a
    loud error at the exact call site that introduced it. See
    ``docs/adr/0001-canonical-json-hashing.md``.
    """
    # bool is a subclass of int; both are JSON-native, so no special-casing.
    if value is None or isinstance(value, (str, int, float)):
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(
                    f"trace {_path}: JSON object key must be str, got "
                    f"{type(key).__name__} {key!r}"
                )
            assert_json_native(item, f"{_path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            assert_json_native(item, f"{_path}[{index}]")
        return
    raise TypeError(
        f"trace {_path}: value is not JSON-native "
        f"({type(value).__name__}: {value!r})"
    )


def link_hash(prev_hash: str, event: dict[str, Any]) -> str:
    """The hash that chains ``event`` to its predecessor.

    ``sha256(prev_hash || canonical(core))`` — so any edit, deletion, or
    reordering is detected when the chain is recomputed (unless a forger also
    recomputes every downstream link; see :class:`Trace`). Canonicalization is
    JSON with sorted keys, so the chain survives a round-trip through disk.

    :meth:`Trace.record` enforces (via :func:`assert_json_native`) that the
    event core is JSON-native, so the ``default=str`` fallback below is
    unreachable for any event the runtime records. It is retained defensively;
    the format-versioned follow-up to ``docs/adr/0001-canonical-json-hashing.md``
    removes it and tightens serialization to a documented cross-language form.
    """
    payload = prev_hash + json.dumps(
        _event_core(event), sort_keys=True, default=str
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Trace:
    """An auditable, append-only, hash-chained record of a run.

    Each event carries ``prev_hash`` and ``hash`` forming a chain rooted at
    :data:`GENESIS_HASH`. Recomputing the chain detects accidental corruption,
    truncation, and reordering without the program. The links live *inside* the
    trace, though, so a motivated forger can edit an event and recompute every
    downstream hash — the bare chain is integrity, not authenticity. Sealing
    the root out of band closes that gap: with a signing key, ``seal()`` adds an
    HMAC over the root so anyone holding the key can *detect* (not prevent)
    edits, even to runs they did not execute.
    """

    def __init__(self, sign_key: bytes | None = None) -> None:
        self.events: list[dict[str, Any]] = []
        self._prev = GENESIS_HASH
        self._sign_key = sign_key

    def record(self, phase: str, event: str, detail: dict[str, Any] | None = None) -> None:
        entry = {
            "seq": len(self.events) + 1,
            "phase": phase,
            "event": event,
            "detail": detail or {},
        }
        # Enforce the JSON-native domain before the value enters the hash chain,
        # so the canonical form stays well-defined (no silent str() coercion).
        assert_json_native(entry["detail"], f"{event}.detail")
        entry["prev_hash"] = self._prev
        entry["hash"] = link_hash(self._prev, entry)
        self._prev = entry["hash"]
        self.events.append(entry)

    def to_list(self) -> list[dict[str, Any]]:
        return list(self.events)

    def seal(self) -> dict[str, Any]:
        """A compact, verifiable summary of the chain: algorithm, length,
        root hash, and (if a key was supplied) an HMAC signature over it."""
        signature = None
        if self._sign_key is not None:
            signature = hmac.new(
                self._sign_key, self._prev.encode("utf-8"), hashlib.sha256
            ).hexdigest()
        return {
            "algo": "sha256-chain",
            "length": len(self.events),
            "root": self._prev,
            "signature": signature,
        }
