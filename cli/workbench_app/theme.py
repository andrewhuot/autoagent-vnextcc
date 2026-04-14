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
    "accent",
    "accept_mode",
    "assistant",
    "border",
    "command_name",
    "danger_mode",
    "error",
    "format_mode",
    "heading",
    "meta",
    "plan_mode",
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
    plan_mode: str = "cyan"
    accept_mode: str = "green"
    danger_mode: str = "red"
    # Bright turquoise-blue accent used for the rounded input chevron and
    # Claude-Code-style chrome. Stored as a 256-colour index so 256-colour and
    # 16M-colour terminals both render it cleanly; the int routes through
    # ``click.style(fg=45)`` which Click forwards as an SGR ``38;5;45`` sequence.
    prompt_accent: int = 45
    # Dimmed grey used for the rounded box chrome (welcome card, input border).
    # Rendered via ``stylize(dim=True)``; kept as a field so a future theme
    # can override without touching call sites.
    border: str | None = None


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


def plan_mode(text: str, *, color: bool = True) -> str:
    """Color used for the plan-mode permission indicator."""

    return stylize(text, fg=PALETTE.plan_mode, color=color)


def accept_mode(text: str, *, color: bool = True) -> str:
    """Color used for accept-edits permission indicators."""

    return stylize(text, fg=PALETTE.accept_mode, color=color)


def danger_mode(text: str, *, color: bool = True) -> str:
    """Emphasized color used for bypass-style permission indicators."""

    return stylize(text, fg=PALETTE.danger_mode, bold=True, color=color)


def accent(text: str, *, bold: bool = True, color: bool = True) -> str:
    """Turquoise-blue accent used for the rounded input chevron and key chrome.

    Mirrors the blue highlight on the ``claude-code-ui-overhaul`` branch
    theming cue. The palette uses a 256-colour index (``45``) so the result
    stays readable even on terminals that only advertise 256-colour support.
    """

    return stylize(text, fg=PALETTE.prompt_accent, bold=bold, color=color)


def border(text: str, *, color: bool = True) -> str:
    """Chrome colour for rounded-box borders and divider rules.

    Defaults to the terminal's dim-grey so the border recedes behind the
    content it frames. A future palette swap can point this at a fg colour
    without changing call sites.
    """

    if PALETTE.border is None:
        return stylize(text, dim=True, color=color)
    return stylize(text, fg=PALETTE.border, color=color)


def format_mode(mode: str, *, color: bool = True) -> str:
    """Render a permission mode with a Claude-Code-style label.

    Unknown modes fall back to the raw mode text, which keeps stale settings
    readable without crashing startup.
    """
    from cli.permissions import MODE_DISPLAY

    symbol, title, role = MODE_DISPLAY.get(mode, ("", mode, "default"))
    text = f"{symbol} {title}".strip()
    stylers = {
        "plan": plan_mode,
        "accept": accept_mode,
        "danger": danger_mode,
    }
    styler = stylers.get(role)
    return styler(text, color=color) if styler is not None else text
