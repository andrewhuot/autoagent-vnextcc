"""Tests for :mod:`cli.mcp.reconnect` (P3.T8).

The ReconnectingTransport wraps a :class:`Transport` with a supervisor
thread that keeps the inner transport alive through transient failures
and invalidates downstream caches after every successful reconnect.

These tests use a ``FakeTransport`` double rather than a real MCP server
subprocess — the supervisor only cares about
``connect / close / is_connected / send / receive``. Timing is controlled
with a fake clock patched onto ``cli.mcp.reconnect.time`` so the suite
runs in milliseconds and is not flaky in CI (mirrors the approach used
by ``tests/test_mcp_transport_sse.py::test_sse_transport_is_connected_reflects_staleness``).
"""

from __future__ import annotations

import threading
import time as real_time
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

import pytest

from cli.mcp.reconnect import ReconnectingTransport

# Capture the real sleep/monotonic BEFORE anyone monkeypatches the time
# module — tests need real wall-clock waits to drive the supervisor, and
# monkeypatching the module attribute clobbers ``real_time.sleep`` too
# (because ``real_time`` is the same module object).
_REAL_SLEEP = real_time.sleep
_REAL_MONOTONIC = real_time.monotonic


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


@dataclass
class FakeTransport:
    """Minimal Transport double with controllable failure injection.

    * ``fail_on_connect_count`` — number of upcoming ``connect()`` calls
      that will raise. Decrements on each raise; the next call after the
      counter hits zero succeeds.
    * ``is_connected`` is writeable so tests can flip it mid-stream to
      simulate a server drop.
    """

    fail_on_connect_count: int = 0
    raise_on_send: Optional[Exception] = None
    receive_value: Optional[dict] = None
    is_connected: bool = False
    connect_calls: int = 0
    close_calls: int = 0
    sent: List[dict] = field(default_factory=list)
    received_timeouts: List[float] = field(default_factory=list)

    def connect(self) -> None:
        self.connect_calls += 1
        if self.fail_on_connect_count > 0:
            self.fail_on_connect_count -= 1
            raise RuntimeError(f"connect fail #{self.connect_calls}")
        self.is_connected = True

    def close(self) -> None:
        self.close_calls += 1
        self.is_connected = False

    def send(self, payload: dict) -> None:
        if self.raise_on_send is not None:
            raise self.raise_on_send
        self.sent.append(payload)

    def receive(self, timeout: float) -> Optional[dict]:
        self.received_timeouts.append(timeout)
        return self.receive_value


