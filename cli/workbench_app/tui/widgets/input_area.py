"""Text input area for the TUI workbench."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Input, Static

from cli.workbench_app.input_router import InputKind, route_user_input
from cli.workbench_app.store import AppState, Store, append_message

if TYPE_CHECKING:
    from cli.workbench_app.tui.slash_adapter import TUISlashAdapter


class InputArea(Widget):
    """Bottom-docked input area with prompt chevron and text input.

    Routes input through :func:`route_user_input` and dispatches slash
    commands via the :class:`TUISlashAdapter`.
    """

    def __init__(
        self,
        store: Store[AppState],
        *,
        slash_adapter: "TUISlashAdapter | None" = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._store = store
        self._input: Input | None = None
        self._slash_adapter = slash_adapter

    @property
    def slash_adapter(self) -> "TUISlashAdapter | None":
        return self._slash_adapter

    @slash_adapter.setter
    def slash_adapter(self, adapter: "TUISlashAdapter | None") -> None:
        self._slash_adapter = adapter

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Static("\u203a", classes="input-chevron")
            self._input = Input(
                placeholder="Type a message, /command, or ? for help",
            )
            yield self._input

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle enter key — route through input router and dispatch."""
        text = event.value.strip()
        if not text:
            return

        # Clear the input immediately for responsiveness.
        if self._input is not None:
            self._input.value = ""

        # Route through the slash adapter if available.
        if self._slash_adapter is not None:
            route = self._slash_adapter.handle_input(text)
            if route.kind == InputKind.EXIT:
                self.app.exit()
            return

        # Fallback: basic routing without adapter.
        route = route_user_input(text)

        if route.kind == InputKind.EXIT:
            self.app.exit()
            return

        if route.kind == InputKind.EMPTY:
            return

        # Default: append as user message.
        self._store.set_state(append_message("user", text))
