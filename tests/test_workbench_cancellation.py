"""Tests for the T16 cancellation primitive + streaming-handler integration.

Covers:

* :class:`CancellationToken` state transitions (``cancelled`` flag,
  process registration, idempotent cancel, reset).
* Subprocess lifecycle — a cancelled token terminates registered
  ``Popen`` objects and never leaks orphans (SIGTERM → SIGKILL
  escalation respected).
* Streaming-handler wiring — each of ``/eval``, ``/optimize``, ``/build``,
  ``/deploy`` honors the ``ctx.cancellation`` token (both token-flip
  mid-stream and direct ``KeyboardInterrupt`` paths), emits a yellow
  cancellation line, and returns a skip-display ``on_done``.
* App-loop double-ctrl-c behavior (first press cancels active tool call,
  second press exits).
"""

from __future__ import annotations

import _thread
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Sequence

import click
import pytest

from cli.llm.orchestrator import LLMOrchestrator
from cli.llm.provider_capabilities import ProviderCapabilities
from cli.llm.streaming import ToolUseDelta, ToolUseEnd, ToolUseStart
from cli.llm.types import TurnMessage
from cli.permissions import PermissionManager
from cli.tools.base import Tool, ToolContext, ToolResult
from cli.tools.registry import ToolRegistry
from cli.workbench_app.app import run_workbench_app
from cli.workbench_app.build_slash import (
    make_build_handler as make_build_handler_,
)
from cli.workbench_app.cancellation import (
    CancellationToken,
    iter_with_cancellation,
)
from cli.workbench_app.deploy_slash import (
    make_deploy_handler as make_deploy_handler_,
)
from cli.workbench_app.eval_slash import make_eval_handler
from cli.workbench_app.optimize_slash import (
    make_optimize_handler as make_optimize_handler_,
)
from cli.workbench_app.slash import SlashContext


# ---------------------------------------------------------------------------
# CancellationToken unit tests
# ---------------------------------------------------------------------------


def test_token_starts_uncancelled_and_inactive() -> None:
    token = CancellationToken()
    assert token.cancelled is False
    assert token.active is False


def test_cancel_sets_flag_and_is_idempotent() -> None:
    token = CancellationToken()
    token.cancel()
    token.cancel()  # second call must be a no-op, not a double-kill.
    assert token.cancelled is True


def test_reset_clears_flag_and_registry() -> None:
    token = CancellationToken()
    token.cancel()
    token.reset()
    assert token.cancelled is False
    assert token.active is False


class _FakeProc:
    """Minimal :class:`subprocess.Popen` stub for registry testing."""

    def __init__(self, *, exits_on_terminate: bool = True) -> None:
        self._alive = True
        self._exits_on_terminate = exits_on_terminate
        self.terminate_calls = 0
        self.kill_calls = 0
        self.wait_calls: list[float | None] = []

    def poll(self) -> int | None:
        return None if self._alive else 0

    def terminate(self) -> None:
        self.terminate_calls += 1
        if self._exits_on_terminate:
            self._alive = False

    def kill(self) -> None:
        self.kill_calls += 1
        self._alive = False

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls.append(timeout)
        if self._alive and not self._exits_on_terminate and self.kill_calls == 0:
            # Simulate a hung process — let the token escalate to kill.
            raise subprocess.TimeoutExpired(cmd="fake", timeout=timeout or 0)
        return 0


def test_register_process_tracks_active_state() -> None:
    token = CancellationToken()
    proc = _FakeProc()
    token.register_process(proc)
    assert token.active is True
    proc._alive = False
    assert token.active is False


def test_cancel_terminates_registered_process_gracefully() -> None:
    token = CancellationToken()
    proc = _FakeProc(exits_on_terminate=True)
    token.register_process(proc)
    token.cancel()
    assert proc.terminate_calls == 1
    assert proc.kill_calls == 0  # graceful SIGTERM was enough.


def test_cancel_escalates_to_kill_when_terminate_is_ignored() -> None:
    token = CancellationToken(terminate_grace=0.01)
    proc = _FakeProc(exits_on_terminate=False)
    token.register_process(proc)
    token.cancel()
    assert proc.terminate_calls == 1
    assert proc.kill_calls == 1  # escalated to SIGKILL after timeout.


def test_register_after_cancel_kills_late_arriver() -> None:
    """A process registered after ``cancel()`` is still terminated.

    Otherwise a racy handler could slip a subprocess through between the
    cancel and the handler's own cleanup.
    """
    token = CancellationToken()
    token.cancel()
    proc = _FakeProc(exits_on_terminate=True)
    token.register_process(proc)
    assert proc.terminate_calls == 1


