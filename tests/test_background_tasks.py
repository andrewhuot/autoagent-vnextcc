"""Tests for ``&`` background-task dispatch in the Workbench REPL."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import click

from cli.workbench_app import run_workbench_app
from cli.workbench_app.app import _run_background_turn
from cli.workbench_app.slash import SlashContext


@dataclass
class _TurnResult:
    transcript_lines: tuple[str, ...] = ("  background: done",)
    next_actions: tuple[str, ...] = ()
    active_tasks: int = 0
    task_id: str = "t1"
    plan_id: str = "p1"
    run_id: str = "r1"
    status: str = "completed"
    worker_roles: tuple[str, ...] = ()
    command_intent: str = "background"


class _RecordingRuntime:
    """Captures each coordinator turn and lets a probe observe mid-run state."""

    def __init__(self, probe=None) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self._probe = probe

    def process_turn(self, line, *, ctx=None, command_intent=None, **_kwargs):
        self.calls.append((line, command_intent))
        if self._probe is not None and ctx is not None:
            self._probe(ctx)
        return _TurnResult()


def _capture():
    lines: list[str] = []

    def echo(line: str = "") -> None:
        lines.append(click.unstyle(line))

    return lines, echo


def test_run_background_turn_increments_active_tasks_during_dispatch() -> None:
    observed: list[int] = []

    def probe(ctx):
        observed.append(int(ctx.meta.get("active_tasks", 0)))

    runtime = _RecordingRuntime(probe=probe)
    ctx = SlashContext()
    lines, echo = _capture()
    _run_background_turn(runtime=runtime, ctx=ctx, line="spin up a loader", echo=echo)
    assert runtime.calls == [("spin up a loader", "background")]
    assert observed == [1]
    # After a synchronous finish the footer should be idle again.
    assert int(ctx.meta.get("active_tasks", 0)) == 0
    assert ctx.meta.get("background_queue") == []
    assert any("Dispatched background task" in line for line in lines)


def test_run_background_turn_empty_body_warns_without_calling_runtime() -> None:
    runtime = _RecordingRuntime()
    ctx = SlashContext()
    lines, echo = _capture()
    _run_background_turn(runtime=runtime, ctx=ctx, line="", echo=echo)
    assert runtime.calls == []
    assert any("provide a request" in line for line in lines)


def test_run_background_turn_without_runtime_warns() -> None:
    ctx = SlashContext()
    lines, echo = _capture()
    _run_background_turn(runtime=None, ctx=ctx, line="hello", echo=echo)
    assert any("coordinator runtime is not available" in line for line in lines)


def test_app_dispatches_ampersand_prefix_to_background_turn() -> None:
    runtime = _RecordingRuntime()
    lines, echo = _capture()
    result = run_workbench_app(
        workspace=None,
        input_provider=iter(["&build agent", "/exit"]),
        echo=echo,
        show_banner=False,
        agent_runtime=runtime,
    )
    assert result.exited_via == "/exit"
    assert runtime.calls == [("build agent", "background")]
    assert any("Dispatched background task" in line for line in lines)
