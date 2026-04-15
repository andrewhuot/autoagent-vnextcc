"""Tests for the live orchestrator wiring inside :func:`run_workbench_app`.

The earlier Phase-C test module covered ``build_workbench_runtime`` in
isolation; this one drives the actual REPL loop to confirm natural-
language input lands in the orchestrator and the subsystems show up on
the slash context so follow-up ``/plan`` / ``/usage`` commands work."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import click
import pytest

from cli.llm.streaming import (
    MessageStop,
    TextDelta,
    ToolUseEnd,
    ToolUseStart,
)
from cli.llm.types import TurnMessage
from cli.workbench_app import run_workbench_app
from cli.workbench_app.background_slash import (
    BACKGROUND_REGISTRY_META_KEY,
)
from cli.workbench_app.orchestrator_runtime import build_workbench_runtime
from cli.workbench_app.plan_slash import PLAN_WORKFLOW_META_KEY
from cli.workbench_app.slash import SlashContext, build_builtin_registry
from cli.workbench_app.transcript_rewind_slash import (
    TRANSCRIPT_REWIND_MANAGER_META_KEY,
)
from cli.user_skills.slash import SKILL_REGISTRY_META_KEY


# ---------------------------------------------------------------------------
# Fakes + helpers
# ---------------------------------------------------------------------------


class _ScriptedModel:
    """Streaming stub that produces a scripted event list per call."""

    def __init__(self, turns: list[list[Any]]) -> None:
        self._turns = list(turns)
        self.calls: list[dict[str, Any]] = []

    def stream(
        self,
        *,
        system_prompt: str,
        messages: list[TurnMessage],
        tools: list[dict[str, Any]],
    ) -> Iterator[Any]:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "messages": [m.to_wire() for m in messages],
                "tools": tools,
            }
        )
        events = self._turns.pop(0) if self._turns else [MessageStop(stop_reason="end_turn")]
        for event in events:
            yield event


def _capture_sink() -> tuple[list[str], Any]:
    """Return a list and a click-style echo that appends stripped lines."""
    out: list[str] = []

    def echo(line: str = "") -> None:
        out.append(click.unstyle(line))

    return out, echo


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / ".agentlab").mkdir()
    return tmp_path


# ---------------------------------------------------------------------------
# Natural-language turns route through the orchestrator when supplied
# ---------------------------------------------------------------------------


def test_run_workbench_app_routes_through_orchestrator(workspace: Path) -> None:
    model = _ScriptedModel(
        [
            [
                TextDelta(text="Hello from the orchestrator."),
                MessageStop(stop_reason="end_turn"),
            ]
        ]
    )
    runtime = build_workbench_runtime(
        workspace_root=workspace,
        model=model,
    )
    lines, echo = _capture_sink()
    result = run_workbench_app(
        workspace=None,
        input_provider=["hello there", "/exit"],
        echo=echo,
        show_banner=False,
        orchestrator=runtime,
    )
    # Model was actually invoked.
    assert model.calls, "orchestrator never called the model"
    # Exit via slash, not via EOF — proves the loop reached the /exit turn
    # after dispatching the natural-language one.
    assert result.exited_via == "/exit"
    rendered = "\n".join(lines)
    assert "Hello from the orchestrator." in rendered


def test_orchestrator_path_surfaces_tool_executions(workspace: Path) -> None:
    """A natural-language turn that triggers a FileRead should execute it
    and render the follow-up text — exercising the full tool loop."""
    (workspace / "a.txt").write_text("hello world\n", encoding="utf-8")

    model = _ScriptedModel(
        [
            [
                ToolUseStart(id="t1", name="FileRead"),
                ToolUseEnd(
                    id="t1",
                    name="FileRead",
                    input={"path": "a.txt"},
                ),
                MessageStop(stop_reason="tool_use"),
            ],
            [
                TextDelta(text="File read complete."),
                MessageStop(stop_reason="end_turn"),
            ],
        ]
    )
    runtime = build_workbench_runtime(
        workspace_root=workspace,
        model=model,
    )
    _, echo = _capture_sink()
    run_workbench_app(
        workspace=None,
        input_provider=["read a.txt", "/exit"],
        echo=echo,
        show_banner=False,
        orchestrator=runtime,
    )
    # Two model calls: one that asks for the tool, one that finishes.
    assert len(model.calls) == 2
    # The second call's messages include a tool_result entry.
    final_call_messages = model.calls[1]["messages"]
    tool_result = final_call_messages[-1]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert "hello world" in tool_result["content"]


# ---------------------------------------------------------------------------
# Slash commands see the subsystems the orchestrator is using
# ---------------------------------------------------------------------------


def test_subsystems_publish_to_slash_context(workspace: Path) -> None:
    model = _ScriptedModel([])
    runtime = build_workbench_runtime(
        workspace_root=workspace,
        model=model,
    )
    registry = build_builtin_registry()
    ctx = SlashContext(workspace=None, registry=registry)

    lines, echo = _capture_sink()
    run_workbench_app(
        workspace=None,
        input_provider=["/exit"],
        echo=echo,
        show_banner=False,
        orchestrator=runtime,
        slash_context=ctx,
        registry=registry,
    )
    # Every published key is bound to the live subsystem.
    assert ctx.meta[PLAN_WORKFLOW_META_KEY] is runtime.plan_workflow
    assert ctx.meta[SKILL_REGISTRY_META_KEY] is runtime.skill_registry
    assert ctx.meta[TRANSCRIPT_REWIND_MANAGER_META_KEY] is runtime.transcript_rewind
    assert ctx.meta[BACKGROUND_REGISTRY_META_KEY] is runtime.background_tasks
    assert ctx.meta["active_model"] == "claude-sonnet-4-5"


def test_bare_orchestrator_still_publishes_active_model(workspace: Path) -> None:
    """A caller that passes just an orchestrator (no runtime bundle)
    should still set ``active_model`` when the orchestrator carries a
    seed. Keeps the publication logic forgiving."""
    model = _ScriptedModel([])
    runtime = build_workbench_runtime(
        workspace_root=workspace,
        model=model,
    )
    # Pass only the orchestrator, not the runtime bundle.
    orchestrator = runtime.orchestrator

    registry = build_builtin_registry()
    ctx = SlashContext(workspace=None, registry=registry)
    lines, echo = _capture_sink()
    run_workbench_app(
        workspace=None,
        input_provider=["/exit"],
        echo=echo,
        show_banner=False,
        orchestrator=orchestrator,
        slash_context=ctx,
        registry=registry,
    )
    # Only active_model is guaranteed here — the subsystem keys require
    # the WorkbenchRuntime bundle.
    assert ctx.meta.get("active_model") == "claude-sonnet-4-5"


# ---------------------------------------------------------------------------
# Orchestrator failure is non-fatal
# ---------------------------------------------------------------------------


class _CrashingOrchestrator:
    """Orchestrator whose run_turn raises — used to prove the REPL survives."""

    def run_turn(self, prompt: str):
        raise RuntimeError("boom")


def test_orchestrator_exception_does_not_kill_repl(workspace: Path) -> None:
    """A bad turn should warn and keep accepting input."""
    lines, echo = _capture_sink()
    result = run_workbench_app(
        workspace=None,
        input_provider=["trigger crash", "/exit"],
        echo=echo,
        show_banner=False,
        orchestrator=_CrashingOrchestrator(),
    )
    assert result.exited_via == "/exit"
    combined = "\n".join(lines)
    assert "orchestrator turn failed" in combined or "boom" in combined


# ---------------------------------------------------------------------------
# Backwards compatibility — no orchestrator means no change
# ---------------------------------------------------------------------------


def test_no_orchestrator_preserves_echo_fallback() -> None:
    """Without an orchestrator or agent runtime the REPL still runs, and
    free-text input still echoes back (the headless default)."""
    lines, echo = _capture_sink()
    run_workbench_app(
        workspace=None,
        input_provider=["hi", "/exit"],
        echo=echo,
        show_banner=False,
    )
    combined = "\n".join(lines)
    assert "AgentLab received: hi" in combined
