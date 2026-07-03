"""Reliability primitives for calls that leave the deterministic core.

Everything in IntentFlow is deterministic except one thing: talking to a real
model or judge over the network. That is the one place a run can hang, flake,
or fail — so it is the one place that needs explicit timeouts and a bounded,
fail-closed retry policy. Keeping both here (rather than scattered through the
backends) means cognition backends and the LLM judge share exactly one
definition of "how long do we wait" and "how many times do we try".

Two knobs, both env-configurable and both safe by default:

* :class:`HTTPTimeout` — a connect/read timeout handed to the provider SDK.
* :class:`RetryPolicy` — bounded retries with deterministic exponential
  backoff. On exhaustion it raises :class:`~intentflow.backends.BackendError`,
  never a partial success: a call that never returned a value fails the run.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Callable


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class HTTPTimeout:
    """An explicit connect/read timeout for real backend and judge calls.

    Both the ``anthropic`` and ``openai`` SDKs accept either a plain float
    (total seconds) or an ``httpx.Timeout``. :meth:`as_sdk` returns the richer
    ``httpx.Timeout`` when httpx is importable (it always is when either SDK is
    installed) and falls back to the read timeout as a float otherwise, so the
    core install never grows a dependency.
    """

    connect: float = 10.0
    read: float = 60.0

    @classmethod
    def from_env(cls) -> "HTTPTimeout":
        """Build from ``INTENTFLOW_HTTP_*`` env vars.

        ``INTENTFLOW_HTTP_TIMEOUT`` sets the read timeout (the common case);
        ``INTENTFLOW_HTTP_CONNECT_TIMEOUT`` overrides the connect timeout.
        """
        read = _env_float("INTENTFLOW_HTTP_TIMEOUT", cls.read)
        connect = _env_float("INTENTFLOW_HTTP_CONNECT_TIMEOUT", cls.connect)
        return cls(connect=connect, read=read)

    def as_sdk(self) -> Any:
        """The value to pass as the provider SDK's ``timeout=`` argument."""
        try:
            import httpx
        except ImportError:  # pragma: no cover - httpx ships with the SDKs
            return self.read
        return httpx.Timeout(self.read, connect=self.connect)


@dataclass
class RetryPolicy:
    """Bounded retries with deterministic exponential backoff, fail-closed.

    A call is attempted up to :attr:`max_attempts` times. Between attempts the
    policy sleeps ``min(max_delay, base_delay * backoff ** (attempt - 1))``.
    Exceptions in :attr:`no_retry` propagate immediately (they are not
    transient). Any other exception is retried; once attempts are exhausted the
    last error is re-raised as a :class:`~intentflow.backends.BackendError` so
    the runtime records a clean ``backend_error`` rather than a leaked
    provider exception.

    ``sleep`` is injectable so tests exercise the backoff schedule without
    real delays, and ``on_retry`` is an optional hook (attempt, exc) for
    observability.
    """

    max_attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0
    backoff: float = 2.0
    no_retry: tuple[type[BaseException], ...] = (NotImplementedError,)
    sleep: Callable[[float], None] = time.sleep
    on_retry: Callable[[int, BaseException], None] | None = None

    @classmethod
    def from_env(cls) -> "RetryPolicy":
        """Build from ``INTENTFLOW_*`` env vars, falling back to safe defaults."""
        return cls(
            max_attempts=max(1, _env_int("INTENTFLOW_MAX_ATTEMPTS", cls.max_attempts)),
            base_delay=_env_float("INTENTFLOW_RETRY_BASE_DELAY", cls.base_delay),
            max_delay=_env_float("INTENTFLOW_RETRY_MAX_DELAY", cls.max_delay),
            backoff=_env_float("INTENTFLOW_RETRY_BACKOFF", cls.backoff),
        )

    @classmethod
    def disabled(cls) -> "RetryPolicy":
        """A single-attempt policy: no retries, still fail-closed."""
        return cls(max_attempts=1)

    def delay_for(self, attempt: int) -> float:
        """The backoff delay (seconds) before the given 1-indexed attempt."""
        return min(self.max_delay, self.base_delay * (self.backoff ** (attempt - 1)))

    def run(self, fn: Callable[[], Any], *, describe: str = "call") -> Any:
        """Run ``fn`` with bounded retries. Fail-closed on exhaustion."""
        last: BaseException | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                return fn()
            except self.no_retry:
                raise
            except Exception as exc:  # transient by assumption; bounded above
                last = exc
                if attempt >= self.max_attempts:
                    break
                if self.on_retry is not None:
                    self.on_retry(attempt, exc)
                # The Nth wait (before attempt N+1) uses delay_for(N): the
                # first backoff is base_delay, then it grows geometrically.
                self.sleep(self.delay_for(attempt))
        # Import here to avoid a circular import at module load.
        from intentflow.backends import BackendError

        raise BackendError(
            f"{describe} failed after {self.max_attempts} attempt(s): {last}"
        ) from last
