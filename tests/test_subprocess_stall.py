"""Tests for :func:`cli.workbench_app._subprocess.stream_subprocess`.

Chunk 3 of the Claude-Code-UX refactor factors the stream-json subprocess
loop that the four slash runners (``/eval``, ``/optimize``, ``/build``,
``/deploy``) have been copy-pasting into one helper. The new helper adds a
stall timeout so a hung provider can no longer wedge the CLI forever, and
preserves the last few output lines for diagnostics.

These tests pin down the invariants:

1. Happy path — valid JSON lines round-trip through as stream events.
2. Non-JSON lines go through the caller-supplied ``on_nonjson`` factory
   (each runner needs a slightly different envelope shape).
3. Non-zero exit raises ``SubprocessStreamError`` with ``kind="nonzero"``
   and the tail of stdout attached.
4. A subprocess that produces no output within ``stall_timeout_s`` raises
   ``SubprocessStreamError`` with ``kind="stalled"`` and kills the process.
5. ``CancellationToken.cancel()`` breaks out of the loop cleanly and does
   not raise, even if the subprocess would otherwise stall.
6. A cancelled token registered before the helper runs short-circuits
   cleanly — no lingering threads or unraised errors.
"""

from __future__ import annotations

import subprocess
import threading
import time
from typing import Iterable, Iterator, Sequence

import pytest

from cli.workbench_app._subprocess import (
    SubprocessStreamError,
    stream_subprocess,
)
from cli.workbench_app.cancellation import CancellationToken


class _FakePopen:
    """Minimal :class:`subprocess.Popen` stand-in for the stream loop.

    The helper's reader thread iterates ``proc.stdout`` line by line and
    calls ``proc.poll`` / ``proc.wait`` / ``proc.kill`` to manage lifecycle.
    This fake supports all of that without spawning a real child process.
    """

    def __init__(
        self,
        lines: Sequence[str] = (),
        *,
        exit_code: int = 0,
        hang_after_lines: bool = False,
    ) -> None:
        self._lines = list(lines)
        self._exit_code = exit_code
        self._hang_after_lines = hang_after_lines
        self._killed = threading.Event()
        self._finished = threading.Event()
        self.stdout = self  # iterable line source
        self.kill_count = 0
        self.terminate_count = 0

    # --- iteration (simulates reading proc.stdout line by line) ---------
    def __iter__(self) -> Iterator[str]:
        for line in self._lines:
            if self._killed.is_set():
                break
            yield line
        if self._hang_after_lines:
            # Block forever until the helper kills us.
            self._killed.wait()
        self._finished.set()

    # --- Popen lifecycle surface ----------------------------------------
    def poll(self) -> int | None:
        if self._killed.is_set() or self._finished.is_set():
            return self._exit_code
        if self._hang_after_lines:
            return None
        return self._exit_code

    def wait(self, timeout: float | None = None) -> int:
        if self._hang_after_lines:
            if timeout is not None:
                if not self._killed.wait(timeout=timeout):
                    raise subprocess.TimeoutExpired(cmd="fake", timeout=timeout)
            else:
                self._killed.wait()
        return self._exit_code

    def kill(self) -> None:
        self.kill_count += 1
        self._killed.set()

    def terminate(self) -> None:
        self.terminate_count += 1
        self._killed.set()


def _popen_factory(fake: _FakePopen):
    def _factory(_cmd: Sequence[str]):
        return fake
    return _factory


def _drain(stream: Iterable[dict]) -> list[dict]:
    return list(stream)


# ---------------------------------------------------------------------------
# Happy path / envelope handling
# ---------------------------------------------------------------------------


def test_stream_subprocess_yields_valid_json_events() -> None:
    """Valid JSON lines are parsed into dicts and yielded in order."""
    fake = _FakePopen([
        '{"event": "phase_started", "phase": "loading"}\n',
        '{"event": "phase_completed", "phase": "loading"}\n',
    ])
    events = _drain(stream_subprocess(["fake"], popen_factory=_popen_factory(fake)))

    assert [e["event"] for e in events] == ["phase_started", "phase_completed"]


def test_stream_subprocess_uses_on_nonjson_factory_for_bad_lines() -> None:
    """Malformed JSON goes through the caller's envelope factory."""
    fake = _FakePopen([
        "this is not json\n",
        '{"event": "ok"}\n',
    ])

    def envelope(line: str) -> dict:
        return {"event": "warning", "data": {"message": line}}

    events = _drain(
        stream_subprocess(
            ["fake"],
            popen_factory=_popen_factory(fake),
            on_nonjson=envelope,
        )
    )
    assert events[0] == {"event": "warning", "data": {"message": "this is not json"}}
    assert events[1] == {"event": "ok"}


def test_stream_subprocess_skips_blank_lines() -> None:
    """Blank lines are dropped without being dispatched to ``on_nonjson``."""
    calls: list[str] = []

    def envelope(line: str) -> dict:
        calls.append(line)
        return {"event": "warning", "message": line}

    fake = _FakePopen([
        "\n",
        "   \n",
        '{"event": "ok"}\n',
    ])
    events = _drain(
        stream_subprocess(
            ["fake"],
            popen_factory=_popen_factory(fake),
            on_nonjson=envelope,
        )
    )
    assert calls == []
    assert events == [{"event": "ok"}]


