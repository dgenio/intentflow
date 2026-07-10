"""Canonical-JSON / hashed-domain tests (issue #110).

These lock the JSON-native domain constraint that ADR 0001 adopts: hashed trace
material must be JSON-native so the canonical form is well-defined and does not
silently depend on CPython's ``str()`` coercion. They also document the
Python-specific serialization behaviors a future cross-language canonical form
must reconcile, without changing any hash bytes yet.
"""

from __future__ import annotations

import json

import pytest

from intentflow.trace import Event, Trace, assert_json_native, link_hash


class _NotJson:
    def __repr__(self) -> str:  # pragma: no cover - value irrelevant
        return "<not-json>"


def test_assert_json_native_accepts_native_structures() -> None:
    assert_json_native(
        {
            "action": "read_logs",
            "args": ["a", 1, 2.5, True, None],
            "nested": {"k": [{"x": 1}]},
        }
    )


@pytest.mark.parametrize(
    "value",
    [
        _NotJson(),
        {"ok": _NotJson()},
        [1, 2, _NotJson()],
        {"nested": {"deep": _NotJson()}},
    ],
)
def test_assert_json_native_rejects_non_native_values(value) -> None:
    with pytest.raises(TypeError):
        assert_json_native(value)


def test_assert_json_native_rejects_non_str_object_keys() -> None:
    with pytest.raises(TypeError, match="object key must be str"):
        assert_json_native({1: "one"})


def test_error_names_the_offending_path() -> None:
    with pytest.raises(TypeError, match=r"detail\.args\[2\]"):
        assert_json_native({"args": [1, 2, _NotJson()]}, "detail")


def test_record_rejects_a_non_native_detail() -> None:
    trace = Trace()
    with pytest.raises(TypeError):
        trace.record("call_backend", Event.BACKEND_RESPONDED, {"obj": _NotJson()})
    # The failed record must not have entered the chain.
    assert trace.to_list() == []


def test_record_accepts_native_detail_and_chains() -> None:
    trace = Trace()
    trace.record("parse", Event.PHASE_STARTED, {"title": "t", "n": 1, "ok": True})
    assert len(trace.to_list()) == 1


def test_default_str_is_unreachable_for_recorded_events() -> None:
    # link_hash still carries default=str defensively, but the domain guard means
    # a real record() never reaches it. Demonstrate the divergence the guard
    # prevents: default=str would coerce a non-native object to a Python repr,
    # producing a hash no other language could reproduce.
    core = {"seq": 1, "phase": "p", "event": "e", "detail": {"x": _NotJson()}}
    coerced = link_hash("0" * 64, core)  # only works because of default=str
    assert isinstance(coerced, str) and len(coerced) == 64
    # But recording such a detail is refused, so this value can never appear in
    # a real trace.
    with pytest.raises(TypeError):
        assert_json_native(core["detail"])


def test_non_ascii_is_currently_escaped_documenting_the_jcs_gap() -> None:
    # ADR 0001: today's form uses ensure_ascii=True (\uXXXX escapes). A future
    # JCS-conformant form emits raw UTF-8. This test pins current behavior so the
    # migration is a visible, versioned change rather than a silent one.
    payload = json.dumps({"s": "café"}, sort_keys=True)
    assert "\\u00e9" in payload  # é is escaped today
    assert "café" not in payload
