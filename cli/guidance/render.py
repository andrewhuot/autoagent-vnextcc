"""Terminal rendering for guidance suggestions.

Kept separate so web/JSON callers can import the engine without pulling
``click`` in. The CLI uses :func:`render_suggestions_block` to append a
short, dismissible list to the status screen; the slash command uses
:func:`render_suggestions_detail` for an expanded view.
"""

from __future__ import annotations

from typing import Iterable

import click

from cli.guidance.types import Suggestion


_SEVERITY_COLORS = {
    "blocker": "red",
    "warn": "yellow",
    "info": "cyan",
}


def _sev_color(severity: str) -> str:
    return _SEVERITY_COLORS.get(severity, "cyan")


def render_suggestions_block(suggestions: Iterable[Suggestion]) -> str:
    """Return a compact multi-line block — one suggestion per line.

    Used by the ``status`` screen. Callers that don't want color at all
    should strip ANSI codes (``click.unstyle``) downstream.
    """
    lines: list[str] = []
    items = list(suggestions)
    if not items:
        return ""
    lines.append(click.style("  Suggestions:", bold=True))
    for suggestion in items:
        color = _sev_color(suggestion.severity)
        bullet = click.style("•", fg=color)
        head = click.style(suggestion.title, fg=color, bold=True)
        tail = ""
        if suggestion.command:
            tail = click.style(f"  ({suggestion.command})", dim=True)
        lines.append(f"  {bullet} {head}{tail}")
        lines.append(f"      {suggestion.body}")
    return "\n".join(lines)


def render_suggestions_detail(suggestions: Iterable[Suggestion]) -> str:
    """Expanded slash-command rendering with IDs for dismissal hints."""
    items = list(suggestions)
    if not items:
        return "  No active suggestions. Nice."
    lines = [click.style("\n  Active Suggestions", bold=True)]
    for suggestion in items:
        color = _sev_color(suggestion.severity)
        lines.append("")
        lines.append(
            f"  {click.style(suggestion.title, fg=color, bold=True)}"
            f"  {click.style('[' + suggestion.id + ']', dim=True)}"
        )
        lines.append(f"    Severity: {click.style(suggestion.severity, fg=color)}")
        if suggestion.command:
            lines.append(f"    Command:  {suggestion.command}")
        if suggestion.href:
            lines.append(f"    Web:      {suggestion.href}")
        lines.append(f"    {suggestion.body}")
    lines.append("")
    lines.append(
        "  Use /suggest dismiss <id> to hide one, /suggest reset to clear history."
    )
    return "\n".join(lines)


__all__ = ["render_suggestions_block", "render_suggestions_detail"]
