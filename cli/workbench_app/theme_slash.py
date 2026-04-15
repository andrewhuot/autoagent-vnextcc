"""``/theme`` slash command.

Behaves like Claude Code's equivalent:

* ``/theme`` — list available themes, highlighting the active one.
* ``/theme <name>`` — swap the active palette at runtime and persist the
  choice to ``~/.agentlab/config.json`` so the next session starts with
  the same look.

Persistence uses :func:`cli.settings.save_user_config` (user-global scope)
rather than workspace settings — a theme is a user preference, not a
project convention.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cli.settings import save_user_config
from cli.workbench_app import theme
from cli.workbench_app.commands import LocalCommand, OnDoneResult, on_done

if TYPE_CHECKING:
    from cli.workbench_app.slash import SlashContext


def build_theme_command() -> LocalCommand:
    return LocalCommand(
        name="theme",
        description="Switch the workbench colour theme",
        handler=_handle_theme,
        source="builtin",
        argument_hint="[theme-name]",
        when_to_use=(
            "Use to preview available themes or activate one. Without "
            "arguments, lists all themes with the active one marked."
        ),
    )


def _handle_theme(ctx: "SlashContext", *args: str) -> OnDoneResult:
    if not args:
        return on_done("\n".join(_render_catalogue()), display="user")

    requested = args[0].strip()
    try:
        theme.apply_theme(requested)
    except KeyError as exc:
        return on_done(theme.warning(f"  {exc}"), display="system")

    # Persist the choice so future sessions pick it up. Store under
    # ``theme.name`` to keep the user-config schema namespaced.
    save_user_config({"theme": {"name": requested.lower()}})

    return on_done(
        theme.success(f"  Theme set to '{requested.lower()}'. Saved to ~/.agentlab/config.json."),
        display="user",
    )


def _render_catalogue() -> list[str]:
    active = theme.current_theme_name()
    lines = [theme.workspace("Available themes")]
    for name in theme.available_themes():
        marker = "*" if name == active else " "
        palette = theme.get_theme(name)
        swatches = _swatches(palette)
        lines.append(f"  {marker} /theme {name:<12} {swatches}")
    lines.append("")
    lines.append(theme.meta("  Use /theme <name> to switch."))
    return lines


def _swatches(palette) -> str:
    """Render a small colour preview using the palette's key roles.

    We write literal role helpers so the preview reflects how the theme
    will actually style future output — a swatch string composed ad hoc
    could drift from what ``theme.success`` / ``theme.warning`` emit."""
    # Temporarily apply the palette for the swatch by calling ``stylize``
    # directly; safer than mutating the module palette since this runs
    # during a simple listing.
    return " ".join(
        [
            theme.stylize("●", fg=palette.workspace),
            theme.stylize("●", fg=palette.success),
            theme.stylize("●", fg=palette.warning),
            theme.stylize("●", fg=palette.error),
        ]
    )


__all__ = ["build_theme_command"]
