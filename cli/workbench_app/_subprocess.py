"""Shared streaming-subprocess helper for slash runners.

The four streaming slash commands (``/eval``, ``/optimize``, ``/build``,
``/deploy``) each used to own a near-identical ``_default_stream_runner``:
``subprocess.Popen`` with a line-buffered text pipe, a ``for raw in
proc.stdout`` reader, JSON parsing with a synthetic ``warning`` fallback
for malformed lines, and an exit-code → domain-error translation.

Three problems with copy-paste:

1. **No stall detection.** A hung provider (network wedged, LLM rate
   limited, child process deadlocked) would keep the CLI at the spinner
   indefinitely — users had to ctrl-c and re-run.
2. **Error messages were identical across commands**, so operators had
   nothing to tell apart "exited 1" from "stalled after 90s" in logs.
3. **No output tail in errors.** When the child exited non-zero the
   handler printed ``"/build failed: workbench build exited with status 2"``
   with no clue about what stderr said.

:func:`stream_subprocess` addresses all three. The public-facing rule:
*every* streaming slash runner should delegate through this helper so the
stall-timeout behavior is uniform across commands.

Design notes
------------

- Stall detection uses a background reader thread that pushes lines onto a
  :class:`queue.Queue`. The main iterator waits on ``queue.get(timeout=…)``;
  if the wait expires without a line the subprocess is killed and the
  caller sees a :class:`SubprocessStreamError` with ``kind="stalled"``.
  (``select.select`` on a pipe is POSIX-only; the thread+queue combo works
  on Windows too, which matters if anyone ships workbench there later.)
- ``on_nonjson`` is injected because the four runners use slightly different
  synthetic envelopes — ``/eval``, ``/optimize``, ``/deploy`` emit flat
  ``{"event": "warning", "message": …}`` while ``/build`` nests under
  ``"data"`` because workbench stream-json events are nested. Keeping the
  envelope shape out of the helper means we don't leak runner quirks here.
- ``error_factory`` is the escape hatch for runners that want to keep
  raising their own error class (``EvalCommandError`` etc.) so handler
  code outside this module can keep its ``except EvalCommandError:`` catch.
- The ``tail`` we attach to errors is the last :data:`_TAIL_MAX` raw
  stdout lines (stripped). That's enough to include the final traceback /
  Click usage error without blowing up the handler's echo output.
"""

from __future__ import annotations

import json
import queue
import subprocess
import threading
from collections import deque
from typing import Any, Callable, Iterator, Sequence

from cli.workbench_app.cancellation import CancellationToken


StreamEvent = dict[str, Any]
"""One JSON event emitted by a stream-json subprocess."""

PopenFactory = Callable[[Sequence[str]], "subprocess.Popen[str]"]
"""Build a :class:`subprocess.Popen` from the command list.

Tests inject a fake Popen so they never spawn a real child process; the
default :func:`_default_popen_factory` matches the shape each runner used
before the refactor (line-buffered text, stderr merged into stdout).
"""

NonJsonFactory = Callable[[str], StreamEvent]
"""Build a synthetic event for a line that failed JSON parsing.

Each runner picks its own envelope shape (``/build`` nests under ``data``,
the others use flat ``message``), so this is pluggable.
"""

ErrorFactory = Callable[[str, str, tuple[str, ...], "int | None"], Exception]
"""Translate a helper error into the runner's domain-specific exception.

Signature: ``(kind, message, tail, exit_code) -> Exception``. ``kind`` is
``"stalled"`` or ``"nonzero"``. When omitted, the helper raises
:class:`SubprocessStreamError` directly.
"""


DEFAULT_STALL_TIMEOUT_S = 90.0
"""Default seconds between lines before declaring a subprocess stalled."""

_TAIL_MAX = 10
"""Number of trailing stdout lines to preserve on failure for diagnostics."""

_EOF = object()
"""Sentinel pushed onto the reader queue when the child's stdout closes."""


