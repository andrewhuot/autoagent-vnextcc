"""Base class for workbench full-screen takeovers.

The design intentionally stays synchronous and minimal: key input arrives via
an injectable :data:`KeyProvider` (``Callable[[], str]``), rendering goes
through an injectable ``echo`` function, and the :meth:`Screen.run` loop is a
plain while-loop. This keeps the scaffold testable today without a TTY and
leaves a clean seam for the prompt_toolkit full-screen :class:`Application`
wiring planned for T16 — at that point ``run()`` can be overridden to bind
real key bindings while preserving the same :class:`ScreenResult` contract.

Transcript restoration contract
-------------------------------
A screen **does not** write to the enclosing :class:`cli.workbench_app.transcript.Transcript`
directly. Instead it:

1. Paints its own lines via ``self._echo`` while active — the caller is expected
   to visually separate these by clearing or scrolling (real terminal handling
   lands in T16).
2. On exit, returns a :class:`ScreenResult` carrying ``meta_messages`` that the
   enclosing :class:`cli.workbench_app.slash.dispatch` layer can route back into
   the transcript via the ``onDone(meta_messages=…)`` protocol.

This keeps the transcript the single source of truth for the session log while
letting screens own the screen.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator

import click


ACTION_EXIT = "exit"
"""Standard action used by screens that simply close without a payload."""

ACTION_CANCEL = "cancel"
"""Standard action used by screens whose user dismissed the picker."""


KeyProvider = Callable[[], str]
"""Callable returning the next keystroke.

A keystroke is a short symbolic string — a single character (``"j"``,
``"q"``), a named key (``"enter"``, ``"escape"``, ``"up"``, ``"down"``), or a
chord (``"ctrl+c"``). The stub loop treats keys as opaque strings; individual
screens normalize aliases they care about.

Contract matches :data:`cli.workbench_app.app.InputProvider` in spirit:
raising :class:`EOFError` or :class:`KeyboardInterrupt` terminates the screen
with :data:`ACTION_CANCEL`.
"""

EchoFn = Callable[[str], None]
"""One-line echo sink. Defaults to :func:`click.echo`."""


@dataclass(frozen=True)
class ScreenResult:
    """Value returned from :meth:`Screen.run`.

    ``action`` is a screen-defined verb (``"exit"``, ``"resume"``, ``"fork"``,
    ``"show"`` …) that the caller dispatches on. ``value`` carries an optional
    payload keyed to that action (e.g. a session id or skill slug).
    ``meta_messages`` are dim transcript lines the caller should surface via
    :func:`cli.workbench_app.commands.on_done` once the screen closes.
    """

    action: str
    value: Any = None
    meta_messages: tuple[str, ...] = field(default_factory=tuple)


def iter_keys(keys: Iterable[str]) -> KeyProvider:
    """Wrap an iterable so it satisfies :data:`KeyProvider`.

    Convenience for tests: ``screen.run(keys=iter_keys(["j", "enter"]))``.
    Exhausting the iterable raises :class:`EOFError`, which
    :meth:`Screen.run` translates into a cancel result — this keeps tests
    honest about specifying every key the loop will consume.
    """
    iterator: Iterator[str] = iter(keys)

    def _provider() -> str:
        try:
            return next(iterator)
        except StopIteration as exc:
            raise EOFError from exc

    return _provider


class Screen(ABC):
    """Abstract base class for full-screen takeovers.

    Subclasses implement :meth:`render_lines` (what to paint) and
    :meth:`handle_key` (how to react to a key, returning a
    :class:`ScreenResult` to exit). The default :meth:`run` loop paints,
    reads keys from :data:`KeyProvider`, dispatches to :meth:`handle_key`, and
    repaints after any key that did not terminate the screen.

    Subclasses typically declare ``name`` and ``title`` class attributes so
    the caller can announce the takeover (``"Opened /doctor"``) without
    duplicating strings.
    """

    name: str = ""
    title: str = ""

    def __init__(
        self,
        *,
        keys: KeyProvider | Iterable[str] | None = None,
        echo: EchoFn | None = None,
    ) -> None:
        self._keys: KeyProvider = self._resolve_keys(keys)
        self._echo: EchoFn = echo if echo is not None else click.echo

    # ------------------------------------------------------------------ api

    def run(self) -> ScreenResult:
        """Paint the screen, read keys, dispatch — block until a result.

        Any :class:`EOFError` or :class:`KeyboardInterrupt` raised by the
        key provider is translated into :data:`ACTION_CANCEL` so the caller
        always gets a well-formed :class:`ScreenResult`.
        """
        self._paint()
        while True:
            try:
                key = self._keys()
            except EOFError:
                return ScreenResult(action=ACTION_CANCEL)
            except KeyboardInterrupt:
                return ScreenResult(action=ACTION_CANCEL)

            result = self.handle_key(self._normalize_key(key))
            if result is not None:
                return result
            self._paint()

    # ------------------------------------------------------------------ abstract

    @abstractmethod
    def render_lines(self) -> list[str]:
        """Return the lines to paint for the current screen state."""

    @abstractmethod
    def handle_key(self, key: str) -> ScreenResult | None:
        """Process one normalized key. Return a result to exit, ``None`` to stay."""

    # ------------------------------------------------------------------ hooks

    def header_lines(self) -> list[str]:
        """Optional header painted before :meth:`render_lines`. Default is empty."""
        if self.title:
            return [click.style(self.title, fg="cyan", bold=True), ""]
        return []

    def footer_lines(self) -> list[str]:
        """Optional footer painted after :meth:`render_lines`. Default is empty."""
        return []

    # ------------------------------------------------------------------ internal

    def _paint(self) -> None:
        for line in self.header_lines():
            self._echo(line)
        for line in self.render_lines():
            self._echo(line)
        for line in self.footer_lines():
            self._echo(line)

    @staticmethod
    def _normalize_key(key: str) -> str:
        """Lower-case named keys so subclasses can match case-insensitively.

        Single-character literal keys are preserved verbatim so screens that
        want to distinguish ``"k"`` vs ``"K"`` can still do so.
        """
        if len(key) > 1:
            return key.lower()
        return key

    @staticmethod
    def _resolve_keys(
        keys: KeyProvider | Iterable[str] | None,
    ) -> KeyProvider:
        if keys is None:
            def _no_keys() -> str:
                raise EOFError
            return _no_keys
        if callable(keys):
            return keys  # type: ignore[return-value]
        return iter_keys(keys)


__all__ = [
    "ACTION_CANCEL",
    "ACTION_EXIT",
    "EchoFn",
    "KeyProvider",
    "Screen",
    "ScreenResult",
    "iter_keys",
]
