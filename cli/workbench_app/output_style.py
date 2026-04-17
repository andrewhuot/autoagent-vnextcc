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

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Literal


class OutputStyle(str, Enum):
    """One of the supported verbosity / format modes."""

    CONCISE = "concise"
    VERBOSE = "verbose"
    JSON = "json"


STYLES = Literal["table", "json", "markdown", "terse", "default"]

DEFAULT_STYLE = OutputStyle.VERBOSE
"""Matches the current ad-hoc behaviour — render everything with full
chrome. Users can dial down via ``/output-style concise``."""


_current: OutputStyle = DEFAULT_STYLE

_STYLE_DIRECTIVE_RE = re.compile(
    r'^<agentlab output-style="(?P<style>table|json|markdown|terse|default)">'
)
_TABLE_RULE_RE = re.compile(r"^:?-{3,}:?$")


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


def parse_style_directive(text: str) -> tuple[str, str | None]:
    """Strip a leading model-requested style directive when present."""
    match = _STYLE_DIRECTIVE_RE.match(text)
    if match is None:
        return text, None
    return text[match.end() :], match.group("style")


def apply_style(text: str, style: str) -> str:
    """Apply a non-throwing render hint for a single assistant response."""
    if style == "terse":
        return _apply_terse(text)
    if style == "table":
        # Phase 5a keeps table styling as a validation-only hint: valid
        # tables pass through unchanged, and invalid table requests fall
        # back to the original text unchanged.
        _looks_like_markdown_table(text)
        return text
    if style == "json":
        try:
            json.loads(text)
        except json.JSONDecodeError:
            return text
        return f"```json\n{text}\n```"
    return text


def is_machine_readable() -> bool:
    """``True`` when the current style calls for JSON output.

    Renderers use this to decide whether to emit human-readable chrome
    or a single structured record per turn."""
    return _current is OutputStyle.JSON


def is_verbose() -> bool:
    """``True`` when the current style is verbose. Renderers that fold
    large tool outputs check this before collapsing."""
    return _current is OutputStyle.VERBOSE


def _apply_terse(text: str) -> str:
    lines: list[str] = []
    last_was_blank = False
    for raw_line in text.splitlines():
        compacted = " ".join(raw_line.split())
        if compacted:
            lines.append(compacted)
            last_was_blank = False
            continue
        if not last_was_blank and lines:
            lines.append("")
        last_was_blank = True
    return "\n".join(lines)


def _looks_like_markdown_table(text: str) -> bool:
    lines = text.splitlines()
    if len(lines) < 2 or "|" not in lines[0]:
        return False
    header_cells = [cell.strip() for cell in lines[0].strip().strip("|").split("|")]
    separator_cells = [cell.strip() for cell in lines[1].strip().strip("|").split("|")]
    if (
        not header_cells
        or not separator_cells
        or len(header_cells) != len(separator_cells)
        or any(not cell for cell in header_cells)
        or any(not cell for cell in separator_cells)
    ):
        return False
    return all(_TABLE_RULE_RE.fullmatch(cell) is not None for cell in separator_cells)


__all__ = [
    "DEFAULT_STYLE",
    "OutputStyle",
    "STYLES",
    "apply_style",
    "available_styles",
    "current_style",
    "is_machine_readable",
    "is_verbose",
    "parse_style_directive",
    "reset_style",
    "set_style",
]
