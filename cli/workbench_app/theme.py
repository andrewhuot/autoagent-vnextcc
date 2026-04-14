"""Central palette for the workbench REPL.

T18 lifts the ad-hoc ``click.style(text, fg="red", bold=True)`` calls scattered
across :mod:`cli.workbench_app` into role-named helpers that read from a single
frozen :class:`Palette`. Call sites no longer hard-code colours; they declare
intent (``theme.success(...)``, ``theme.warning(...)``) and the palette owns the
mapping. This keeps the UX consistent and lets a future ``NO_COLOR``-aware path
rebind the palette in one place.

The defaults match the plan's brief:

- Cyan for workspace-scoped identifiers (labels, workspace names, user echo).
- Green for completed / success states.
- Yellow for warnings and cancellations.
- Red (bold) for errors.
- Dim for meta lines / tips / system chrome.

Every helper accepts ``color: bool = True``; passing ``color=False`` returns the
plain text, which is how tests assert the raw string without ANSI escapes.
"""

from __future__ import annotations

from dataclasses import dataclass

import click

__all__ = [
    "PALETTE",
    "Palette",
    "assistant",
    "command_name",
    "error",
    "heading",
    "meta",
    "stylize",
    "success",
    "user",
    "warning",
    "workspace",
]


@dataclass(frozen=True)
class Palette:
    """Role → Click colour name mapping.

    ``None`` means "no colour applied" so the terminal default shows through.
    The palette is frozen so no caller can mutate it at runtime; themes swap
    by rebinding :data:`PALETTE` (future work) rather than editing fields.
    """

    workspace: str = "cyan"
    success: str = "green"
    warning: str = "yellow"
    error: str = "red"
    user: str = "cyan"
    assistant: str | None = None
    command_name: str = "cyan"


PALETTE = Palette()


def stylize(
    text: str,
    *,
    fg: str | None = None,
    bold: bool = False,
    dim: bool = False,
    color: bool = True,
) -> str:
    """Apply styling when ``color`` is true, otherwise return ``text`` verbatim.

    Internal helper used by the role functions below. Exposed so call sites
    that carry their own ``color`` flag (e.g. :func:`render_snapshot`) can
    route through the same branch-free path.
    """

    if not color:
        return text
    if fg is None and not bold and not dim:
        return text
    # Pass only the flags the caller actually asked for. ``click.style`` emits
    # an SGR off-code when it sees ``bold=False`` / ``dim=False`` explicitly;
    # collapsing False → None keeps the escape sequences tight and matches
    # how individual call sites invoke ``click.style`` directly.
    kwargs: dict[str, str | bool] = {}
    if fg is not None:
        kwargs["fg"] = fg
    if bold:
        kwargs["bold"] = True
    if dim:
        kwargs["dim"] = True
    return click.style(text, **kwargs)


def meta(text: str, *, color: bool = True) -> str:
    """Dim line for tips, system chrome, and trailing metadata."""

    return stylize(text, dim=True, color=color)


def workspace(text: str, *, bold: bool = True, color: bool = True) -> str:
    """Cyan label used for workspace names and identifiers in status lines."""

    return stylize(text, fg=PALETTE.workspace, bold=bold, color=color)


def user(text: str, *, bold: bool = True, color: bool = True) -> str:
    """User-side echo (cyan). Kept as a distinct role even though the colour
    matches :func:`workspace` today — a future palette swap may diverge them.
    """

    return stylize(text, fg=PALETTE.user, bold=bold, color=color)


def assistant(text: str, *, color: bool = True) -> str:
    """Assistant-side output. Defaults to terminal colour so pre-styled event
    lines (which already own their rendering) pass through untouched.
    """

    if PALETTE.assistant is None:
        return text
    return stylize(text, fg=PALETTE.assistant, color=color)


def success(text: str, *, bold: bool = False, color: bool = True) -> str:
    """Green line for completion / success banners."""

    return stylize(text, fg=PALETTE.success, bold=bold, color=color)


def warning(text: str, *, bold: bool = False, color: bool = True) -> str:
    """Yellow line for cancellations and non-fatal warnings."""

    return stylize(text, fg=PALETTE.warning, bold=bold, color=color)


def error(text: str, *, bold: bool = True, color: bool = True) -> str:
    """Red bold line for errors. ``bold`` defaults to true because error lines
    read better when the caller doesn't have to remember to flag them.
    """

    return stylize(text, fg=PALETTE.error, bold=bold, color=color)


def command_name(text: str, *, bold: bool = False, color: bool = True) -> str:
    """Cyan line for ``/command`` names in help screens / command popups."""

    return stylize(text, fg=PALETTE.command_name, bold=bold, color=color)


def heading(text: str, *, color: bool = True) -> str:
    """Plain bold heading (e.g. help screen section titles)."""

    return stylize(text, bold=True, color=color)
