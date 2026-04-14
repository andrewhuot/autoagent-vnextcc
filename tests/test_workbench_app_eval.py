"""Integration tests for ``/eval`` end-to-end through the real subprocess runner.

Sister file to :mod:`tests.test_workbench_eval_slash` — that suite unit-tests the
handler against a fake :data:`StreamRunner` callable. This module covers the
step up the stack: drives ``/eval`` through :func:`dispatch` with the *real*
:func:`_default_stream_runner`, and replaces :class:`subprocess.Popen` with a
stub that emits pre-baked stream-json lines on stdout. The point is to verify
the wire-up between the subprocess reader, the event parser,
:func:`format_workbench_event`, and the transcript — the glue no unit test
exercises in isolation.

Scope: runner wiring → parser → renderer → transcript. Out of scope: argument
parsing (covered by the unit file) and the :class:`CancellationToken` branch
(covered by ``test_workbench_cancellation``).
"""

from __future__ import annotations

import json
import re
import subprocess
from typing import Iterable, Iterator, Sequence

import pytest

from cli.workbench_app import eval_slash
from cli.workbench_app.commands import CommandRegistry
from cli.workbench_app.eval_slash import build_eval_command
from cli.workbench_app.slash import DispatchResult, SlashContext, dispatch


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


class _EchoCapture:
    """Collects transcript lines for assertion."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, line: str) -> None:
        self.lines.append(line)

    @property
    def plain(self) -> list[str]:
        return [_strip_ansi(l) for l in self.lines]

    @property
    def plain_joined(self) -> str:
        return "\n".join(self.plain)


class _FakePopen:
    """Stand-in for :class:`subprocess.Popen` that emits stream-json lines.

    Real ``_default_stream_runner`` reads ``proc.stdout`` line-by-line, calls
    ``proc.wait()`` for the exit code, and probes ``proc.poll()`` in the
    finally block. We mimic each of those hooks so the runner walks its real
    code path without touching an actual process.
    """

    instances: list["_FakePopen"] = []

    def __init__(
        self,
        cmd: Sequence[str],
        *,
        stdout: object = None,
        stderr: object = None,
        text: bool = False,
        bufsize: int = 0,
    ) -> None:
        self.cmd = list(cmd)
        self.stdout_lines = list(self._pending_lines)
        self.exit_code = self._pending_exit_code
        self._poll_returns_none = True
        # stdout behaves like an iterator of strings — mimics text-mode Popen.
        self.stdout = iter(self.stdout_lines)
        self.stderr = None
        self.kill_calls = 0
        self.wait_calls = 0
        _FakePopen.instances.append(self)

    # --- configuration ------------------------------------------------------

    _pending_lines: list[str] = []
    _pending_exit_code: int = 0

    @classmethod
    def configure(
        cls, *, events: Iterable[dict] | None = None, exit_code: int = 0,
        raw_lines: Iterable[str] | None = None,
    ) -> None:
        """Seed the next :class:`_FakePopen` instance(s)."""
        if raw_lines is not None:
            cls._pending_lines = list(raw_lines)
        else:
            assert events is not None, "pass events= or raw_lines="
            cls._pending_lines = [json.dumps(e) + "\n" for e in events]
        cls._pending_exit_code = exit_code
        cls.instances = []

    # --- Popen API ----------------------------------------------------------

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
        self._poll_returns_none = False
        return self.exit_code

    def poll(self) -> int | None:
        return None if self._poll_returns_none else self.exit_code

    def kill(self) -> None:  # pragma: no cover — not reached in happy path
        self.kill_calls += 1
        self._poll_returns_none = False


@pytest.fixture
def patch_popen(monkeypatch: pytest.MonkeyPatch) -> type[_FakePopen]:
    """Replace ``subprocess.Popen`` *in eval_slash* with the fake."""
    monkeypatch.setattr(eval_slash.subprocess, "Popen", _FakePopen)
    return _FakePopen


@pytest.fixture
def ctx() -> tuple[SlashContext, _EchoCapture]:
    echo = _EchoCapture()
    registry = CommandRegistry()
    # Register a *real* eval command — no runner override, so dispatch uses
    # the default `_default_stream_runner` which in turn uses our patched
    # ``Popen``. This is the integration-test point.
    registry.register(build_eval_command())
    return SlashContext(echo=echo, registry=registry), echo


# ---------------------------------------------------------------------------
# Happy path — real runner + mocked subprocess
# ---------------------------------------------------------------------------


def test_eval_streams_subprocess_stdout_to_transcript(
    patch_popen: type[_FakePopen],
    ctx: tuple[SlashContext, _EchoCapture],
) -> None:
    slash_ctx, echo = ctx
    patch_popen.configure(
        events=[
            {"event": "phase_started", "phase": "eval", "message": "boot"},
            {"event": "phase_completed", "phase": "eval", "message": "ok"},
            {"event": "artifact_written", "artifact": "run", "path": "/tmp/r.json"},
            {"event": "next_action", "message": "agentlab optimize"},
        ],
    )

    result = dispatch(slash_ctx, "/eval")

    assert isinstance(result, DispatchResult)
    assert result.handled is True
    assert result.error is None
    plain = echo.plain_joined
    assert "/eval starting" in plain
    assert "[eval] starting: boot" in plain
    assert "[eval] done: ok" in plain
    assert "/tmp/r.json" in plain
    assert "/eval complete" in plain
    # Summary meta lines (last three artifacts + next_action) surface via the
    # dispatcher's meta-message echo.
    meta_strs = [_strip_ansi(m) for m in result.meta_messages]
    assert any(m.startswith("Suggested next:") for m in meta_strs)
    assert any("/tmp/r.json" in m for m in meta_strs)


def test_eval_spawns_subprocess_with_stream_json_flag(
    patch_popen: type[_FakePopen],
    ctx: tuple[SlashContext, _EchoCapture],
) -> None:
    """The runner must launch ``runner eval run --output-format stream-json``."""
    slash_ctx, _ = ctx
    patch_popen.configure(events=[])

    dispatch(slash_ctx, "/eval --category safety")

    assert len(patch_popen.instances) == 1
    cmd = patch_popen.instances[0].cmd
    # ``python -m runner eval run --output-format stream-json --category safety``
    assert cmd[1:6] == ["-m", "runner", "eval", "run", "--output-format"]
    assert cmd[6] == "stream-json"
    assert cmd[-2:] == ["--category", "safety"]


def test_eval_forwards_run_id_as_config(
    patch_popen: type[_FakePopen],
    ctx: tuple[SlashContext, _EchoCapture],
) -> None:
    slash_ctx, _ = ctx
    patch_popen.configure(events=[])

    dispatch(slash_ctx, "/eval --run-id v012")

    cmd = patch_popen.instances[0].cmd
    assert cmd[-2:] == ["--config", "v012"]
    # The ``--run-id`` alias must not leak into the subprocess call.
    assert "--run-id" not in cmd


def test_eval_skips_blank_subprocess_lines(
    patch_popen: type[_FakePopen],
    ctx: tuple[SlashContext, _EchoCapture],
) -> None:
    """Blank stdout lines from the child must not break the JSON parser."""
    slash_ctx, echo = ctx
    patch_popen.configure(
        raw_lines=[
            "\n",
            json.dumps({"event": "phase_started", "phase": "eval"}) + "\n",
            "\n",
            json.dumps({"event": "phase_completed", "phase": "eval"}) + "\n",
        ],
    )

    result = dispatch(slash_ctx, "/eval")

    assert isinstance(result, DispatchResult)
    plain = echo.plain_joined
    assert "[eval] starting" in plain
    assert "[eval] done" in plain
    assert "/eval complete" in plain


def test_eval_non_json_output_surfaces_as_warning(
    patch_popen: type[_FakePopen],
    ctx: tuple[SlashContext, _EchoCapture],
) -> None:
    """A child that prints non-JSON (e.g. a naked warning) is rescued.

    The runner wraps such lines as synthetic ``warning`` events so they show
    up in the transcript instead of vanishing.
    """
    slash_ctx, echo = ctx
    patch_popen.configure(
        raw_lines=[
            "legacy log line about fs\n",
            json.dumps({"event": "phase_completed", "phase": "eval"}) + "\n",
        ],
    )

    result = dispatch(slash_ctx, "/eval")

    plain = echo.plain_joined
    assert "[warning] legacy log line about fs" in plain
    assert "1 warnings" in plain
    assert isinstance(result, DispatchResult)


# ---------------------------------------------------------------------------
# Failure path — non-zero exit
# ---------------------------------------------------------------------------


def test_eval_non_zero_exit_raises_command_error_and_reports_failure(
    patch_popen: type[_FakePopen],
    ctx: tuple[SlashContext, _EchoCapture],
) -> None:
    slash_ctx, echo = ctx
    patch_popen.configure(
        events=[{"event": "phase_started", "phase": "eval"}],
        exit_code=2,
    )

    result = dispatch(slash_ctx, "/eval")

    # Handler catches EvalCommandError internally and echoes a red failure
    # line; the dispatcher receives a clean DispatchResult (no error).
    assert isinstance(result, DispatchResult)
    assert result.error is None
    assert result.display == "skip"
    assert any("/eval failed" in _strip_ansi(l) for l in echo.lines)
    assert result.raw_result is not None
    assert "exit 2" in _strip_ansi(result.raw_result) or "status 2" in _strip_ansi(
        result.raw_result
    )


def test_eval_error_event_produces_failed_summary_despite_clean_exit(
    patch_popen: type[_FakePopen],
    ctx: tuple[SlashContext, _EchoCapture],
) -> None:
    """An ``error`` event in-stream flips the summary to red even on exit 0."""
    slash_ctx, echo = ctx
    patch_popen.configure(
        events=[
            {"event": "phase_started", "phase": "eval"},
            {"event": "error", "message": "judge timeout"},
            {"event": "phase_completed", "phase": "eval"},
        ],
        exit_code=0,
    )

    result = dispatch(slash_ctx, "/eval")

    plain = echo.plain_joined
    assert "/eval failed" in plain
    assert "1 errors" in plain
    assert isinstance(result, DispatchResult)


def test_eval_missing_binary_handled_gracefully(
    monkeypatch: pytest.MonkeyPatch,
    ctx: tuple[SlashContext, _EchoCapture],
) -> None:
    """``FileNotFoundError`` from Popen becomes a red failure line + skip."""
    slash_ctx, echo = ctx

    def _boom(*a: object, **kw: object) -> None:
        raise FileNotFoundError("python")

    monkeypatch.setattr(eval_slash.subprocess, "Popen", _boom)

    result = dispatch(slash_ctx, "/eval")

    assert isinstance(result, DispatchResult)
    assert result.display == "skip"
    assert result.raw_result is None
    assert any("/eval failed" in _strip_ansi(l) for l in echo.lines)


# ---------------------------------------------------------------------------
# Cleanup — no orphan processes left behind
# ---------------------------------------------------------------------------


def test_eval_leaves_no_alive_subprocess_behind(
    patch_popen: type[_FakePopen],
    ctx: tuple[SlashContext, _EchoCapture],
) -> None:
    """After a clean run, the fake Popen reports no outstanding child."""
    slash_ctx, _ = ctx
    patch_popen.configure(
        events=[{"event": "phase_completed", "phase": "eval"}],
    )

    dispatch(slash_ctx, "/eval")

    assert len(patch_popen.instances) == 1
    proc = patch_popen.instances[0]
    assert proc.wait_calls == 1  # runner awaited the exit code
    assert proc.kill_calls == 0  # clean shutdown, no force-kill
    assert proc.poll() == 0  # finally-block probe sees terminated child


# ---------------------------------------------------------------------------
# Synthesized lines — runner contract sanity
# ---------------------------------------------------------------------------


def test_eval_default_runner_iterates_full_stdout(
    patch_popen: type[_FakePopen],
) -> None:
    """Drive the runner directly (no dispatcher) to pin its contract.

    The runner is a generator: it must yield one parsed dict per stdout line
    until the pipe is exhausted, then let the caller consume exit-code
    handling. Iterating to completion here confirms there's no accidental
    early-return.
    """
    patch_popen.configure(
        events=[
            {"event": "phase_started", "phase": "eval"},
            {"event": "phase_completed", "phase": "eval"},
        ],
    )

    results: list[dict] = list(eval_slash._default_stream_runner(["--noop"]))

    assert [e["event"] for e in results] == ["phase_started", "phase_completed"]


def test_eval_default_runner_raises_on_nonzero_exit(
    patch_popen: type[_FakePopen],
) -> None:
    patch_popen.configure(events=[], exit_code=5)
    stream: Iterator[dict] = eval_slash._default_stream_runner(["--x"])

    with pytest.raises(eval_slash.EvalCommandError) as exc_info:
        list(stream)

    assert "5" in str(exc_info.value)


# Sanity: the module is actually routing through ``subprocess.Popen`` and
# isn't accidentally stubbed elsewhere. If someone refactors the runner to use
# ``run()`` or ``check_output()``, this test will flag it immediately.
def test_eval_default_runner_uses_subprocess_popen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[Sequence[str]] = []

    class _Sentinel(_FakePopen):
        def __init__(self, cmd: Sequence[str], **kw: object) -> None:
            called.append(list(cmd))
            super().__init__(cmd, **kw)

    _Sentinel.configure(events=[])
    monkeypatch.setattr(eval_slash.subprocess, "Popen", _Sentinel)

    list(eval_slash._default_stream_runner([]))

    assert called, "eval_slash._default_stream_runner must call subprocess.Popen"
    # The real runner always passes --output-format stream-json.
    assert "stream-json" in called[0]
