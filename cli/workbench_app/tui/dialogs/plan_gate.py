"""Plan-mode approval gate as a Textual ModalScreen.

Port of ``cli.workbench_app.plan_gate.PlanGate`` — the blocking
``prompt_fn`` call is replaced by a modal overlay with approve/reject/edit
buttons. Returns :class:`PlanGateDecision` via ``screen.dismiss()``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Markdown, Static


class PlanDecision(str, Enum):
    """User's decision on a proposed plan."""
    APPROVE = "approved"
    ABORT = "aborted"
    EDIT = "edit"


@dataclass(frozen=True)
class PlanGateDecision:
    """Result from the plan gate dialog."""
    decision: PlanDecision
    edit_text: str = ""


class PlanGateDialog(ModalScreen[PlanGateDecision]):
    """Modal dialog showing a proposed coordinator plan for approval.

    Displays the plan content and offers approve / abort / edit options.

    Usage::

        decision = await self.app.push_screen_wait(
            PlanGateDialog(plan_text="Worker roster: ...")
        )
    """

    DEFAULT_CSS = """
    PlanGateDialog {
        align: center middle;
    }

    PlanGateDialog > Vertical {
        width: 70;
        height: auto;
        max-height: 30;
        border: round $accent;
        background: $panel;
        padding: 1 2;
    }

    PlanGateDialog .plan-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }

    PlanGateDialog .plan-content {
        height: auto;
        max-height: 15;
        overflow-y: auto;
        margin-bottom: 1;
        padding: 0 1;
    }

    PlanGateDialog .plan-edit-input {
        display: none;
        margin-bottom: 1;
    }

    PlanGateDialog .plan-buttons {
        height: auto;
        margin-top: 1;
    }

    PlanGateDialog Button {
        margin: 0 1;
    }
    """

    def __init__(
        self,
        plan_text: str = "",
        *,
        title: str = "Plan Review",
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._plan_text = plan_text
        self._title = title
        self._edit_mode = False

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(f"\u2699 {self._title}", classes="plan-title")
            yield Markdown(self._plan_text, classes="plan-content")
            yield Input(
                placeholder="Enter refinement instructions...",
                classes="plan-edit-input",
                id="edit-input",
            )
            with Horizontal(classes="plan-buttons"):
                yield Button("[y] Approve", id="approve", variant="success")
                yield Button("[n] Abort", id="abort", variant="error")
                yield Button("[e] Edit", id="edit", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id

        if button_id == "approve":
            self.dismiss(PlanGateDecision(decision=PlanDecision.APPROVE))
        elif button_id == "abort":
            self.dismiss(PlanGateDecision(decision=PlanDecision.ABORT))
        elif button_id == "edit":
            if not self._edit_mode:
                self._edit_mode = True
                edit_input = self.query_one("#edit-input")
                edit_input.display = True
                edit_input.focus()
            else:
                edit_input = self.query_one("#edit-input", Input)
                text = edit_input.value.strip()
                if text:
                    self.dismiss(PlanGateDecision(
                        decision=PlanDecision.EDIT,
                        edit_text=text,
                    ))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Submit edit text on enter."""
        text = event.value.strip()
        if text:
            self.dismiss(PlanGateDecision(
                decision=PlanDecision.EDIT,
                edit_text=text,
            ))

    def key_y(self) -> None:
        if not self._edit_mode:
            self.dismiss(PlanGateDecision(decision=PlanDecision.APPROVE))

    def key_n(self) -> None:
        if not self._edit_mode:
            self.dismiss(PlanGateDecision(decision=PlanDecision.ABORT))

    def key_e(self) -> None:
        if not self._edit_mode:
            self.query_one("#edit", Button).press()

    def key_escape(self) -> None:
        self.dismiss(PlanGateDecision(decision=PlanDecision.ABORT))
