"""``/output-style`` slash command.

Swaps the global :data:`current_style` and persists the choice under
``output.style`` in workspace settings — the setting is project-scoped
because transcript verbosity is often a project convention (``verbose``
while onboarding, ``concise`` once the team is comfortable).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from cli.settings import save_project_settings
from cli.workbench_app import output_style, theme
from cli.workbench_app.commands import LocalCommand, OnDoneResult, on_done

if TYPE_CHECKING:
    from cli.workbench_app.slash import SlashContext


def build_output_style_command() -> LocalCommand:
    return LocalCommand(
        name="output-style",
        description="Switch transcript verbosity (concise / verbose / json)",
        handler=_handle_output_style,
        source="builtin",
        argument_hint="[concise|verbose|json]",
        when_to_use=(
            "Use to dial transcript verbosity up or down, or switch to "
            "machine-readable JSON for scripted runs."
        ),
    )


def _handle_output_style(ctx: "SlashContext", *args: str) -> OnDoneResult:
    if not args:
        return on_done("\n".join(_render_catalogue()), display="user")

    requested = args[0].strip()
    try:
        output_style.set_style(requested)
    except ValueError as exc:
        return on_done(theme.warning(f"  {exc}"), display="system")

    workspace_root = _workspace_root(ctx)
    persisted = False
    if workspace_root is not None:
        save_project_settings(workspace_root, {"output": {"style": requested.lower()}})
        persisted = True

    message = theme.success(
        f"  Output style set to '{output_style.current_style().value}'."
    )
    if persisted:
        message += theme.meta(
            f"  Saved to {workspace_root}/.agentlab/settings.json"
        )
    else:
        message += theme.meta(
            "  (session-only — no workspace bound to persist the setting)"
        )
    return on_done(message, display="user")


def _render_catalogue() -> list[str]:
    active = output_style.current_style().value
    lines = [theme.workspace("Output styles")]
    for style_name in output_style.available_styles():
        marker = "*" if style_name == active else " "
        lines.append(f"  {marker} /output-style {style_name}")
    lines.append("")
    lines.append(theme.meta("  Use /output-style <name> to switch."))
    return lines


def _workspace_root(ctx: "SlashContext") -> Path | None:
    workspace = getattr(ctx, "workspace", None)
    root = getattr(workspace, "root", None) if workspace is not None else None
    return Path(root) if root else None


__all__ = ["build_output_style_command"]
