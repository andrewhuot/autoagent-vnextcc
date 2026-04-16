"""Base Textual screen for full-screen takeovers.

Adapts the legacy ``Screen`` ABC (synchronous key loop) to Textual's
``Screen`` class. The old contract — ``render_lines()`` + ``handle_key()``
returning ``ScreenResult`` — maps to Textual ``compose()`` + key bindings
+ ``screen.dismiss(result)``.

This base class provides shared infrastructure: a scrollable content area,
a bottom hint bar, and dismiss-on-escape. Concrete screens override
``screen_title``, ``screen_content()``, and add their own key bindings.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Static

from cli.workbench_app.screens.base import ScreenResult, ACTION_CANCEL, ACTION_EXIT


class TUIScreen(Screen[ScreenResult]):
    """Base class for TUI full-screen takeovers.

    Subclasses should:
    - Set ``screen_title`` class variable
    - Override ``screen_content()`` to yield widgets
    - Add key bindings for their specific actions
    - Call ``self.dismiss(ScreenResult(...))`` to exit
    """

    screen_title: str = ""

    DEFAULT_CSS = """
    TUIScreen {
        background: $surface;
    }

    TUIScreen .screen-header {
        dock: top;
        height: 3;
        padding: 1 2;
        background: $panel;
        color: $accent;
        text-style: bold;
    }

    TUIScreen .screen-body {
        height: 1fr;
        padding: 1 2;
    }

    TUIScreen .screen-hint {
        dock: bottom;
        height: 1;
        padding: 0 2;
        background: $panel;
        color: $text-muted;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Back"),
        ("q", "cancel", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Static(self.screen_title or self.__class__.__name__, classes="screen-header")
        with VerticalScroll(classes="screen-body"):
            yield from self.screen_content()
        yield Static(self.hint_text(), classes="screen-hint")

    def screen_content(self) -> ComposeResult:
        """Override to yield the screen's main content widgets."""
        yield Static("(empty screen)")

    def hint_text(self) -> str:
        """Override to customize the bottom hint bar."""
        return "Press [q] or [Esc] to go back"

    def action_cancel(self) -> None:
        """Dismiss the screen with a cancel result."""
        self.dismiss(ScreenResult(action=ACTION_CANCEL))
