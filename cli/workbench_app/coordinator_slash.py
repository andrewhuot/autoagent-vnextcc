"""Coordinator-backed slash commands for the Workbench."""

from __future__ import annotations

from typing import Any, Callable

from cli.workbench_app import theme
from cli.workbench_app.commands import LocalCommand, OnDoneResult, on_done
from cli.workbench_app.runtime import remember_turn_result
from cli.workbench_app.slash import SlashContext


_COMMAND_DESCRIPTIONS: dict[str, str] = {
    "build": "Build or change an agent with coordinator-managed workers",
    "eval": "Evaluate the active agent candidate and interpret loss patterns",
    "optimize": "Optimize the agent from eval and trace evidence",
    "deploy": "Prepare canary, release, and rollback gates",
    "skills": "Find and attach build-time skills through the coordinator",
}


def build_coordinator_command(intent: str) -> LocalCommand:
    """Return a coordinator-backed slash command for one workflow intent."""
    return LocalCommand(
        name=intent,
        description=_COMMAND_DESCRIPTIONS[intent],
        handler=make_coordinator_handler(intent),
        source="builtin",
        argument_hint="[request]",
        when_to_use=f"Use when you want the coordinator-worker harness to {intent} the agent.",
        effort="medium",
        sensitive=intent in {"deploy", "skills", "optimize"},
    )


def build_tasks_command() -> LocalCommand:
    """Return the `/tasks` command that renders latest coordinator state."""
    return LocalCommand(
        name="tasks",
        description="Show coordinator plans, worker state, and queued work",
        handler=_handle_tasks,
        source="builtin",
        aliases=("task",),
        when_to_use="Use to inspect what coordinator workers just did or where work is blocked.",
    )


def make_coordinator_handler(intent: str) -> Callable[..., OnDoneResult]:
    """Create a slash handler that seeds a coordinator turn."""

    def _handle(ctx: SlashContext, *args: str) -> OnDoneResult:
        runtime = ctx.meta.get("agent_runtime")
        session = ctx.coordinator_session or getattr(runtime, "coordinator_session", None)
        if session is None and runtime is None:
            return on_done(
                "  Coordinator runtime is not attached to this Workbench session.",
                display="system",
            )
        message = " ".join(args).strip() or _default_message(intent)
        if session is not None:
            result = session.process_turn(
                message,
                project_id=_meta_str(ctx, "builder_project_id"),
                session_id=_meta_str(ctx, "builder_session_id"),
                command_intent=intent,
                permission_mode=_meta_str(ctx, "permission_mode"),
            )
        else:
            result = runtime.process_turn(message, ctx=ctx, command_intent=intent)
        remember_turn_result(ctx, result)
        return on_done(
            "\n".join(result.transcript_lines),
            display="user",
            meta_messages=tuple(result.next_actions),
        )

    return _handle


def _handle_tasks(ctx: SlashContext, *_: str) -> OnDoneResult:
    """Render latest coordinator task state from session metadata."""
    session = ctx.coordinator_session
    if session is not None and hasattr(session, "tasks_snapshot"):
        return on_done(_render_session_tasks(session.tasks_snapshot()), display="user")
    latest = ctx.meta.get("latest_coordinator_turn")
    if latest is None:
        return on_done(
            "  No coordinator tasks yet. Start with /build <what you want to make>.",
            display="system",
        )
    lines = [theme.heading("\n  Coordinator Tasks")]
    task_id = _attr(latest, "task_id")
    plan_id = _attr(latest, "plan_id")
    run_id = _attr(latest, "run_id")
    status = _attr(latest, "status") or "unknown"
    intent = _attr(latest, "command_intent") or "turn"
    lines.append(f"    Intent: /{intent}")
    lines.append(f"    Task:   {task_id}")
    lines.append(f"    Plan:   {plan_id}")
    lines.append(f"    Run:    {run_id}")
    lines.append(f"    Status: {status}")
    worker_roles = tuple(getattr(latest, "worker_roles", ()) or ())
    if worker_roles:
        lines.append("")
        lines.append("    Workers:")
        for role in worker_roles:
            lines.append(f"      • {str(role).replace('_', ' ')}")
    active = int(getattr(latest, "active_tasks", 0) or 0)
    queued = len(ctx.meta.get("queued_inputs", []) or [])
    lines.append("")
    lines.append(f"    Active tasks: {active}")
    lines.append(f"    Queued inputs: {queued}")
    next_actions = tuple(getattr(latest, "next_actions", ()) or ())
    if next_actions:
        lines.append("")
        lines.append("    Next:")
        for action in next_actions:
            lines.append(f"      • {action}")
    return on_done("\n".join(lines), display="user")


def _render_session_tasks(snapshot: dict[str, Any]) -> str:
    """Render persisted task/run state from :class:`CoordinatorSession`."""
    lines = [theme.heading("\n  Coordinator Tasks")]
    project_id = str(snapshot.get("project_id") or "")
    session_id = str(snapshot.get("session_id") or "")
    if project_id:
        lines.append(f"    Project: {project_id}")
    if session_id:
        lines.append(f"    Session: {session_id}")
    lines.append(f"    Active runs: {int(snapshot.get('active_run_count') or 0)}")
    tasks = list(snapshot.get("tasks") or [])
    if tasks:
        lines.append("")
        lines.append("    Recent tasks:")
        for task in tasks:
            intent = task.get("command_intent") or "turn"
            title = task.get("title") or task.get("task_id")
            status = task.get("status") or "unknown"
            lines.append(f"      • /{intent} {title} [{status}]")
    runs = list(snapshot.get("runs") or [])
    if runs:
        lines.append("")
        lines.append("    Recent runs:")
        for run in runs:
            lines.append(
                "      • "
                f"{run.get('run_id')} {run.get('status')} "
                f"({run.get('worker_count', 0)} workers)"
            )
    if not tasks and not runs:
        lines.append("    No coordinator tasks yet. Start with /build <what you want to make>.")
    return "\n".join(lines)


def _default_message(intent: str) -> str:
    """Return a useful default prompt when the slash command has no args."""
    defaults = {
        "build": "Build or refine the active agent.",
        "eval": "Evaluate the active agent candidate and summarize failures.",
        "optimize": "Optimize the agent from the latest eval evidence.",
        "deploy": "Prepare a canary deployment and rollback plan.",
        "skills": "Recommend build-time skills that would improve this agent.",
    }
    return defaults.get(intent, "Continue the agent build.")


def _attr(value: Any, name: str) -> str:
    """Read an attribute or mapping key as display text."""
    if isinstance(value, dict):
        raw = value.get(name)
    else:
        raw = getattr(value, name, None)
    return "" if raw is None else str(raw)


def _meta_str(ctx: SlashContext, key: str) -> str | None:
    """Read a string metadata value from the slash context."""
    value = ctx.meta.get(key)
    return str(value) if value else None


__all__ = [
    "build_coordinator_command",
    "build_tasks_command",
    "make_coordinator_handler",
]
