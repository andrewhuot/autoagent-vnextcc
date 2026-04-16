"""Single message display widget for the TUI transcript."""

from __future__ import annotations

from textual.widgets import Static

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


class MessageWidget(Static):
    """Renders a single :class:`TranscriptEntry` as a styled Static widget.

    The CSS class ``role-<role>`` is applied so the theme can style each
    role differently (user = cyan, error = red, etc.).
    """

    def __init__(self, entry: TranscriptEntry, **kwargs: object) -> None:
        prefix = _ROLE_PREFIX.get(entry.role, "")
        css_class = _ROLE_CSS_CLASS.get(entry.role, "role-system")
        super().__init__(
            f"{prefix}{entry.content}",
            classes=css_class,
            **kwargs,
        )
        self._entry = entry

    @property
    def entry(self) -> TranscriptEntry:
        return self._entry
