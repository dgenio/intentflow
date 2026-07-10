"""Reliability tests: HTTP timeouts and the bounded, fail-closed retry policy
shared by real cognition backends and the LLM judge. No network required."""

from __future__ import annotations

import pytest

from intentflow.backends import BackendError
from intentflow.reliability import HTTPTimeout, RetryPolicy


class _Flaky:
    """A callable that raises ``fails`` times, then returns ``value``."""

    def __init__(self, fails: int, value: str = "ok") -> None:
        self.fails = fails
        self.value = value
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        if self.calls <= self.fails:
            raise ConnectionError(f"transient error {self.calls}")
        return self.value


def _no_sleep_policy(**kw) -> tuple[RetryPolicy, list[float]]:
    slept: list[float] = []
    policy = RetryPolicy(sleep=slept.append, **kw)
    return policy, slept


def test_first_attempt_success_does_not_retry_or_sleep() -> None:
    policy, slept = _no_sleep_policy(max_attempts=3)
    fn = _Flaky(fails=0)
    assert policy.run(fn) == "ok"
    assert fn.calls == 1
    assert slept == []


def test_retries_then_succeeds() -> None:
    policy, slept = _no_sleep_policy(max_attempts=3, base_delay=0.5, backoff=2.0)
    fn = _Flaky(fails=2)
    assert policy.run(fn) == "ok"
    assert fn.calls == 3
    # Two backoff sleeps before attempts 2 and 3: 0.5 * 2**0, 0.5 * 2**1.
    assert slept == [0.5, 1.0]


def test_exhaustion_fails_closed_as_backend_error() -> None:
    policy, slept = _no_sleep_policy(max_attempts=3, base_delay=0.1)
    fn = _Flaky(fails=99)
    with pytest.raises(BackendError, match="failed after 3 attempt"):
        policy.run(fn, describe="widget")
    assert fn.calls == 3
    assert len(slept) == 2  # one sleep between each of the 3 attempts


def test_backend_error_message_carries_the_last_cause() -> None:
    policy, _ = _no_sleep_policy(max_attempts=1)
    with pytest.raises(BackendError, match="transient error 1") as exc:
        policy.run(_Flaky(fails=1), describe="widget")
    assert isinstance(exc.value.__cause__, ConnectionError)


def test_non_retryable_exceptions_propagate_immediately() -> None:
    policy, slept = _no_sleep_policy(max_attempts=5)
    calls = {"n": 0}

    def fn() -> str:
        calls["n"] += 1
        raise NotImplementedError("abstract")

    with pytest.raises(NotImplementedError):
        policy.run(fn)
    assert calls["n"] == 1  # not retried
    assert slept == []


def test_delay_is_capped_at_max_delay() -> None:
    policy = RetryPolicy(base_delay=1.0, backoff=10.0, max_delay=5.0)
    assert policy.delay_for(1) == 1.0
    assert policy.delay_for(2) == 5.0  # 10.0 capped to 5.0
    assert policy.delay_for(3) == 5.0


def test_disabled_policy_is_single_attempt() -> None:
    policy = RetryPolicy.disabled()
    assert policy.max_attempts == 1
    fn = _Flaky(fails=1)
    with pytest.raises(BackendError):
        policy.run(fn)
    assert fn.calls == 1


def test_retry_policy_from_env(monkeypatch) -> None:
    monkeypatch.setenv("INTENTFLOW_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("INTENTFLOW_RETRY_BASE_DELAY", "0.25")
    monkeypatch.setenv("INTENTFLOW_RETRY_MAX_DELAY", "12")
    monkeypatch.setenv("INTENTFLOW_RETRY_BACKOFF", "3")
    policy = RetryPolicy.from_env()
    assert policy.max_attempts == 5
    assert policy.base_delay == 0.25
    assert policy.max_delay == 12.0
    assert policy.backoff == 3.0


def test_retry_policy_from_env_ignores_garbage(monkeypatch) -> None:
    monkeypatch.setenv("INTENTFLOW_MAX_ATTEMPTS", "not-a-number")
    assert RetryPolicy.from_env().max_attempts == RetryPolicy.max_attempts


def test_http_timeout_defaults_and_env(monkeypatch) -> None:
    assert HTTPTimeout() == HTTPTimeout(connect=10.0, read=60.0)
    monkeypatch.setenv("INTENTFLOW_HTTP_TIMEOUT", "30")
    monkeypatch.setenv("INTENTFLOW_HTTP_CONNECT_TIMEOUT", "3")
    t = HTTPTimeout.from_env()
    assert t.read == 30.0
    assert t.connect == 3.0


def test_http_timeout_as_sdk_is_usable() -> None:
    sdk = HTTPTimeout(connect=2.0, read=20.0).as_sdk()
    # httpx.Timeout when available, else the read timeout as a float.
    try:
        import httpx

        assert isinstance(sdk, httpx.Timeout)
        assert sdk.read == 20.0
        assert sdk.connect == 2.0
    except ImportError:  # pragma: no cover - depends on the environment
        assert sdk == 20.0