class FakeClock:
    """Patchable monotonic + sleep. ``sleep`` advances ``now`` and also
    records each requested sleep duration so tests can assert backoff
    timing without real waits."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start
        self.sleeps: List[float] = []
        self._cond = threading.Condition()

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        with self._cond:
            self.sleeps.append(seconds)
            self.now += seconds
            self._cond.notify_all()
        # Yield to other threads so the supervisor doesn't starve the
        # test driver (and vice versa). Real time.sleep releases the
        # GIL; our fake has to do so explicitly or threads on tight
        # loops monopolize the interpreter.
        _REAL_SLEEP(0)

    def wait_for_sleeps(self, n: int, timeout: float = 2.0) -> None:
        """Block the real wall clock until the supervisor has called
        sleep() at least ``n`` times, or until ``timeout`` expires.

        The test driver uses this to synchronize with the background
        supervisor without racing on shared state.
        """
        deadline = _REAL_MONOTONIC() + timeout
        with self._cond:
            while len(self.sleeps) < n:
                remaining = deadline - _REAL_MONOTONIC()
                if remaining <= 0:
                    raise AssertionError(
                        f"expected >= {n} sleeps, saw {len(self.sleeps)}"
                    )
                self._cond.wait(timeout=remaining)


@pytest.fixture
def fake_clock(monkeypatch):
    clock = FakeClock()
    from cli.mcp import reconnect as reconnect_mod

    monkeypatch.setattr(reconnect_mod.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(reconnect_mod.time, "sleep", clock.sleep)
    return clock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_happy_path_delegates_to_inner(fake_clock):
    """Case 1: wrap, connect, send, receive — delegates to the inner transport."""
    inner = FakeTransport(receive_value={"ok": True})
    rt = ReconnectingTransport(inner=inner, ping_interval_seconds=0.01)
    try:
        rt.connect()
        assert rt.is_connected
        rt.send({"hello": "world"})
        assert inner.sent == [{"hello": "world"}]
        assert rt.receive(timeout=0.1) == {"ok": True}
        assert inner.received_timeouts[-1] == 0.1
    finally:
        rt.close()


def test_first_connect_failure_then_retry_succeeds(fake_clock):
    """Case 2: inner raises on first N connect()s, succeeds on N+1."""
    inner = FakeTransport(fail_on_connect_count=2)
    rt = ReconnectingTransport(
        inner=inner,
        ping_interval_seconds=0.01,
        backoff_schedule_seconds=(1.0, 2.0, 4.0),
    )
    try:
        rt.connect()  # should NOT raise
        assert rt.is_connected
        assert inner.connect_calls == 3  # 2 failures + 1 success
    finally:
        rt.close()


def test_first_connect_totally_fails_raises_last_exception(fake_clock):
    """Case 3: all schedule values exhausted with inner always raising."""

    class Sentinel(RuntimeError):
        pass

    inner = FakeTransport()

    # Last-raised exception propagates. The schedule has 3 entries so
    # we expect exactly 3 connect attempts — the 3rd raises Sentinel so
    # we can assert it's the LAST exception that surfaces (not the 1st
    # or 2nd).
    schedule = (1.0, 2.0, 4.0)

    def failing_connect():
        inner.connect_calls += 1
        if inner.connect_calls == len(schedule):
            raise Sentinel("final")
        raise RuntimeError(f"early fail #{inner.connect_calls}")

    inner.connect = failing_connect  # type: ignore[assignment]

    rt = ReconnectingTransport(
        inner=inner,
        ping_interval_seconds=0.01,
        backoff_schedule_seconds=schedule,
    )
    with pytest.raises(Sentinel):
        rt.connect()
    # Exactly as many attempts as schedule entries.
    assert inner.connect_calls == 3


def test_mid_stream_disconnect_triggers_reconnect_and_hook(fake_clock):
    """Case 4: inner flips is_connected False, supervisor reconnects and hook fires."""
    inner = FakeTransport()
    hook_calls: List[int] = []

    rt = ReconnectingTransport(
        inner=inner,
        ping_interval_seconds=0.01,
        backoff_schedule_seconds=(0.1,),
        on_reconnect=lambda: hook_calls.append(1),
    )
    try:
        rt.connect()
        assert inner.connect_calls == 1

        # Drop the connection mid-stream.
        inner.is_connected = False
        # Wait for supervisor to observe the drop and reconnect.
        # It sleeps ping_interval first, then (on drop) close + connect.
        deadline = _REAL_MONOTONIC() + 2.0
        while _REAL_MONOTONIC() < deadline:
            if inner.connect_calls >= 2 and hook_calls:
                break
            _REAL_SLEEP(0.01)
        assert inner.connect_calls >= 2
        assert inner.close_calls >= 1  # supervisor closed defensively
        assert hook_calls == [1]
        assert rt.is_connected
    finally:
        rt.close()


def test_on_reconnect_hook_fires_after_connect_returns(fake_clock):
    """Case 5: hook is invoked AFTER inner.connect() returns, not during."""
    inner = FakeTransport()
    order: List[str] = []

    original_connect = inner.connect

    def tracked_connect():
        order.append("connect-start")
        original_connect()
        order.append("connect-end")

    inner.connect = tracked_connect  # type: ignore[assignment]

    def hook():
        order.append("hook")

    rt = ReconnectingTransport(
        inner=inner,
        ping_interval_seconds=0.01,
        on_reconnect=hook,
    )
    try:
        rt.connect()
        # Initial connect() MUST NOT fire the hook — hook is only for
        # RE-connects. (First connect is load-bearing on callers who want
        # to init their cache once from scratch.)
        assert "hook" not in order

        # Force reconnect.
        inner.is_connected = False
        deadline = _REAL_MONOTONIC() + 2.0
        while _REAL_MONOTONIC() < deadline:
            if "hook" in order:
                break
            _REAL_SLEEP(0.01)

        assert "hook" in order
        hook_idx = order.index("hook")
        # Most recent connect-end must precede the hook.
        prev_end_idx = max(
            i for i, tag in enumerate(order[:hook_idx]) if tag == "connect-end"
        )
        assert prev_end_idx < hook_idx
    finally:
        rt.close()


def test_exponential_backoff_on_mid_stream_disconnect(fake_clock):
    """Case 6: mid-stream disconnect with 3 failing reconnects uses 1s/2s/4s."""
    inner = FakeTransport()
    rt = ReconnectingTransport(
        inner=inner,
        ping_interval_seconds=0.01,
        backoff_schedule_seconds=(1.0, 2.0, 4.0, 8.0, 16.0),
    )
    try:
        rt.connect()
        # After the very first connect the supervisor starts poll-sleeping.
        # We want to observe the BACKOFF sleeps (1, 2, 4) specifically, not
        # the poll sleeps (0.01). Fail next 3 reconnect attempts, succeed on 4th.
        inner.fail_on_connect_count = 3
        inner.is_connected = False

        # Wait for reconnect attempts. After the 4th call, inner is connected.
        deadline = _REAL_MONOTONIC() + 3.0
        while _REAL_MONOTONIC() < deadline:
            if inner.connect_calls >= 4 and inner.is_connected:
                break
            _REAL_SLEEP(0.01)
        assert inner.connect_calls >= 4

        # Filter supervisor's ping sleeps out. We defined ping_interval as
        # 0.01 so any sleep >= 1.0 is a backoff sleep.
        backoff_sleeps = [s for s in fake_clock.sleeps if s >= 1.0]
        assert backoff_sleeps[:3] == [1.0, 2.0, 4.0]
    finally:
        rt.close()


def test_close_is_idempotent_and_joins_supervisor(fake_clock):
    """Case 7: close() is idempotent and the supervisor thread exits quickly."""
    inner = FakeTransport()
    rt = ReconnectingTransport(inner=inner, ping_interval_seconds=0.01)
    rt.connect()
    supervisor = rt._supervisor_thread
    assert supervisor is not None and supervisor.is_alive()

    rt.close()
    # Second close is a no-op.
    rt.close()

    # Supervisor must have exited within the 1s join.
    assert not supervisor.is_alive()
    assert inner.close_calls >= 1


def test_supervisor_does_not_reconnect_after_close(fake_clock):
    """Case 8: after close(), supervisor will not attempt further connects."""
    inner = FakeTransport()
    rt = ReconnectingTransport(inner=inner, ping_interval_seconds=0.01)
    rt.connect()
    connects_at_close = inner.connect_calls

    rt.close()
    # Simulate a late flip — should not matter; supervisor is gone.
    inner.is_connected = False
    _REAL_SLEEP(0.1)
    assert inner.connect_calls == connects_at_close


def test_on_reconnect_fires_exactly_once_per_successful_reconnect(fake_clock):
    """Case 9: hook is called once per successful reconnect (not per attempt)."""
    inner = FakeTransport()
    hook_calls: List[int] = []

    rt = ReconnectingTransport(
        inner=inner,
        ping_interval_seconds=0.01,
        backoff_schedule_seconds=(0.1, 0.1, 0.1),
        on_reconnect=lambda: hook_calls.append(1),
    )
    try:
        rt.connect()
        assert hook_calls == []  # initial connect does NOT fire hook

        # Make the reconnect take 2 failed attempts before succeeding.
        inner.fail_on_connect_count = 2
        inner.is_connected = False

        deadline = _REAL_MONOTONIC() + 3.0
        while _REAL_MONOTONIC() < deadline:
            if hook_calls:
                break
            _REAL_SLEEP(0.01)

        # Only ONE hook call, even though 2 attempts failed before success.
        assert hook_calls == [1]
    finally:
        rt.close()


def test_send_while_disconnected_raises(fake_clock):
    """Case 10a: send() while inner not connected surfaces inner's exception."""
    inner = FakeTransport()
    rt = ReconnectingTransport(inner=inner, ping_interval_seconds=0.01)
    try:
        rt.connect()
        inner.raise_on_send = RuntimeError("peer gone")
        with pytest.raises(RuntimeError, match="peer gone"):
            rt.send({"x": 1})
    finally:
        rt.close()


