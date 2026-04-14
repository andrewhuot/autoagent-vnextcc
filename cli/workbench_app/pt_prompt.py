"""prompt_toolkit-backed input provider for the workbench REPL.

Wraps a ``prompt_toolkit.PromptSession`` with the three Claude-Code-style
chrome pieces the plain ``input()`` loop couldn't offer:

- a slash-command completion popup driven by
  :class:`cli.workbench_app.completer.SlashCommandCompleter`,
- a Unicode ``╭─╮ / ╰─╯`` border rendered around the input line, and
- a ``shift+tab`` key binding that cycles the active permission mode
  (``default`` → ``acceptEdits`` → ``plan`` → ``bypass``),
  persisting the choice to ``.agentlab/settings.json`` when a workspace
  is present.

Kept in its own module so the rest of :mod:`cli.workbench_app` (which runs
in headless tests) does not pay the prompt_toolkit import cost. The only
module-level dependency is the stdlib; prompt_toolkit is imported lazily
inside :func:`build_prompt_input_provider`.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from typing import Any, Callable

from cli.permissions import (
    DEFAULT_PERMISSION_MODE,
    update_workspace_settings,
)
from cli.workbench_app import theme
from cli.workbench_app.commands import CommandRegistry
from cli.workbench_app.completer import SlashCommandCompleter

InputProvider = Callable[[str], str]
EchoFn = Callable[[str], None]

__all__ = [
    "PROMPT_PERMISSION_MODE_CYCLE",
    "WorkbenchPromptState",
    "build_prompt_input_provider",
    "cycle_permission_mode",
]

PROMPT_PERMISSION_MODE_CYCLE = ("default", "acceptEdits", "plan", "bypass")
"""Visible shift-tab cycle; ``dontAsk`` remains accepted from settings."""


@dataclass
class WorkbenchPromptState:
    """Mutable state shared between prompt keybindings and the loop.

    The prompt_toolkit key handlers can't return data back to the caller,
    so instead they mutate this object. The loop reads the current mode
    after each turn to re-render the footer accordingly.
    """

    workspace: Any | None = None
    mode: str = DEFAULT_PERMISSION_MODE
    cycle_count: int = 0
    _persisted_failed: bool = field(default=False, repr=False)

    def persist(self) -> None:
        """Best-effort persistence of ``mode`` into workspace settings.

        Failures are swallowed so a read-only settings dir can't break
        the REPL — a flag is set so the loop can surface a warning once.
        """
        root = getattr(self.workspace, "root", None)
        if root is None:
            return
        try:
            update_workspace_settings({"permissions": {"mode": self.mode}}, root=root)
        except Exception:
            self._persisted_failed = True


def cycle_permission_mode(current: str) -> str:
    """Return the next permission mode in the canonical cycle.

    Extracted so it can be unit-tested without a prompt_toolkit session.
    Unknown modes collapse to the default so users can always escape a
    stale settings value.
    """
    if current == "dontAsk":
        return DEFAULT_PERMISSION_MODE
    try:
        idx = PROMPT_PERMISSION_MODE_CYCLE.index(current)
    except ValueError:
        return DEFAULT_PERMISSION_MODE
    return PROMPT_PERMISSION_MODE_CYCLE[
        (idx + 1) % len(PROMPT_PERMISSION_MODE_CYCLE)
    ]


def _terminal_width(default: int = 80) -> int:
    """Return the current terminal width clamped to a sensible range."""
    try:
        cols = shutil.get_terminal_size((default, 20)).columns
    except Exception:
        cols = default
    return max(20, min(cols, 160))


def _render_top_border(echo: EchoFn) -> None:
    width = _terminal_width()
    echo(theme.meta("─" * width))


def _render_bottom_border(echo: EchoFn) -> None:
    width = _terminal_width()
    echo(theme.meta("─" * width))


def build_prompt_input_provider(
    registry: CommandRegistry,
    state: WorkbenchPromptState,
    *,
    echo: EchoFn,
) -> InputProvider:
    """Return an :data:`InputProvider` backed by prompt_toolkit.

    Raises :class:`RuntimeError` when prompt_toolkit is unavailable — the
    caller is expected to fall back to :func:`cli.workbench_app.app._default_input_provider`.
    """
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.formatted_text import FormattedText
        from prompt_toolkit.history import InMemoryHistory
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.shortcuts import CompleteStyle
    except ImportError as exc:  # pragma: no cover — prompt_toolkit is a hard dep
        raise RuntimeError("prompt_toolkit is required for the interactive prompt") from exc

    completer = SlashCommandCompleter(registry)
    history = InMemoryHistory()
    bindings = KeyBindings()

    @bindings.add("s-tab")
    def _cycle_mode(event: Any) -> None:  # pragma: no cover — requires real PT app
        state.mode = cycle_permission_mode(state.mode)
        state.cycle_count += 1
        state.persist()
        event.app.invalidate()

    @bindings.add("/")
    def _open_slash_menu(event: Any) -> None:  # pragma: no cover — needs real PT app
        """Show the slash-command popup as soon as the user types ``/``.

        ``complete_while_typing=True`` only re-runs the completer when
        existing completions have to be refreshed — it does not kick the
        menu open on the first trigger character. We fire
        ``start_completion`` explicitly so the dropdown appears the moment
        a slash lands on an empty line, matching Claude Code's UX.
        """
        buf = event.current_buffer
        buf.insert_text("/")
        if buf.document.text_before_cursor == "/":
            buf.start_completion(select_first=False)

    def _bottom_toolbar() -> Any:
        label = theme.format_mode(state.mode, color=False)
        return FormattedText(
            [("class:toolbar", f"{label} permissions on · shift+tab to cycle")]
        )

    session: Any = PromptSession(
        completer=completer,
        complete_while_typing=True,
        complete_style=CompleteStyle.COLUMN,
        reserve_space_for_menu=8,
        key_bindings=bindings,
        bottom_toolbar=_bottom_toolbar,
        mouse_support=False,
        history=history,
        enable_history_search=True,
    )

    def provider(prompt_text: str) -> str:
        _render_top_border(echo)
        try:
            raw = session.prompt(prompt_text)
        finally:
            _render_bottom_border(echo)
        return raw

    return provider