def test_unregister_process_is_best_effort() -> None:
    token = CancellationToken()
    proc = _FakeProc()
    token.register_process(proc)
    token.unregister_process(proc)
    token.unregister_process(proc)  # second call tolerated.
    assert token.active is False


def test_cancel_survives_processlookup() -> None:
    """``ProcessLookupError`` on terminate means the child is already gone."""

    class _Dead(_FakeProc):
        def terminate(self) -> None:  # type: ignore[override]
            raise ProcessLookupError

    token = CancellationToken()
    proc = _Dead()
    token.register_process(proc)
    token.cancel()  # must not raise.
    assert proc.kill_calls == 0


def test_iter_with_cancellation_breaks_on_cancel() -> None:
    token = CancellationToken()

    def source() -> Iterator[int]:
        for value in range(5):
            yield value

    collected: list[int] = []
    for value in iter_with_cancellation(source(), token):
        collected.append(value)
        if value == 2:
            token.cancel()
    assert collected == [0, 1, 2]


# ---------------------------------------------------------------------------
# Real subprocess cleanup (sanity check — no orphans).
# ---------------------------------------------------------------------------


def test_cancel_terminates_real_long_running_subprocess() -> None:
    """Spawn a sleeping Python child, register it, cancel, assert it's reaped."""
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    token = CancellationToken(terminate_grace=2.0)
    token.register_process(proc)
    token.cancel()
    # At this point the subprocess should be gone; give the OS a short
    # grace window to reap it before we assert.
    for _ in range(20):
        if proc.poll() is not None:
            break
        time.sleep(0.05)
    try:
        assert proc.poll() is not None, "subprocess was not terminated by cancel()"
    finally:
        if proc.poll() is None:  # last-resort cleanup so the test never leaks.
            proc.kill()
            proc.wait(timeout=2)


# ---------------------------------------------------------------------------
# Handler integration — mid-stream cancel via token.
# ---------------------------------------------------------------------------


def _capture_echo() -> tuple[list[str], callable]:  # type: ignore[type-arg]
    sink: list[str] = []

    def echo(text: str = "") -> None:
        sink.append(text)

    return sink, echo


def _make_ctx(echo, token: CancellationToken | None = None) -> SlashContext:
    return SlashContext(
        workspace=None,
        session=None,
        session_store=None,
        echo=echo,
        click_invoker=None,
        cancellation=token,
    )


def _mid_stream_runner(token: CancellationToken):
    """Runner that yields one event then flips the cancellation flag."""

    def _runner(args: Sequence[str], *, cancellation: CancellationToken | None = None) -> Iterator[dict[str, Any]]:
        yield {"event": "phase_started", "phase": "eval"}
        token.cancel()
        # The handler checks `cancellation.cancelled` after each yield, so
        # the second event would still be consumed but we break out before
        # draining more. Yielding an extra event tests that behavior.
        yield {"event": "phase_started", "phase": "should-not-render"}

    return _runner


def _ki_runner(args: Sequence[str], **_: Any) -> Iterator[dict[str, Any]]:
    yield {"event": "phase_started", "phase": "eval"}
    raise KeyboardInterrupt


def _strip(s: str) -> str:
    return click.unstyle(s)


@pytest.mark.parametrize(
    "make_handler,slash,ctx_arg",
    [
        (make_eval_handler, "/eval", ()),
        (make_optimize_handler_, "/optimize", ("--eval-run-id", "er_test")),
        (make_build_handler_, "/build", ("a brief",)),
        # /deploy needs a prompter-free path to avoid the y/N dialog.
        (
            lambda runner: make_deploy_handler_(
                runner=runner, prompter=lambda _msg: True
            ),
            "/deploy",
            ("-y", "--attempt-id", "att_test"),
        ),
    ],
)
def test_handler_cancels_mid_stream_via_token(
    make_handler, slash, ctx_arg
) -> None:
    token = CancellationToken()
    handler = make_handler(_mid_stream_runner(token))
    sink, echo = _capture_echo()
    ctx = _make_ctx(echo, token=token)
    result = handler(ctx, *ctx_arg)
    plain = [_strip(line) for line in sink]
    assert any("cancelled" in line for line in plain), plain
    assert result.display == "skip"
    assert token.cancelled is True


