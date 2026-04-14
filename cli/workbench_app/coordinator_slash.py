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
        if runtime is None:
            return on_done(
                "  Coordinator runtime is not attached to this Workbench session.",
                display="system",
            )
        message = " ".join(args).strip() or _default_message(intent)
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


__all__ = [
    "build_coordinator_command",
    "build_tasks_command",
    "make_coordinator_handler",
]
