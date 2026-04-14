"""Tests for the Workbench coordinator turn runtime."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import click

from builder.events import EventBroker
from builder.orchestrator import BuilderOrchestrator
from builder.store import BuilderStore
from builder.types import BuilderProject, BuilderSession, BuilderTask, SpecialistRole
from cli.workbench_app import run_workbench_app
from cli.workbench_app.slash import SlashContext, build_builtin_registry


def _capture_echo() -> tuple[list[str], callable]:
    lines: list[str] = []

    def echo(text: str = "") -> None:
        lines.append(text)

    return lines, echo


@dataclass
class _FakeTurnResult:
    transcript_lines: tuple[str, ...]
    active_tasks: int = 0
    task_id: str = "task-fake"
    plan_id: str = "plan-fake"
    run_id: str = "run-fake"


class _FakeTurnRuntime:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def process_turn(self, message: str, *, ctx: SlashContext | None = None, command_intent: str | None = None):
        self.calls.append(message)
        if ctx is not None:
            ctx.meta["active_tasks"] = 1
        return _FakeTurnResult(
            transcript_lines=(f"  coordinator handled: {message}",),
            active_tasks=1,
        )


def test_free_text_routes_to_agent_runtime_instead_of_echoing() -> None:
    """Default Workbench text should become a coordinator turn, not an echo."""
    runtime = _FakeTurnRuntime()
    lines, echo = _capture_echo()

    result = run_workbench_app(
        workspace=None,
        input_provider=iter(["I want to build my agent", "/exit"]),
        echo=echo,
        show_banner=False,
        agent_runtime=runtime,
    )

    joined = click.unstyle("\n".join(lines))
    assert result.exited_via == "/exit"
    assert runtime.calls == ["I want to build my agent"]
    assert "coordinator handled: I want to build my agent" in joined
    assert "AgentLab received" not in joined
    assert "1 task" in joined


def test_tasks_command_renders_latest_coordinator_turn() -> None:
    """Users need a Claude Code-style task view for the latest coordinator run."""
    runtime = _FakeTurnRuntime()
    lines, echo = _capture_echo()
    ctx = SlashContext(registry=build_builtin_registry(include_streaming=False))

    run_workbench_app(
        workspace=None,
        input_provider=iter(["Build an agent", "/tasks", "/exit"]),
        echo=echo,
        show_banner=False,
        slash_context=ctx,
        agent_runtime=runtime,
    )

    joined = click.unstyle("\n".join(lines))
    assert "Coordinator Tasks" in joined
    assert "task-fake" in joined
    assert "plan-fake" in joined
    assert "run-fake" in joined


def test_workbench_agent_runtime_creates_and_executes_coordinator_turn(tmp_path: Path) -> None:
    """The real runtime should plan and execute a persisted coordinator run."""
    from cli.workbench_app.runtime import WorkbenchAgentRuntime

    store = BuilderStore(db_path=str(tmp_path / "builder.db"))
    events = EventBroker()
    orchestrator = BuilderOrchestrator(store=store)
    runtime = WorkbenchAgentRuntime(
        store=store,
        orchestrator=orchestrator,
        events=events,
    )

    result = runtime.process_turn("I want to build my agent")

    assert result.task_id
    assert result.plan_id
    assert result.run_id
    assert result.command_intent == "build"
    assert result.active_tasks == 0
    assert any("Coordinator plan" in line for line in result.transcript_lines)

    task = store.get_task(result.task_id)
    assert task is not None
    assert task.metadata["latest_coordinator_run_id"] == result.run_id
    assert store.get_coordinator_run(result.run_id) is not None


def test_workbench_agent_runtime_reuses_active_builder_context(tmp_path: Path) -> None:
    """Follow-up turns should attach to the current Builder project and session."""
    from cli.workbench_app.runtime import WorkbenchAgentRuntime

    store = BuilderStore(db_path=str(tmp_path / "builder.db"))
    project = BuilderProject(name="Existing")
    session = BuilderSession(project_id=project.project_id, title="Existing session")
    task = BuilderTask(
        project_id=project.project_id,
        session_id=session.session_id,
        title="Prior task",
        description="Build a support agent",
    )
    store.save_project(project)
    store.save_session(session)
    store.save_task(task)
    ctx = SlashContext(meta={
        "builder_project_id": project.project_id,
        "builder_session_id": session.session_id,
    })

    runtime = WorkbenchAgentRuntime(
        store=store,
        orchestrator=BuilderOrchestrator(store=store),
        events=EventBroker(),
    )

    result = runtime.process_turn("Now evaluate it", ctx=ctx)

    new_task = store.get_task(result.task_id)
    assert new_task is not None
    assert new_task.project_id == project.project_id
    assert new_task.session_id == session.session_id
    assert result.command_intent == "eval"
    assert SpecialistRole.EVAL_AUTHOR.value in result.worker_roles