@pytest.mark.parametrize(
    "make_handler,slash,ctx_arg",
    [
        (make_eval_handler, "/eval", ()),
        (make_optimize_handler_, "/optimize", ("--eval-run-id", "er_test")),
        (make_build_handler_, "/build", ("a brief",)),
        (
            lambda runner: make_deploy_handler_(
                runner=runner, prompter=lambda _msg: True
            ),
            "/deploy",
            ("-y", "--attempt-id", "att_test"),
        ),
    ],
)
def test_handler_cancels_on_keyboard_interrupt(
    make_handler, slash, ctx_arg
) -> None:
    token = CancellationToken()
    handler = make_handler(_ki_runner)
    sink, echo = _capture_echo()
    ctx = _make_ctx(echo, token=token)
    result = handler(ctx, *ctx_arg)
    assert token.cancelled is True, "handler must flip the token on KeyboardInterrupt"
    assert result.display == "skip"
    assert any("cancelled" in _strip(line) for line in sink)


def test_handler_without_token_still_respects_keyboard_interrupt() -> None:
    """Legacy callers (no token on context) still get a clean cancel path."""
    handler = make_eval_handler(_ki_runner)
    sink, echo = _capture_echo()
    ctx = _make_ctx(echo, token=None)
    result = handler(ctx)
    assert result.display == "skip"
    assert any("cancelled" in _strip(line) for line in sink)


def test_handler_passes_token_to_runner_when_supported() -> None:
    """Runner that accepts ``cancellation`` kwarg should receive the token."""
    captured: dict[str, Any] = {}

    def runner(
        args: Sequence[str],
        *,
        cancellation: CancellationToken | None = None,
    ) -> Iterator[dict[str, Any]]:
        captured["cancellation"] = cancellation
        yield {"event": "phase_completed", "phase": "eval"}

    token = CancellationToken()
    handler = make_eval_handler(runner)
    _, echo = _capture_echo()
    ctx = _make_ctx(echo, token=token)
    handler(ctx)
    assert captured["cancellation"] is token


def test_handler_falls_back_for_legacy_runner_signature() -> None:
    """Runner that only accepts positional ``args`` must still be called."""
    calls: list[Sequence[str]] = []

    def runner(args: Sequence[str]) -> Iterator[dict[str, Any]]:
        calls.append(list(args))
        yield {"event": "phase_completed", "phase": "eval"}

    token = CancellationToken()
    handler = make_eval_handler(runner)
    _, echo = _capture_echo()
    ctx = _make_ctx(echo, token=token)
    handler(ctx)
    assert calls == [[]]


# ---------------------------------------------------------------------------
# App-loop double-ctrl-c behavior
# ---------------------------------------------------------------------------


@dataclass
class _ToolState:
    """Lifecycle signals for the in-process tool used in the Ctrl+C test."""

    started: threading.Event = field(default_factory=threading.Event)
    finished: threading.Event = field(default_factory=threading.Event)
    cancel_observed: threading.Event = field(default_factory=threading.Event)


class _InterruptibleTool(Tool):
    """Read-only tool that exits only when the shared token is cancelled."""

    name = "Interruptible"
    description = "Blocks until cancelled."
    input_schema = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    read_only = True
    is_concurrency_safe = True

    def __init__(self, state: _ToolState) -> None:
        self._state = state

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        self._state.started.set()
        token = context.cancel_check
        while not getattr(token, "cancelled", False):
            time.sleep(0.01)
        self._state.cancel_observed.set()
        self._state.finished.set()
        return ToolResult.success("cancelled")


@dataclass
class _SingleToolTurnModel:
    """Model stub that emits one tool-use turn and should never reach a follow-up."""

    capabilities: ProviderCapabilities
    calls: int = 0

    def stream(
        self,
        *,
        system_prompt: str,
        messages: list[TurnMessage],
        tools: list[dict[str, Any]],
    ) -> Iterator[Any]:
        self.calls += 1
        if self.calls > 1:  # pragma: no cover - regression sentinel
            raise AssertionError("cancelled turn should not reach a follow-up model call")
        yield ToolUseStart(id="tool-1", name="Interruptible")
        yield ToolUseDelta(id="tool-1", input_json="{}")
        yield ToolUseEnd(id="tool-1", name="Interruptible", input={})


def _caps(*, parallel_tool_calls: bool) -> ProviderCapabilities:
    return ProviderCapabilities(
        streaming=True,
        native_tool_use=True,
        parallel_tool_calls=parallel_tool_calls,
        thinking=False,
        prompt_cache=False,
        vision=False,
        json_mode=False,
        max_context_tokens=1_000,
        max_output_tokens=1_000,
    )


def _recorder_echo() -> tuple[list[str], Any]:
    sink: list[str] = []

    def echo(text: str = "") -> None:
        sink.append(text)

    return sink, echo


