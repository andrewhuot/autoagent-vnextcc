"""Collapsible tool-call output buffer.

Port of Claude Code's ``CtrlOToExpand``: tool-call output longer than a
threshold (10 lines by default) collapses to a one-line summary with an
optional token count and a "press Ctrl-O to expand" hint. The user toggles
the view by pressing Ctrl-O on the focused block — binding that chord is
the job of the prompt_toolkit layer in T19; this module is the pure state
machine that the key binding will drive.

The class is deliberately append-only plus :meth:`clear`; nothing in here
mutates previously-appended lines. That matches the on-screen invariant
already held by the tool-call block renderer (T08): progress lines are
immutable once emitted, so a collapse/expand toggle is just a re-render
from the same line buffer.

Typical usage::

    buf = CollapsibleOutput()
    for line in streamed_lines:
        buf.append(line)
    if buf.is_collapsible:
        for line in buf.render():      # → single summary line
            echo(line)
    # user presses Ctrl-O …
    buf.toggle()
    for line in buf.render():          # → every line
        echo(line)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from cli.workbench_app import theme


__all__ = [
    "DEFAULT_COLLAPSE_THRESHOLD",
    "CollapsibleOutput",
    "format_summary",
]


DEFAULT_COLLAPSE_THRESHOLD = 10
"""Lines beyond which the buffer folds to its summary."""


@dataclass
class CollapsibleOutput:
    """Append-only line buffer that can fold to a summary line.

    ``collapse_threshold`` controls when the buffer is *collapsible* — not
    when it is collapsed. Below the threshold the buffer always renders in
    full regardless of the :attr:`collapsed` flag; above it the flag wins.
    That split keeps :meth:`toggle` a no-op on small outputs, matching
    Claude Code's behavior where short blocks never show the hint.
    """

    collapse_threshold: int = DEFAULT_COLLAPSE_THRESHOLD
    collapsed: bool = True
    token_count: int | None = None
    _lines: list[str] = field(default_factory=list, repr=False)

    # ------------------------------------------------------------------ write

    def append(self, line: str) -> None:
        """Add one line to the buffer. No normalization is applied."""
        self._lines.append(line)

    def extend(self, lines: Iterable[str]) -> None:
        """Append many lines at once."""
        for line in lines:
            self._lines.append(line)

    def clear(self) -> None:
        """Drop every buffered line (and the collapsed flag stays untouched)."""
        self._lines.clear()

    def set_token_count(self, count: int | None) -> None:
        """Attach a token count that shows up in the collapsed summary."""
        if count is not None and count < 0:
            raise ValueError("token_count must be non-negative")
        self.token_count = count

    # ------------------------------------------------------------------ read

    @property
    def lines(self) -> tuple[str, ...]:
        """Immutable snapshot of the buffered lines in insertion order."""
        return tuple(self._lines)

    @property
    def line_count(self) -> int:
        return len(self._lines)

    @property
    def is_collapsible(self) -> bool:
        """True when the buffer is long enough to warrant a collapse toggle."""
        return len(self._lines) > self.collapse_threshold

    @property
    def is_collapsed(self) -> bool:
        """Effective view state: collapsible *and* the flag is set."""
        return self.is_collapsible and self.collapsed

    # ------------------------------------------------------------------ mutate

    def toggle(self) -> bool:
        """Flip :attr:`collapsed` and return the new value.

        When the buffer is not collapsible (below threshold) the call is a
        no-op and the current value is returned unchanged; that matches the
        Claude Code UX where pressing Ctrl-O on a short block does nothing.
        """
        if not self.is_collapsible:
            return self.collapsed
        self.collapsed = not self.collapsed
        return self.collapsed

    def expand(self) -> None:
        """Force the buffer into the expanded view."""
        self.collapsed = False

    def collapse(self) -> None:
        """Force the buffer into the collapsed view (noop when short)."""
        self.collapsed = True

    # ------------------------------------------------------------------ render

    def render(self, *, color: bool = True) -> list[str]:
        """Return the lines currently visible for the active view state.

        A fresh list is returned so callers can mutate without bleeding into
        the internal buffer. The summary line is styled dim (via :func:`theme.meta`)
        so the enclosing transcript can concatenate without an extra pass.
        """
        if not self.is_collapsed:
            return list(self._lines)
        return [format_summary(len(self._lines), self.token_count, color=color)]

    def summary(self, *, color: bool = True) -> str:
        """Render just the summary line (shortcut used by the tool-call footer)."""
        return format_summary(len(self._lines), self.token_count, color=color)


def format_summary(
    hidden_count: int, token_count: int | None, *, color: bool = True
) -> str:
    """Format the single-line collapse summary shown in place of the body.

    Exposed as a module-level helper so tests assert the exact wording
    without touching a :class:`CollapsibleOutput` instance — and so the
    tool-call block renderer can surface the same summary under a
    never-expanded block when appropriate.
    """
    parts = [f"… {hidden_count} line{'s' if hidden_count != 1 else ''} hidden"]
    if token_count is not None:
        parts.append(_format_tokens(token_count))
    parts.append("press Ctrl-O to expand")
    line = "  " + " · ".join(parts)
    return theme.meta(line, color=color)


def _format_tokens(count: int) -> str:
    if count < 1000:
        return f"{count} tok"
    if count < 1_000_000:
        return f"{count / 1000:.1f}k tok"
    return f"{count / 1_000_000:.1f}M tok"
