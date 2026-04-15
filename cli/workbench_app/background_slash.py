"""Slash commands for the background-task panel.

Uses ``/background`` for the panel view and ``/background-clear`` for the
cleanup verb. Named distinctly from the legacy ``&`` background-turn
syntax so users can tell at a glance that these deal with subagent /
long-running tool work rather than coordinator fire-and-forget turns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cli.workbench_app import theme
from cli.workbench_app.background_panel import BackgroundTaskRegistry, render_panel
from cli.workbench_app.commands import LocalCommand, OnDoneResult, on_done

if TYPE_CHECKING:
    from cli.workbench_app.slash import SlashContext


BACKGROUND_REGISTRY_META_KEY = "background_task_registry"


def build_background_command() -> LocalCommand:
    return LocalCommand(
        name="background",
        description="List active and recent background tasks",
        handler=_handle_background,
        source="builtin",
        argument_hint="[--active-only]",
        when_to_use=(
            "Use to see the state of subagents and long-running tool "
            "invocations spawned this session."
        ),
    )


def build_background_clear_command() -> LocalCommand:
    return LocalCommand(
        name="background-clear",
        description="Drop completed/failed background tasks from the panel",
        handler=_handle_background_clear,
        source="builtin",
        argument_hint="[--all]",
        sensitive=False,
    )


def all_background_commands() -> tuple[LocalCommand, ...]:
    return (build_background_command(), build_background_clear_command())


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _handle_background(ctx: "SlashContext", *args: str) -> OnDoneResult:
    registry = _registry_from_ctx(ctx)
    if registry is None:
        return _registry_missing()
    include_completed = not _flag_present(args, "--active-only")
    lines = [theme.workspace("Background tasks")]
    lines.extend(render_panel(registry, include_completed=include_completed))
    return on_done("\n".join(lines), display="user")


def _handle_background_clear(ctx: "SlashContext", *args: str) -> OnDoneResult:
    registry = _registry_from_ctx(ctx)
    if registry is None:
        return _registry_missing()
    drop_all = _flag_present(args, "--all")
    removed = registry.clear(completed_only=not drop_all)
    verb = "tasks" if removed != 1 else "task"
    return on_done(
        theme.success(f"  Cleared {removed} background {verb}."),
        display="user",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _registry_from_ctx(ctx: "SlashContext") -> BackgroundTaskRegistry | None:
    registry = ctx.meta.get(BACKGROUND_REGISTRY_META_KEY) if ctx.meta else None
    return registry if isinstance(registry, BackgroundTaskRegistry) else None


def _flag_present(args: tuple[str, ...], flag: str) -> bool:
    return any(arg.strip() == flag for arg in args)


def _registry_missing() -> OnDoneResult:
    return on_done(
        theme.warning(
            "  Background-task panel is not configured for this session. "
            "Re-launch the workbench or file a bug."
        ),
        display="system",
    )


__all__ = [
    "BACKGROUND_REGISTRY_META_KEY",
    "all_background_commands",
    "build_background_clear_command",
    "build_background_command",
]
