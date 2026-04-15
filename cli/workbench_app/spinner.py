"""Streaming spinner wrapper for slash-command handlers.

The workbench REPL wants Claude-Code-style "thinking" indicators during
long-running subprocess and LLM calls. :class:`StreamingSpinner` layers two
behaviours on top of :class:`cli.progress.PhaseSpinner`:

1. **Composite label.** Spinner frames read ``⠋ <model> · <phase> (2.3s)`` so
   users see which provider is working and what it's doing right now. When no
   model is known, the label collapses to just the phase.
2. **Pane-friendly echo.** ``echo(line)`` clears the spinner frame first so
   transcript output doesn't collide with the animation. In non-TTY modes
   (tests, CI, piped stdout) the wrapper is a silent no-op and echoes fall
   through to the caller-supplied ``echo`` sink — so tests can capture
   transcript lines through ``ctx.echo`` without having to stub a spinner.

Usage::

    with ctx.spinner("building candidate", model="gemini-2.5-pro") as spin:
        for event in stream:
            spin.echo(render(event))
            if event["event"] == "task.started":
                spin.update(event["data"]["title"])
"""

from __future__ import annotations

from types import TracebackType
from typing import Callable

import click

from cli.progress import PhaseSpinner


EchoFn = Callable[[str], None]
"""Fallback echo sink used when the spinner is disabled (non-TTY)."""


class StreamingSpinner:
    """Context-manager wrapper around :class:`PhaseSpinner` with a composed label.

    Thin by design — all animation, locking, and TTY detection lives in
    ``PhaseSpinner``. This wrapper only owns the ``model · phase`` string
    and the echo fall-through so handlers can treat ``ctx.spinner(...)`` as
    a uniform interface regardless of whether they're attached to a real
    terminal.
    """

    def __init__(
        self,
        phase: str,
        *,
        model: str | None = None,
        echo: EchoFn | None = None,
        output_format: str = "text",
    ) -> None:
        self._phase = phase
        self._model = model
        self._fallback_echo = echo if echo is not None else click.echo
        self._inner = PhaseSpinner(
            self._compose_label(phase, model),
            output_format=output_format,
        )

    # ------------------------------------------------------------------ read

    @property
    def phase(self) -> str:
        """The current phase segment of the composed label."""
        return self._phase

    @property
    def model(self) -> str | None:
        """The model prefix, if any — e.g. ``"gemini-2.5-pro"``."""
        return self._model

    @property
    def enabled(self) -> bool:
        """True when the spinner will actually animate (real TTY, text mode)."""
        return self._inner.enabled

    @property
    def label(self) -> str:
        """The full composed label as rendered on screen."""
        return self._compose_label(self._phase, self._model)

    # ---------------------------------------------------------------- write

    def update(self, phase: str) -> None:
        """Swap the phase segment mid-run (e.g. ``parsing envelope``)."""
        self._phase = phase
        self._inner.update(self._compose_label(phase, self._model))

    def echo(self, line: str) -> None:
        """Emit one transcript line without tearing the spinner frame.

        When the inner spinner is animating, delegate to
        :meth:`PhaseSpinner.echo` which clears the current frame and writes
        to stdout. Otherwise route through the caller-supplied echo so
        tests and non-TTY runs still see the line.
        """
        if self._inner.enabled:
            self._inner.echo(line)
        else:
            self._fallback_echo(line)

    # --------------------------------------------------------------- lifecycle

    def __enter__(self) -> "StreamingSpinner":
        self._inner.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._inner.__exit__(exc_type, exc, tb)

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _compose_label(phase: str, model: str | None) -> str:
        """Return ``"<model> · <phase>"`` or the bare phase when no model is set."""
        if model:
            return f"{model} · {phase}"
        return phase


__all__ = ["StreamingSpinner", "EchoFn"]
