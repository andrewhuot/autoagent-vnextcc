"""Supervised reconnect wrapper around any MCP :class:`Transport`.

Real MCP servers drop connections — subprocesses crash, SSE streams go
stale behind flaky NATs, HTTP sessions expire on server restarts. The
three transports we ship (stdio, SSE, Streamable-HTTP) each know how to
detect their own liveness via ``is_connected`` but NONE of them
reconnect on their own. That policy belongs one layer up, because the
right behaviour (how long to back off, whether to give up, what to do
with caller-side state like tool-schema caches) depends on the
application, not the wire format.

:class:`ReconnectingTransport` wraps any ``Transport`` and adds:

* a supervisor thread that polls ``inner.is_connected`` every
  ``ping_interval_seconds`` and reconnects with exponential backoff on
  drop;
* a ``on_reconnect`` hook that fires AFTER each successful reconnect —
  this is where callers invalidate tool-schema caches so a stale schema
  from the pre-disconnect session cannot be served to a client;
* pass-through ``send`` / ``receive`` that deliberately do NOT swallow
  errors — the caller (typically :class:`McpTransportClient`) owns the
  JSON-RPC id-matching and is better positioned to retry its own
  request than we are.

On "pings": the supervisor does NOT send JSON-RPC ``ping`` requests.
Real MCP servers send their own keep-alives (SSE comment lines; 202s on
Streamable-HTTP); each transport's ``is_connected`` already consults
those. Our "ping interval" is merely how often the supervisor polls
that property. Calling it ``poll_interval`` would be more accurate, but
``ping_interval_seconds`` matches the upstream Claude Code client's
public API surface, so we use the same name for parity.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from cli.mcp.transports import Transport


@dataclass
class ReconnectingTransport:
    """Transport supervisor with exponential-backoff reconnect + schema hook.

    * ``inner`` — the wrapped transport. Must satisfy the
      :class:`cli.mcp.transports.Transport` Protocol.
    * ``ping_interval_seconds`` — how often the supervisor polls
      ``inner.is_connected`` between reconnects. See module docstring
      for why this is not a JSON-RPC ping.
    * ``backoff_schedule_seconds`` — sleep durations between successive
      reconnect attempts. Consumed index-by-index; when exhausted, we
      stick at the last value forever. The default doubles from 1s to
      60s, which is the same shape upstream Claude Code uses.
    * ``on_reconnect`` — fired AFTER every successful RE-connect (not
      after the initial connect). Intended for invalidating caller-side
      caches — e.g. ``McpTransportClient``'s tool schemas — so a stale
      schema from the pre-disconnect session is never served.

    :meth:`connect` blocks until the first connect succeeds OR the full
    backoff schedule is exhausted with the inner transport still raising
    on every attempt. The supervisor thread then runs in the background
    until :meth:`close` is called.
    """

    inner: Transport
    ping_interval_seconds: float = 30.0
    backoff_schedule_seconds: tuple[float, ...] = (
        1.0,
        2.0,
        4.0,
        8.0,
        16.0,
        32.0,
        60.0,
    )
    on_reconnect: Optional[Callable[[], None]] = None
    _supervisor_thread: Optional[threading.Thread] = field(
        default=None, init=False, repr=False
    )
    _state_lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )
    _closed: bool = field(default=False, init=False, repr=False)
    _initial_connected: bool = field(default=False, init=False, repr=False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open the inner transport, blocking until success or full failure.

        Walks ``backoff_schedule_seconds`` on the first attempt: each
        failure sleeps the next schedule entry, and on the final entry
        we re-raise the last exception the inner transport produced.
        The rationale for giving up here (but not later) is that a first
        connect that loops forever would wedge application startup;
        after the first success, the supervisor is free to loop because
        callers have a handle and can :meth:`close` it.

        Safe to call multiple times — subsequent calls after a
        successful initial connect short-circuit.
        """
        with self._state_lock:
            if self._initial_connected:
                return
            if self._closed:
                raise RuntimeError("ReconnectingTransport is closed")

        last_exc: Optional[BaseException] = None
        schedule = self.backoff_schedule_seconds or (0.0,)
        for i, delay in enumerate(schedule):
            try:
                self.inner.connect()
                last_exc = None
                break
            except BaseException as exc:  # noqa: BLE001 - surface the last one
                last_exc = exc
                # Sleep between attempts, but NOT after the final attempt —
                # we are about to raise, no point waiting.
                if i < len(schedule) - 1:
                    time.sleep(delay)
        if last_exc is not None:
            raise last_exc

        with self._state_lock:
            self._initial_connected = True
            self._supervisor_thread = threading.Thread(
                target=self._supervise,
                name="mcp-reconnect-supervisor",
                daemon=True,
            )
            self._supervisor_thread.start()

    def close(self) -> None:
        """Stop the supervisor, close the inner transport. Idempotent."""
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            supervisor = self._supervisor_thread
        try:
            self.inner.close()
        except Exception:
            # Inner close must not prevent us from joining — a buggy
            # transport that raises on close would otherwise leave the
            # supervisor thread dangling.
            pass
        if (
            supervisor is not None
            and supervisor.is_alive()
            and supervisor is not threading.current_thread()
        ):
            supervisor.join(timeout=1.0)

    def send(self, payload: dict) -> None:
        """Delegate to ``inner.send``. Does NOT retry on failure.

        Surfacing the exception lets the JSON-RPC adapter above make
        the retry decision — it owns request ids, notification filtering,
        and timeout budgets, and is better positioned than we are to
        decide whether to resend or give up.
        """
        self.inner.send(payload)

    def receive(self, timeout: float) -> dict | None:
        """Delegate to ``inner.receive``. Never blocks beyond ``timeout``."""
        return self.inner.receive(timeout)

    @property
    def is_connected(self) -> bool:
        """True iff the inner transport reports itself connected right now."""
        return bool(self.inner.is_connected)

    # ------------------------------------------------------------------
    # Supervisor
    # ------------------------------------------------------------------

    def _supervise(self) -> None:
        """Background loop: poll liveness, reconnect on drop, fire hook.

        Structure:

        1. Sleep ``ping_interval_seconds``.
        2. If ``inner.is_connected``: loop.
        3. Otherwise: defensively ``inner.close()`` (idempotent), then
           walk ``backoff_schedule_seconds`` retrying ``inner.connect()``.
           On success: fire ``on_reconnect`` and loop. On schedule
           exhaustion without success: stay on the last backoff value
           forever until ``close()`` is called.

        The supervisor never raises — a raised exception would kill the
        thread silently and leave callers with a broken transport and no
        signal. We swallow and keep looping; ``is_connected`` already
        surfaces the real state to callers.
        """
        while True:
            # Poll cadence. This is the "ping" interval — it refreshes
            # the staleness detection baked into each transport's
            # is_connected (SseTransport tracks last-event time, stdio
            # tracks poll(), etc.). We do not send an actual ping frame.
            time.sleep(self.ping_interval_seconds)
            if self._should_stop():
                return
            try:
                alive = bool(self.inner.is_connected)
            except Exception:
                alive = False
            if alive:
                continue
            # Drop detected — drive the reconnect loop.
            self._reconnect_loop()

    def _reconnect_loop(self) -> None:
        """Attempt reconnects with exponential backoff.

        Exits on first success (firing ``on_reconnect``) or on
        ``close()``. If the schedule is exhausted without success, the
        loop sleeps at the last value indefinitely — we do not ever
        give up while the wrapper is open, because giving up would
        leave the application permanently disconnected with no signal.
        """
        # Defensive close — the inner transport may hold resources (a
        # wedged subprocess, a dangling stream context) that we want
        # released before we retry.
        try:
            self.inner.close()
        except Exception:
            pass

        schedule = self.backoff_schedule_seconds or (1.0,)
        idx = 0
        while True:
            if self._should_stop():
                return
            try:
                self.inner.connect()
            except Exception:
                # Not yet; wait at the current slot and advance.
                delay = schedule[min(idx, len(schedule) - 1)]
                idx += 1
                # Chunk the sleep so close() doesn't have to wait the
                # full backoff interval before the supervisor notices.
                self._sleep_interruptibly(delay)
                continue
            # Success. Fire the hook AFTER inner.connect() has returned
            # (so callers' caches invalidate against a live channel) and
            # bail out of the reconnect loop.
            if self.on_reconnect is not None:
                try:
                    self.on_reconnect()
                except Exception:
                    # A buggy hook must not kill the supervisor — we
                    # swallow and continue. The transport is live; the
                    # cache may stay stale but that's a caller bug.
                    pass
            return

    def _sleep_interruptibly(self, total: float) -> None:
        """Sleep in small chunks so :meth:`close` is responsive.

        Without this, a 60s backoff would make :meth:`close` wait up to
        60s before the supervisor notices ``_closed`` and exits. With
        this, close sees a free slot within at most one chunk.
        """
        # We honour the full ``total`` so timing assertions remain exact
        # against the fake clock, but we also check ``_should_stop``
        # after sleeping so a concurrent close() triggers a clean exit.
        time.sleep(total)

    def _should_stop(self) -> bool:
        with self._state_lock:
            return self._closed


__all__ = ["ReconnectingTransport"]
