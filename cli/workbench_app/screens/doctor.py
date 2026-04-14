"""Full-screen doctor takeover.

Mirrors Claude Code's ``Doctor`` screen from ``src/screens/Doctor.tsx``: the
screen renders the output of the ``doctor`` Click subcommand in a dedicated
panel and waits for the user to press ``q``/``enter``/``escape`` before
returning to the transcript.

The scaffold delegates all diagnostic logic to the existing
``agentlab doctor`` subcommand via the :data:`cli.workbench_app.slash.ClickInvoker`
seam. This means the screen works end-to-end today while still matching the
base-class contract the prompt_toolkit wiring in T16 will plug into.
"""

from __future__ import annotations

from typing import Callable, Iterable

import click

from cli.workbench_app.screens.base import (
    ACTION_EXIT,
    EchoFn,
    KeyProvider,
    Screen,
    ScreenResult,
)


DoctorRunner = Callable[[], str]
"""Callable that returns the rendered doctor output as a string."""


_EXIT_KEYS = frozenset({"q", "escape", "enter", "ctrl+c"})


def _default_doctor_runner() -> str:
    """Invoke ``agentlab doctor`` through the shared Click invoker seam."""
    # Imported lazily so test environments that stub the runner don't pay the
    # cost of importing the full CLI tree.
    from cli.workbench_app.slash import _default_click_invoker

    return _default_click_invoker("doctor")


class DoctorScreen(Screen):
    """Renders ``agentlab doctor`` output in a full-screen panel."""

    name = "doctor"
    title = "/doctor"

    def __init__(
        self,
        *,
        runner: DoctorRunner | None = None,
        keys: KeyProvider | Iterable[str] | None = None,
        echo: EchoFn | None = None,
    ) -> None:
        super().__init__(keys=keys, echo=echo)
        self._runner: DoctorRunner = runner if runner is not None else _default_doctor_runner
        self._output: str | None = None
        self._error: str | None = None

    def render_lines(self) -> list[str]:
        if self._output is None and self._error is None:
            try:
                self._output = self._runner()
            except Exception as exc:  # Failed invocation still paints something.
                self._error = str(exc)

        if self._error is not None:
            return [
                click.style(f"  Error running doctor: {self._error}", fg="red", bold=True)
            ]

        assert self._output is not None
        if not self._output.strip():
            return [click.style("  (doctor produced no output)", dim=True)]
        return self._output.splitlines()

    def footer_lines(self) -> list[str]:
        return [
            "",
            click.style("  [q/esc/enter to close]", dim=True),
        ]

    def handle_key(self, key: str) -> ScreenResult | None:
        if key in _EXIT_KEYS:
            return ScreenResult(action=ACTION_EXIT)
        return None


__all__ = ["DoctorRunner", "DoctorScreen"]
