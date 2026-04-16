"""Single message display widget for the TUI transcript."""

from __future__ import annotations

from textual.widget import Widget
from textual.widgets import Markdown

from cli.workbench_app.transcript import (
    TranscriptEntry,
    TranscriptRole,
    _ROLE_PREFIX,
)


# Map transcript roles to CSS classes for styling.
_ROLE_CSS_CLASS: dict[TranscriptRole, str] = {
    "user": "role-user",
    "assistant": "role-assistant",
    "system": "role-system",
    "tool": "role-tool",
    "error": "role-error",
    "warning": "role-warning",
    "meta": "role-meta",
}


class MessageWidget(Widget):
    """Renders a single :class:`TranscriptEntry` as a Markdown widget.

    Uses the same pattern as :class:`StreamingMessage` — composes a child
    ``Markdown`` widget for rich rendering of transcript content.

    The CSS class ``role-<role>`` is applied so the theme can style each
    role differently (user = cyan, error = red, etc.).
    """

    def __init__(self, entry: TranscriptEntry, **kwargs: object) -> None:
        css_class = _ROLE_CSS_CLASS.get(entry.role, "role-system")
        super().__init__(classes=css_class, **kwargs)
        self._entry = entry
        self._prefix = _ROLE_PREFIX.get(entry.role, "")

    def compose(self):
        yield Markdown(f"{self._prefix}{self._entry.content}")

    @property
    def entry(self) -> TranscriptEntry:
        return self._entry
