"""Permission dialog as a Textual ModalScreen.

Port of ``cli.workbench_app.permission_dialog.request_permission()`` — the
blocking ``prompter()`` call is replaced by a modal overlay with buttons.
Returns :class:`DialogOutcome` via ``screen.dismiss()``.
"""

from __future__ import annotations

from typing import Any, Mapping

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from cli.workbench_app.permission_dialog import (
    DialogChoice,
    DialogOutcome,
)


class PermissionDialog(ModalScreen[DialogOutcome]):
    """Modal permission dialog with approve / session / persist / deny buttons.

    Usage::

        outcome = await self.app.push_screen_wait(
            PermissionDialog(tool_name="Bash", preview="rm -rf /tmp/test")
        )
    """

    DEFAULT_CSS = """
    PermissionDialog {
        align: center middle;
    }

    PermissionDialog > Vertical {
        width: 60;
        height: auto;
        max-height: 20;
        border: round $accent;
        background: $panel;
        padding: 1 2;
    }

    PermissionDialog .perm-title {
        text-style: bold;
        color: $warning;
        margin-bottom: 1;
    }

    PermissionDialog .perm-preview {
        color: $text;
        margin-bottom: 1;
        padding: 0 2;
    }

    PermissionDialog .perm-buttons {
        height: auto;
        margin-top: 1;
    }

    PermissionDialog Button {
        margin: 0 1;
    }
    """

    def __init__(
        self,
        tool_name: str = "",
        preview: str = "",
        *,
        tool: Any | None = None,
        tool_input: Mapping[str, Any] | None = None,
        include_persist: bool = True,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._tool_name = tool_name
        self._preview = preview
        self._tool = tool
        self._tool_input = tool_input or {}
        self._include_persist = include_persist

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(
                f"Permission requested: {self._tool_name}",
                classes="perm-title",
            )
            if self._preview:
                yield Static(self._preview, classes="perm-preview")

            with Horizontal(classes="perm-buttons"):
                yield Button("[a] Approve", id="approve", variant="success")
                yield Button("[s] Session", id="session", variant="primary")
                if self._include_persist:
                    yield Button("[p] Persist", id="persist", variant="warning")
                yield Button("[d] Deny", id="deny", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        pattern = self._session_pattern()

        if button_id == "approve":
            outcome = DialogOutcome(
                choice=DialogChoice.APPROVE,
                allow=True,
                persist_rule=None,
                persist_scope=None,
            )
        elif button_id == "session":
            outcome = DialogOutcome(
                choice=DialogChoice.APPROVE_SESSION,
                allow=True,
                persist_rule=pattern,
                persist_scope="session",
            )
        elif button_id == "persist":
            outcome = DialogOutcome(
                choice=DialogChoice.APPROVE_PERSIST,
                allow=True,
                persist_rule=pattern,
                persist_scope="settings",
            )
        else:
            outcome = DialogOutcome(
                choice=DialogChoice.DENY,
                allow=False,
                persist_rule=None,
                persist_scope=None,
            )

        self.dismiss(outcome)

    def _session_pattern(self) -> str:
        """Compute the pattern for session/persist approval."""
        if self._tool is not None:
            from cli.workbench_app.permission_dialog import _session_pattern_for
            return _session_pattern_for(self._tool, self._tool_input)
        return f"tool:{self._tool_name}:*"

    def key_a(self) -> None:
        """Keyboard shortcut: approve."""
        self.query_one("#approve", Button).press()

    def key_s(self) -> None:
        """Keyboard shortcut: session."""
        self.query_one("#session", Button).press()

    def key_p(self) -> None:
        """Keyboard shortcut: persist."""
        try:
            self.query_one("#persist", Button).press()
        except Exception:
            pass  # persist button may not exist

    def key_d(self) -> None:
        """Keyboard shortcut: deny."""
        self.query_one("#deny", Button).press()

    def key_escape(self) -> None:
        """Escape key: deny."""
        self.key_d()
