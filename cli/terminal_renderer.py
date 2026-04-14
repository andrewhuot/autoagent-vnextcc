"""Small terminal UI primitives shared by CLI surfaces.

AgentLab's CLI is Python-first today, while the target experience borrows
ideas from React/Ink. This module is the adapter layer between those worlds:
callers compose stable terminal regions without depending on a Node runtime,
and a future true Ink sidecar can target the same shapes.
"""

from __future__ import annotations

import math
import os
import shutil
import sys
import textwrap
from collections.abc import Iterable

import click

__all__ = [
    "render_box",
    "render_divider",
    "render_pane",
    "render_progress_bar",
    "render_status_footer",
    "supports_unicode_box",
    "terminal_width",
]


_BLOCKS = (" ", "▏", "▎", "▍", "▌", "▋", "▊", "▉", "█")
_MIN_WIDTH = 24
_DEFAULT_WIDTH = 80


def terminal_width(*, fallback: int = _DEFAULT_WIDTH) -> int:
    """Return a safe terminal width because renderers must work in pipes too."""

    try:
        columns = shutil.get_terminal_size((fallback, 24)).columns
    except OSError:
        columns = fallback
    return max(_MIN_WIDTH, columns)


def _visible_len(text: str) -> int:
    return len(click.unstyle(text))


def _fit(text: str, width: int) -> str:
    """Fit text into a fixed cell so terminal regions do not jitter."""

    width = max(0, width)
    plain = click.unstyle(text)
    if len(plain) <= width:
        return text
    if width <= 1:
        return plain[:width]
    return plain[: width - 1] + "…"


def _plural(count: int, noun: str) -> str:
    suffix = "" if count == 1 else "s"
    return f"{count} {noun}{suffix}"


def _meta(text: str, *, color: bool = True) -> str:
    if not color:
        return text
    return click.style(text, dim=True)


def _success(text: str, *, color: bool = True) -> str:
    if not color:
        return text
    return click.style(text, fg="green")


def _warning(text: str, *, color: bool = True) -> str:
    if not color:
        return text
    return click.style(text, fg="yellow")


def render_progress_bar(
    ratio: float,
    *,
    width: int = 24,
    color: bool = True,
) -> str:
    """Render a fixed-width fractional bar so progress states stay readable.

    The block-segment approach mirrors the useful part of Ink-style progress
    components: callers get a deterministic character width while still
    showing sub-cell progress for streaming phases.
    """

    width = max(0, width)
    if width == 0:
        return ""
    clamped = min(1.0, max(0.0, ratio))
    filled_cells = math.floor(clamped * width)
    filled = _BLOCKS[-1] * filled_cells
    partial = ""
    empty_count = width - filled_cells

    if filled_cells < width:
        remainder = clamped * width - filled_cells
        partial_index = math.floor(remainder * len(_BLOCKS))
        partial = _BLOCKS[partial_index]
        empty_count -= 1

    empty = _BLOCKS[0] * max(0, empty_count)
    if not color:
        return filled + partial + empty

    filled_part = filled + (partial if partial.strip() else "")
    empty_part = ("" if partial.strip() else partial) + empty
    return _success(filled_part, color=color) + _meta(empty_part, color=color)


def render_divider(
    title: str | None = None,
    *,
    width: int | None = None,
    char: str = "─",
    color: bool = True,
) -> str:
    """Render a width-aware divider used to anchor panes and footers."""

    resolved_width = max(1, width or terminal_width())
    if not title:
        return _meta(char * resolved_width, color=color)

    label = f" {title.strip()} "
    label_width = _visible_len(label)
    if label_width >= resolved_width:
        return _meta(_fit(label, resolved_width), color=color)

    remaining = resolved_width - label_width
    left = remaining // 2
    right = remaining - left
    return _meta(f"{char * left}{label}{char * right}", color=color)


def _wrap_body_line(line: str, width: int) -> list[str]:
    if not line:
        return [""]
    wrapped = textwrap.wrap(
        line,
        width=max(1, width),
        replace_whitespace=False,
        drop_whitespace=True,
    )
    return wrapped or [""]


