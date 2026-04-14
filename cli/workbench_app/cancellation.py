"""Shared cancellation primitive for streaming slash commands.

T16 introduces a :class:`CancellationToken` that threads through the
workbench app loop and the four streaming runners (``/eval``, ``/optimize``,
``/build``, ``/deploy``). First ctrl-c press cancels the active tool call
(``token.cancel()`` — kills the subprocess, stops the iterator); second
press exits the app.

The token owns two pieces of state:

1. ``cancelled`` — monotonic flag set on first ``cancel()``. The streaming
   runners poll this between event reads so they can break out even when
   the subprocess hasn't produced output in a while.
2. ``active_processes`` — the set of registered :class:`subprocess.Popen`
   objects. ``cancel()`` sends SIGTERM, waits briefly, then SIGKILLs any
   survivors so we never leak orphan children.

The module is deliberately standalone (no imports from sibling
``workbench_app`` modules) so tests can exercise it without pulling in the
whole slash surface.
"""

from __future__ import annotations

import subprocess
import threading
from typing import Iterable


_DEFAULT_TERMINATE_GRACE = 0.5
"""Seconds to wait after SIGTERM before escalating to SIGKILL."""


class CancellationToken:
    """Thread-safe cancellation flag + subprocess registry.

    Instances are cheap to create and intended to live for the duration of
    a single slash-command invocation. The app loop owns one long-lived
    token and :meth:`reset` it between commands.
    """

    __slots__ = ("_cancelled", "_processes", "_lock", "_terminate_grace")

    def __init__(self, *, terminate_grace: float = _DEFAULT_TERMINATE_GRACE) -> None:
        self._cancelled = False
        self._processes: list[subprocess.Popen[str]] = []
        self._lock = threading.Lock()
        self._terminate_grace = terminate_grace

    # ------------------------------------------------------------------
    # Flag state.
    # ------------------------------------------------------------------

    @property
    def cancelled(self) -> bool:
        """True after :meth:`cancel` has been called at least once."""
        with self._lock:
            return self._cancelled

    @property
    def active(self) -> bool:
        """True when at least one subprocess is registered and unfinished."""
        with self._lock:
            return any(p.poll() is None for p in self._processes)

    # ------------------------------------------------------------------
    # Process registration.
    # ------------------------------------------------------------------

    def register_process(self, proc: subprocess.Popen[str]) -> None:
        """Track ``proc`` so :meth:`cancel` can terminate it.

        If the token is already cancelled, the process is killed immediately
        so a late-arriving subprocess (racy handler code) can't escape the
        cancellation window.
        """
        with self._lock:
            already_cancelled = self._cancelled
            self._processes.append(proc)
        if already_cancelled:
            _terminate(proc, self._terminate_grace)

    def unregister_process(self, proc: subprocess.Popen[str]) -> None:
        """Drop ``proc`` from the registry (best-effort; ignores missing)."""
        with self._lock:
            try:
                self._processes.remove(proc)
            except ValueError:
                pass

    # ------------------------------------------------------------------
    # Cancellation.
    # ------------------------------------------------------------------

    def cancel(self) -> None:
        """Set the cancelled flag and kill all registered subprocesses.

        Idempotent — subsequent calls are no-ops once the flag is set and
        the processes are gone.
        """
        with self._lock:
            if self._cancelled:
                procs: list[subprocess.Popen[str]] = []
            else:
                self._cancelled = True
                procs = list(self._processes)
        for proc in procs:
            _terminate(proc, self._terminate_grace)

    def reset(self) -> None:
        """Clear state between slash invocations.

        Called by the app loop when a new command starts so a prior
        cancellation doesn't poison the next run. Does **not** kill any
        still-registered processes — the previous handler's ``finally``
        clause owns that cleanup.
        """
        with self._lock:
            self._cancelled = False
            self._processes.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _terminate(proc: subprocess.Popen[str], grace: float) -> None:
    """Send SIGTERM then SIGKILL if the process doesn't exit in ``grace`` seconds.

    Swallows ``ProcessLookupError`` (already dead) and ``OSError`` so the
    token's cancel path is resilient to races.
    """
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
    except (ProcessLookupError, OSError):
        return
    try:
        proc.wait(timeout=grace)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        proc.kill()
    except (ProcessLookupError, OSError):
        return
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        pass


def iter_with_cancellation(
    stream: Iterable[object],
    token: CancellationToken,
) -> Iterable[object]:
    """Yield from ``stream`` until ``token.cancelled`` becomes True.

    Useful for draining an iterator produced by a stream runner that
    doesn't know about the token itself. The check happens *before* each
    yield, so a pending cancel takes effect as soon as the current read
    returns.
    """
    for item in stream:
        if token.cancelled:
            break
        yield item


__all__ = [
    "CancellationToken",
    "iter_with_cancellation",
]