def test_first_interrupt_at_idle_warns_without_exiting() -> None:
    calls = {"count": 0}

    def provider(_prompt: str) -> str:
        calls["count"] += 1
        if calls["count"] == 1:
            raise KeyboardInterrupt
        return "/exit"

    sink, echo = _recorder_echo()
    result = run_workbench_app(
        workspace=None,
        input_provider=provider,
        echo=echo,
        show_banner=False,
    )
    joined = "\n".join(_strip(line) for line in sink)
    assert "press ctrl-c again" in joined
    assert result.exited_via == "/exit"
    # ``interrupts`` counts the *consecutive* streak at exit; the /exit line
    # that followed resets it to zero — we only care that the warning fired.


def test_double_interrupt_without_input_exits() -> None:
    def provider(_prompt: str) -> str:
        raise KeyboardInterrupt

    sink, echo = _recorder_echo()
    result = run_workbench_app(
        workspace=None,
        input_provider=provider,
        echo=echo,
        show_banner=False,
    )
    assert result.exited_via == "interrupt"
    assert result.interrupts == 2
    joined = "\n".join(_strip(line) for line in sink)
    assert "interrupted" in joined


def test_successful_input_resets_interrupt_streak() -> None:
    """An interrupt followed by normal input must reset the counter."""
    events: list[Any] = [KeyboardInterrupt, "echo-this", KeyboardInterrupt, "/exit"]
    it = iter(events)

    def provider(_prompt: str) -> str:
        nxt = next(it)
        if nxt is KeyboardInterrupt:
            raise KeyboardInterrupt
        return nxt  # type: ignore[return-value]

    sink, echo = _recorder_echo()
    result = run_workbench_app(
        workspace=None,
        input_provider=provider,
        echo=echo,
        show_banner=False,
    )
    # A single stray ctrl-c between real inputs must not kill the app.
    assert result.exited_via == "/exit"
    assert result.lines_read == 2  # "echo-this" + "/exit"


def test_interrupt_with_active_tool_call_cancels_instead_of_exiting() -> None:
    """When a subprocess is registered, the first ctrl-c cancels, not exits."""
    token = CancellationToken()
    proc = _FakeProc(exits_on_terminate=True)
    token.register_process(proc)

    # The provider raises one ctrl-c, then /exit — with an active token the
    # first press must be routed into token.cancel() (not counted toward the
    # exit threshold).
    events = iter([KeyboardInterrupt, "/exit"])

    def provider(_prompt: str) -> str:
        nxt = next(events)
        if nxt is KeyboardInterrupt:
            raise KeyboardInterrupt
        return nxt  # type: ignore[return-value]

    sink, echo = _recorder_echo()
    result = run_workbench_app(
        workspace=None,
        input_provider=provider,
        echo=echo,
        show_banner=False,
        cancellation=token,
    )
    assert proc.terminate_calls == 1
    # With an active call the first ctrl-c cancelled — /exit then ended cleanly.
    assert result.exited_via == "/exit"
    assert any("cancelled active tool call" in _strip(line) for line in sink)


def test_keyboard_interrupt_during_python_tool_turn_cancels_cleanly(
    tmp_path: Path,
) -> None:
    """A real Ctrl+C during a thread-pooled Python tool should return a cancelled turn."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    state = _ToolState()
    registry = ToolRegistry()
    registry.register(_InterruptibleTool(state))
    orchestrator = LLMOrchestrator(
        model=_SingleToolTurnModel(capabilities=_caps(parallel_tool_calls=True)),
        tool_registry=registry,
        permissions=PermissionManager(root=workspace),
        workspace_root=workspace,
        echo=lambda _line: None,
    )

    def _trigger_interrupt() -> None:
        assert state.started.wait(timeout=1)
        os.kill(os.getpid(), signal.SIGINT)

    interrupter = threading.Thread(target=_trigger_interrupt, daemon=True)
    interrupter.start()

    sink, echo = _recorder_echo()
    result = run_workbench_app(
        workspace=None,
        input_provider=["please cancel me", "/exit"],
        echo=echo,
        show_banner=False,
        orchestrator=orchestrator,
    )

    assert state.finished.wait(timeout=1)
    assert state.cancel_observed.is_set()
    assert result.exited_via == "/exit"
    joined = "\n".join(_strip(line) for line in sink)
    assert "(stop: cancelled)" in joined


# ---------------------------------------------------------------------------
# SlashContext wiring sanity
# ---------------------------------------------------------------------------


def test_slash_context_accepts_cancellation_token() -> None:
    token = CancellationToken()
    ctx = SlashContext(cancellation=token)
    assert ctx.cancellation is token


def test_slash_context_defaults_cancellation_to_none() -> None:
    ctx = SlashContext()
    assert ctx.cancellation is None