# ---------------------------------------------------------------------------
# Exit-code handling
# ---------------------------------------------------------------------------


def test_stream_subprocess_raises_on_nonzero_exit() -> None:
    """Non-zero exit after clean iteration raises ``SubprocessStreamError``."""
    fake = _FakePopen(
        ['{"event": "ok"}\n', "stderr-line-1\n", "stderr-line-2\n"],
        exit_code=2,
    )
    with pytest.raises(SubprocessStreamError) as excinfo:
        _drain(stream_subprocess(["fake"], popen_factory=_popen_factory(fake)))

    err = excinfo.value
    assert err.kind == "nonzero"
    assert err.exit_code == 2
    assert "exited" in str(err).lower()
    # The last few stdout lines are preserved for diagnostics.
    assert "stderr-line-2" in err.tail or any(
        "stderr-line-2" in line for line in err.tail
    )


def test_stream_subprocess_zero_exit_does_not_raise() -> None:
    """Exit code 0 produces a clean EOF with no error."""
    fake = _FakePopen(['{"event": "ok"}\n'], exit_code=0)
    events = _drain(stream_subprocess(["fake"], popen_factory=_popen_factory(fake)))
    assert events == [{"event": "ok"}]


# ---------------------------------------------------------------------------
# Stall detection
# ---------------------------------------------------------------------------


def test_stream_subprocess_raises_on_stall() -> None:
    """A subprocess producing no output inside the window is killed + raised."""
    fake = _FakePopen(hang_after_lines=True)

    start = time.monotonic()
    with pytest.raises(SubprocessStreamError) as excinfo:
        _drain(
            stream_subprocess(
                ["fake"],
                popen_factory=_popen_factory(fake),
                stall_timeout_s=0.15,
            )
        )
    elapsed = time.monotonic() - start

    err = excinfo.value
    assert err.kind == "stalled"
    assert "stalled" in str(err).lower()
    # Should complete within a small multiple of the configured timeout.
    assert elapsed < 1.5, f"stall detection too slow: {elapsed:.2f}s"
    # Helper must kill the subprocess on stall so we don't leak orphans.
    assert fake.kill_count + fake.terminate_count > 0


def test_stream_subprocess_stall_preserves_tail() -> None:
    """Stall errors still carry the tail from whatever output arrived first."""
    fake = _FakePopen(
        [
            '{"event": "phase_started", "phase": "loading"}\n',
            "some-stderr-line\n",
        ],
        hang_after_lines=True,
    )
    with pytest.raises(SubprocessStreamError) as excinfo:
        _drain(
            stream_subprocess(
                ["fake"],
                popen_factory=_popen_factory(fake),
                stall_timeout_s=0.15,
            )
        )
    assert excinfo.value.tail  # non-empty
    assert any("some-stderr-line" in line for line in excinfo.value.tail)


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


def test_stream_subprocess_breaks_out_on_cancellation() -> None:
    """Cancellation breaks the loop cleanly without raising a stall error."""
    fake = _FakePopen(hang_after_lines=True)
    token = CancellationToken()

    def _cancel_soon() -> None:
        time.sleep(0.05)
        token.cancel()

    threading.Thread(target=_cancel_soon, daemon=True).start()

    # Long stall timeout — the test must exit via cancellation, not timeout.
    events = _drain(
        stream_subprocess(
            ["fake"],
            popen_factory=_popen_factory(fake),
            stall_timeout_s=5.0,
            cancellation=token,
        )
    )
    assert events == []
    assert token.cancelled is True


def test_stream_subprocess_cancelled_before_nonzero_exit_is_silent() -> None:
    """A non-zero exit caused by our own ``cancel()`` must not raise."""
    fake = _FakePopen(
        ['{"event": "phase_started", "phase": "loading"}\n'],
        exit_code=143,  # conventional SIGTERM exit
        hang_after_lines=True,
    )
    token = CancellationToken()

    def _cancel_soon() -> None:
        time.sleep(0.05)
        token.cancel()

    threading.Thread(target=_cancel_soon, daemon=True).start()

    # No exception expected: the helper sees the cancellation flag set and
    # suppresses the post-exit error translation.
    events = _drain(
        stream_subprocess(
            ["fake"],
            popen_factory=_popen_factory(fake),
            stall_timeout_s=5.0,
            cancellation=token,
        )
    )
    # First line might or might not arrive before cancellation fires; both
    # outcomes are acceptable as long as nothing is raised.
    for event in events:
        assert isinstance(event, dict)


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------


def test_stream_subprocess_error_factory_translates_kind() -> None:
    """``error_factory`` lets runners wrap the helper's errors as their own."""

    class DomainError(RuntimeError):
        pass

    def translate(kind: str, message: str, tail: tuple[str, ...], exit_code: int | None) -> Exception:
        return DomainError(f"[{kind}/{exit_code}] {message}")

    fake = _FakePopen([], exit_code=7)
    with pytest.raises(DomainError) as excinfo:
        _drain(
            stream_subprocess(
                ["fake"],
                popen_factory=_popen_factory(fake),
                error_factory=translate,
            )
        )
    assert "nonzero/7" in str(excinfo.value)
