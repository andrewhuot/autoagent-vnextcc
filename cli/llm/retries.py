"""Retry policy shared by live provider adapters.

Rate-limit errors (HTTP 429) and transient 5xx responses are common on
long agent runs; letting each adapter reinvent retry logic leaks
provider-specific quirks upward. This module centralises a small,
predictable policy:

* Exponential back-off with jitter.
* Configurable attempt cap — default is three retries for a total of four
  attempts, which empirically handles transient rate limits without
  turning a hard failure into a 30-second hang.
* An injectable ``sleep`` callable so tests can exercise the policy
  deterministically without wallclock waits.

The policy deliberately does *not* classify errors itself: callers pass
a ``should_retry`` predicate so provider-specific error types (e.g.
``anthropic.RateLimitError``) stay inside the provider module.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Callable, TypeVar


T = TypeVar("T")


@dataclass
class RetryPolicy:
    """Retry configuration for one logical operation.

    The policy is deliberately small: a max-attempt counter and a
    back-off schedule parameterised by an exponential factor with jitter.
    Bigger retry knobs (circuit breakers, deadline budgets) belong in a
    higher layer — this one handles the "429, wait, try again" path and
    nothing else."""

    max_attempts: int = 4
    """Total attempts including the first call. ``max_attempts=1`` disables
    retries entirely."""

    base_delay_seconds: float = 1.0
    """Delay before the second attempt. Subsequent attempts multiply by
    :attr:`backoff_factor`."""

    backoff_factor: float = 2.0
    """Multiplier applied between attempts."""

    jitter_seconds: float = 0.25
    """Uniform jitter range added to each back-off interval to keep
    retries from synchronising across concurrent clients."""

    max_delay_seconds: float = 30.0
    """Hard ceiling on any single sleep. Protects against pathological
    back-off values when a user cranks the factor up."""

    def sleep_for(self, attempt_index: int) -> float:
        """Return the sleep duration before ``attempt_index`` (1-based).

        ``attempt_index == 1`` is the first retry; the initial call
        happens before any sleep. Jitter is symmetric around the base
        delay so tests can still assert a deterministic upper bound."""
        if attempt_index <= 0:
            return 0.0
        base = self.base_delay_seconds * (self.backoff_factor ** (attempt_index - 1))
        jitter = random.uniform(-self.jitter_seconds, self.jitter_seconds)
        return max(0.0, min(self.max_delay_seconds, base + jitter))


def retry_call(
    operation: Callable[[], T],
    *,
    should_retry: Callable[[BaseException], bool],
    policy: RetryPolicy | None = None,
    sleep: Callable[[float], None] = time.sleep,
    on_retry: Callable[[int, BaseException, float], None] | None = None,
) -> T:
    """Run ``operation`` with retries.

    ``should_retry(exception)`` decides whether a raised exception is
    retryable. The caller passes this rather than a type list so it can
    distinguish ``RateLimitError`` from generic ``APIError`` without this
    module importing provider SDKs.

    ``on_retry`` — when supplied — receives ``(attempt_index, exception,
    sleep_seconds)`` before each delay. The orchestrator uses it to print
    a discreet "retrying in Ns…" hint to the user; tests use it to
    inspect the policy without mocking sleep."""
    policy = policy or RetryPolicy()
    last_exception: BaseException | None = None

    for attempt in range(1, policy.max_attempts + 1):
        try:
            return operation()
        except BaseException as exc:  # noqa: BLE001 — callers classify via should_retry
            last_exception = exc
            if attempt >= policy.max_attempts or not should_retry(exc):
                raise
            delay = policy.sleep_for(attempt)
            if on_retry is not None:
                on_retry(attempt, exc, delay)
            if delay > 0:
                sleep(delay)

    # Unreachable — the loop either returns or re-raises — but keep the
    # explicit raise so static analysers see the flow.
    assert last_exception is not None
    raise last_exception


__all__ = ["RetryPolicy", "retry_call"]
