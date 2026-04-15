"""Output-style configuration.

Three styles, matching Claude Code's ``/output-style`` vocabulary:

* ``concise``  — tight prose, collapsed tool output, no chrome. Good for
                 experienced users who already know what to expect.
* ``verbose`` — full diagnostics, expanded tool output, session
                 breadcrumbs. Good for onboarding and debugging.
* ``json``    — machine-readable transcript. Every render target emits a
                single JSON object per turn so scripts can consume
                workbench output without string parsing.

The current style is a single shared piece of state because nearly every
renderer needs to consult it. We keep it on a module-level singleton
rather than threading it through every function signature; tests that
need isolation call :func:`reset_style` in a fixture.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class OutputStyle(str, Enum):
    """One of the supported verbosity / format modes."""

    CONCISE = "concise"
    VERBOSE = "verbose"
    JSON = "json"


DEFAULT_STYLE = OutputStyle.VERBOSE
"""Matches the current ad-hoc behaviour — render everything with full
chrome. Users can dial down via ``/output-style concise``."""


_current: OutputStyle = DEFAULT_STYLE


def current_style() -> OutputStyle:
    """Return the active :class:`OutputStyle`."""
    return _current


def set_style(style: OutputStyle | str) -> OutputStyle:
    """Update the active style, accepting either the enum or a raw string.

    Raises :class:`ValueError` for unknown strings so the slash handler
    can surface a specific error rather than falling back silently."""
    global _current
    if isinstance(style, OutputStyle):
        _current = style
    else:
        try:
            _current = OutputStyle(style.lower())
        except ValueError as exc:
            raise ValueError(
                f"Unknown output style: {style!r}. "
                f"Available: {tuple(s.value for s in OutputStyle)}."
            ) from exc
    return _current


def reset_style() -> None:
    """Reset to :data:`DEFAULT_STYLE`. Intended for test teardown."""
    global _current
    _current = DEFAULT_STYLE


def available_styles() -> tuple[str, ...]:
    """Return style names in catalogue order."""
    return tuple(s.value for s in OutputStyle)


def is_machine_readable() -> bool:
    """``True`` when the current style calls for JSON output.

    Renderers use this to decide whether to emit human-readable chrome
    or a single structured record per turn."""
    return _current is OutputStyle.JSON


def is_verbose() -> bool:
    """``True`` when the current style is verbose. Renderers that fold
    large tool outputs check this before collapsing."""
    return _current is OutputStyle.VERBOSE


__all__ = [
    "DEFAULT_STYLE",
    "OutputStyle",
    "available_styles",
    "current_style",
    "is_machine_readable",
    "is_verbose",
    "reset_style",
    "set_style",
]