def test_receive_while_disconnected_returns_none_on_timeout(fake_clock):
    """Case 10b: receive() returns None when inner returns None (timeout)."""
    inner = FakeTransport(receive_value=None)
    rt = ReconnectingTransport(inner=inner, ping_interval_seconds=0.01)
    try:
        rt.connect()
        assert rt.receive(timeout=0.1) is None
    finally:
        rt.close()


def test_is_connected_reflects_inner(fake_clock):
    """is_connected mirrors inner.is_connected in real time."""
    inner = FakeTransport()
    rt = ReconnectingTransport(inner=inner, ping_interval_seconds=0.01)
    try:
        rt.connect()
        assert rt.is_connected
        inner.is_connected = False
        assert not rt.is_connected
    finally:
        rt.close()


def test_backoff_caps_at_last_value_and_keeps_trying(fake_clock):
    """Schedule exhaustion during MID-STREAM reconnect: sleep at last value
    forever, never give up (until close())."""
    inner = FakeTransport()
    rt = ReconnectingTransport(
        inner=inner,
        ping_interval_seconds=0.01,
        backoff_schedule_seconds=(1.0, 2.0),
    )
    try:
        rt.connect()
        # Force 5 failures on reconnect, then succeed. With schedule
        # (1, 2) we expect backoff sleeps 1, 2, 2, 2, 2 then success.
        inner.fail_on_connect_count = 5
        inner.is_connected = False

        deadline = _REAL_MONOTONIC() + 5.0
        while _REAL_MONOTONIC() < deadline:
            if inner.connect_calls >= 6 and inner.is_connected:
                break
            _REAL_SLEEP(0.01)
        assert inner.connect_calls >= 6

        backoff_sleeps = [s for s in fake_clock.sleeps if s >= 1.0]
        # First 5 backoff sleeps should be [1, 2, 2, 2, 2].
        assert backoff_sleeps[:5] == [1.0, 2.0, 2.0, 2.0, 2.0]
    finally:
        rt.close()