class SubprocessStreamError(RuntimeError):
    """Raised by :func:`stream_subprocess` on stall or non-zero exit.

    Runners typically catch this and re-raise as their domain error
    (``EvalCommandError`` etc.) using the ``error_factory`` seam so handler
    code can keep its existing ``except`` clauses. The attributes are
    preserved on the wrapped error via ``raise … from exc`` so diagnostics
    aren't lost.
    """

    def __init__(
        self,
        message: str,
        *,
        kind: str,
        exit_code: int | None,
        tail: tuple[str, ...],
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.exit_code = exit_code
        self.tail = tail


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def _default_popen_factory(cmd: Sequence[str]) -> "subprocess.Popen[str]":
    """Match the Popen shape every slash runner used pre-refactor."""
    return subprocess.Popen(
        list(cmd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )


def _default_on_nonjson(line: str) -> StreamEvent:
    """Flat ``warning`` envelope — matches ``/eval``, ``/optimize``, ``/deploy``."""
    return {"event": "warning", "message": line}


# ---------------------------------------------------------------------------
# Public helper
# ---------------------------------------------------------------------------


def stream_subprocess(
    cmd: Sequence[str],
    *,
    stall_timeout_s: float = DEFAULT_STALL_TIMEOUT_S,
    cancellation: CancellationToken | None = None,
    popen_factory: PopenFactory = _default_popen_factory,
    on_nonjson: NonJsonFactory = _default_on_nonjson,
    error_factory: ErrorFactory | None = None,
) -> Iterator[StreamEvent]:
    """Spawn ``cmd`` and yield parsed JSON events with stall-timeout detection.

    Parameters
    ----------
    cmd:
        The full argv list, including interpreter + module flags (e.g.
        ``[sys.executable, "-m", "runner", "eval", "run", ...]``).
    stall_timeout_s:
        Seconds without a new line before the process is considered stalled
        and killed. Defaults to :data:`DEFAULT_STALL_TIMEOUT_S` (90s). Tests
        pass a small value (~0.15s) to keep the suite fast.
    cancellation:
        Optional :class:`CancellationToken`. When present, the subprocess is
        registered so app-level ctrl-c tears it down, and a cancelled token
        suppresses the post-exit error translation (exit code 143 from our
        own SIGTERM is expected, not a user-visible failure).
    popen_factory:
        Injectable seam for tests. Defaults to :func:`_default_popen_factory`.
    on_nonjson:
        Builder for synthetic events when a line fails JSON parsing. Each
        runner picks its own envelope shape.
    error_factory:
        Optional translator that wraps stall / non-zero errors into the
        runner's domain exception class. When omitted, the helper raises
        :class:`SubprocessStreamError` directly.
    """
    proc = popen_factory(cmd)
    if cancellation is not None:
        cancellation.register_process(proc)
    assert proc.stdout is not None

    line_queue: "queue.Queue[object]" = queue.Queue()
    tail: deque[str] = deque(maxlen=_TAIL_MAX)

    def _reader() -> None:
        try:
            for raw in proc.stdout:  # type: ignore[union-attr]
                line_queue.put(raw)
        except Exception:
            # Reader errors (pipe closed mid-read, etc.) surface as EOF —
            # the main loop will see exit_code via proc.wait() and raise
            # if that's abnormal.
            pass
        finally:
            line_queue.put(_EOF)

    reader_thread = threading.Thread(
        target=_reader, name="stream-subprocess-reader", daemon=True
    )
    reader_thread.start()

    stalled = False
    try:
        while True:
            if cancellation is not None and cancellation.cancelled:
                break
            try:
                item = line_queue.get(timeout=stall_timeout_s)
            except queue.Empty:
                # No line for the whole window. If a cancellation raced in
                # while we were waiting, honor that instead of flagging a
                # stall — the subprocess is being killed deliberately.
                if cancellation is not None and cancellation.cancelled:
                    break
                stalled = True
                break
            if item is _EOF:
                break
            raw = item if isinstance(item, str) else ""
            line = raw.strip()
            if not line:
                continue
            tail.append(line)
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                yield on_nonjson(line)

        if stalled:
            _kill(proc)
            message = f"no output for {stall_timeout_s:.0f}s — run stalled"
            raise _build_error(
                error_factory,
                kind="stalled",
                exit_code=None,
                message=message,
                tail=tuple(tail),
            )

        # Drain whatever exit status the child produced. If we got here
        # without stalling or cancelling, ``_EOF`` means stdout closed, so
        # ``wait()`` should return promptly.
        exit_code = proc.wait()
        cancel_suppressed = cancellation is not None and cancellation.cancelled
        if exit_code != 0 and not cancel_suppressed:
            message = f"exited with status {exit_code}"
            raise _build_error(
                error_factory,
                kind="nonzero",
                exit_code=exit_code,
                message=_with_tail(message, tail),
                tail=tuple(tail),
            )
    finally:
        # Always leave the subprocess dead and deregistered — even if the
        # caller abandoned iteration mid-stream (generator .close()).
        if proc.poll() is None:
            _kill(proc)
        if cancellation is not None:
            cancellation.unregister_process(proc)
        # Let the reader thread flush; it's daemonized so we don't block
        # shutdown forever if the child ignored SIGKILL.
        reader_thread.join(timeout=1.0)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _kill(proc: "subprocess.Popen[str]") -> None:
    """Best-effort kill with a short wait so ``finally`` can proceed."""
    try:
        proc.kill()
    except (ProcessLookupError, OSError):
        return
    try:
        proc.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        pass


def _with_tail(message: str, tail: "deque[str]") -> str:
    """Append the last stdout line(s) to ``message`` for diagnostics."""
    if not tail:
        return message
    last = tail[-1]
    # One line is usually enough — keep the error message compact so the
    # handler can echo it on a single row without wrapping the terminal.
    return f"{message} (last output: {last})"


def _build_error(
    factory: ErrorFactory | None,
    *,
    kind: str,
    exit_code: int | None,
    message: str,
    tail: tuple[str, ...],
) -> Exception:
    """Delegate to ``factory`` when present, else raise the generic error."""
    if factory is None:
        return SubprocessStreamError(
            message, kind=kind, exit_code=exit_code, tail=tail
        )
    return factory(kind, message, tail, exit_code)


__all__ = [
    "DEFAULT_STALL_TIMEOUT_S",
    "ErrorFactory",
    "NonJsonFactory",
    "PopenFactory",
    "StreamEvent",
    "SubprocessStreamError",
    "stream_subprocess",
]
