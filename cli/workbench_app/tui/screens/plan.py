"""Plan review screen for the TUI workbench.

Port of ``cli.workbench_app.screens.plan`` — displays the current
coordinator plan for review.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.widgets import Markdown, Static

from cli.workbench_app.screens.base import ACTION_EXIT, ScreenResult
from cli.workbench_app.tui.screens.base import TUIScreen


class PlanScreen(TUIScreen):
    """Full-screen plan review.

    Displays the current plan in a scrollable markdown view.
    Press ``q`` or ``Esc`` to close.
    """

    screen_title = "/plan — Current Plan"

    BINDINGS = [
        ("escape", "cancel", "Back"),
        ("q", "cancel", "Back"),
        ("a", "approve", "Approve"),
    ]

    def __init__(
        self,
        plan_text: str = "",
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._plan_text = plan_text

    def screen_content(self) -> ComposeResult:
        if not self._plan_text:
            yield Static("[dim]No plan available[/]")
            yield Static("")
            yield Static("Run a workflow command (e.g. [bold]/build[/]) to generate a plan.")
            return

        yield Markdown(self._plan_text)

    def hint_text(self) -> str:
        return "Press [a] to approve, [q]/[Esc] to close"

    def action_approve(self) -> None:
        self.dismiss(ScreenResult(
            action="approve",
            meta_messages=("Plan approved",),
        ))