def render_pane(
    title: str,
    body_lines: Iterable[str],
    *,
    width: int | None = None,
    color: bool = True,
    padding: int = 2,
) -> list[str]:
    """Render a titled pane so slash/status surfaces share one structure.

    This is intentionally lighter than a boxed card: the divider gives users
    a clear region boundary while keeping transcript output copyable and
    friendly to narrow terminals.
    """

    resolved_width = max(_MIN_WIDTH, width or terminal_width())
    prefix = " " * max(0, padding)
    content_width = max(1, resolved_width - len(prefix))
    lines = [render_divider(title, width=resolved_width, color=color)]
    for raw_line in body_lines:
        for wrapped in _wrap_body_line(str(raw_line), content_width):
            lines.append(_fit(prefix + wrapped, resolved_width))
    return lines


def supports_unicode_box() -> bool:
    """Return ``True`` when the terminal can render ``╭─╮ │ ╰─╯`` glyphs.

    Non-UTF encodings (cp437, cp1252) mojibake the corners. We gate on the
    detected ``stdout`` encoding so the fallback only kicks in when needed —
    piping to a UTF-8 file still keeps the pretty glyphs.
    """

    encoding = (getattr(sys.stdout, "encoding", None) or "").lower()
    return encoding.startswith("utf")


def render_box(
    body_lines: Iterable[str],
    *,
    title: str | None = None,
    width: int | None = None,
    rounded: bool = True,
    color: bool = True,
    padding: int = 1,
) -> list[str]:
    """Render a bordered box wrapping ``body_lines``.

    Mirrors Claude Code's welcome card — the border recedes (dim grey) while
    the interior content keeps its own styling. ``padding`` controls the
    left/right interior gutter (in columns). When the terminal cannot render
    Unicode corners, falls back to ``+ - |``; ``NO_COLOR`` / ``color=False``
    still produces the box chrome, just without ANSI escapes.

    Returns a list of rendered lines (top border, body lines, bottom border)
    so callers can interleave with other output before echoing.
    """

    resolved_width = max(_MIN_WIDTH, width or terminal_width())
    unicode_ok = supports_unicode_box()
    if rounded and unicode_ok:
        tl, tr, bl, br, horiz, vert = "╭", "╮", "╰", "╯", "─", "│"
    elif unicode_ok:
        tl, tr, bl, br, horiz, vert = "┌", "┐", "└", "┘", "─", "│"
    else:
        tl = tr = bl = br = "+"
        horiz, vert = "-", "|"

    inner_width = max(1, resolved_width - 2 - (2 * padding))
    gutter = " " * padding

    def _chrome(text: str) -> str:
        return text if not color else click.style(text, dim=True)

    def _frame(line: str) -> str:
        plain = click.unstyle(line)
        fill = max(0, inner_width - len(plain))
        return _chrome(vert) + gutter + line + (" " * fill) + gutter + _chrome(vert)

    top_body = horiz * (resolved_width - 2)
    if title:
        label = f" {title.strip()} "
        label_len = len(label)
        if label_len < resolved_width - 4:
            left = 2
            right = (resolved_width - 2) - left - label_len
            top_body = (horiz * left) + label + (horiz * max(0, right))
    top = _chrome(tl + top_body + tr)
    bottom = _chrome(bl + (horiz * (resolved_width - 2)) + br)

    lines: list[str] = [top]
    for raw_line in body_lines:
        text = str(raw_line)
        plain = click.unstyle(text)
        if len(plain) <= inner_width:
            lines.append(_frame(text))
            continue
        # Only wrap the plain representation — text with ANSI escapes is
        # already width-known to the caller. We wrap on the plain form so
        # styled content that overflows degrades gracefully.
        for wrapped in _wrap_body_line(plain, inner_width):
            lines.append(_frame(wrapped))
    lines.append(bottom)
    return lines


def render_status_footer(
    *,
    mode: str,
    shells: int,
    tasks: int,
    width: int | None = None,
    color: bool = True,
) -> list[str]:
    """Render the prompt footer with fixed chrome and live affordance counts."""

    resolved_width = max(_MIN_WIDTH, width or terminal_width())
    status = (
        f"⏵ {mode} permissions on · "
        f"{_plural(shells, 'shell')}, {_plural(tasks, 'task')}"
    )
    return [
        render_divider(width=resolved_width, color=color),
        _warning(_fit(status, resolved_width), color=color),
    ]
