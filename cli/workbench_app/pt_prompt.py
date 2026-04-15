"""prompt_toolkit-backed input provider for the workbench REPL.

Wraps a ``prompt_toolkit.PromptSession`` with the three Claude-Code-style
chrome pieces the plain ``input()`` loop couldn't offer:

- a slash-command completion popup driven by
  :class:`cli.workbench_app.completer.SlashCommandCompleter`,
- prompt-owned compact footer chrome that stays visible while input is live,
  without pre-printing half of a fake input box, and
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
from cli.workbench_app.output_collapse import TranscriptViewState

InputProvider = Callable[[str], str]
EchoFn = Callable[[str], None]

__all__ = [
    "PROMPT_PERMISSION_MODE_CYCLE",
    "WorkbenchPromptState",
    "build_prompt_input_provider",
    "cycle_permission_mode",
    "render_bottom_toolbar",
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
    transcript_view: TranscriptViewState = field(default_factory=TranscriptViewState)
    transcript_view_cycles: int = 0
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


def _fit_toolbar(text: str, width: int) -> str:
    """Fit toolbar text into one terminal row without wrapping."""
    clean = " ".join(text.split())
    if width <= 0 or len(clean) <= width:
        return clean
    if width <= 1:
        return clean[:width]
    return clean[: width - 1].rstrip() + "…"


def render_bottom_toolbar(mode: str, *, width: int | None = None) -> str:
    """Return the single-line prompt-owned toolbar for the live TTY path.

    Claude Code keeps the bottom chrome compact: permission mode first,
    then only the keyboard affordances that fit. Narrow terminals get a
    shorter one-row variant so prompt_toolkit never reserves a surprise
    second toolbar row at the bottom of the screen.
    """
    resolved_width = width if width is not None else _terminal_width()
    label = theme.format_mode(mode, color=False)
    variants = (
        f"{label} permissions on · shift+tab to cycle · ? shortcuts · / commands · ctrl+t transcript",
        f"{label} permissions on · shift+tab · ? shortcuts · / commands",
        f"{label} permissions on · shift+tab",
        f"{label} permissions on",
    )
    for variant in variants:
        padded = f"  {variant}"
        if len(padded) <= resolved_width:
            return padded
    return _fit_toolbar(f"  {variants[-1]}", resolved_width)


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
        from prompt_toolkit.formatted_text import ANSI, FormattedText
        from prompt_toolkit.filters import Condition
        from prompt_toolkit.history import InMemoryHistory
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.shortcuts import CompleteStyle
        from prompt_toolkit.styles import Style
    except ImportError as exc:  # pragma: no cover — prompt_toolkit is a hard dep
        raise RuntimeError("prompt_toolkit is required for the interactive prompt") from exc

    workspace_root = None
    try:
        workspace_root = getattr(state.workspace, "root", None)
    except Exception:  # pragma: no cover - defensive attribute access
        workspace_root = None
    completer = SlashCommandCompleter(registry, workspace_root=workspace_root)
    history = InMemoryHistory()
    bindings = KeyBindings()

    @bindings.add("s-tab")
    def _cycle_mode(event: Any) -> None:  # pragma: no cover — requires real PT app
        state.mode = cycle_permission_mode(state.mode)
        state.cycle_count += 1
        state.persist()
        event.app.invalidate()

    @bindings.add("c-t")
    def _toggle_transcript(event: Any) -> None:  # pragma: no cover — requires real PT app
        state.transcript_view.toggle()
        state.transcript_view_cycles += 1
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

    session: Any

    @Condition
    def _complete_for_slash_commands() -> bool:
        """Reserve completion-menu rows only while slash input is active.

        ``PromptSession`` uses ``complete_while_typing`` to decide whether the
        input window needs at least ``reserve_space_for_menu`` rows. Keeping it
        always-on makes the idle prompt float above the bottom toolbar. Claude
        Code only swaps footer space for suggestions when suggestions are
        visible, so we do the same for slash-command input.
        """
        try:
            text = session.default_buffer.text
        except Exception:
            return False
        return text.lstrip().startswith("/")

    def _bottom_toolbar() -> Any:
        return FormattedText(
            [("class:toolbar", render_bottom_toolbar(state.mode))]
        )

    session = PromptSession(
        completer=completer,
        complete_while_typing=_complete_for_slash_commands,
        complete_style=CompleteStyle.COLUMN,
        reserve_space_for_menu=6,
        key_bindings=bindings,
        bottom_toolbar=_bottom_toolbar,
        mouse_support=False,
        history=history,
        enable_history_search=True,
        style=Style.from_dict(
            {
                "bottom-toolbar": "noreverse",
                "bottom-toolbar.text": "noreverse",
                "toolbar": "noreverse ansigray",
            }
        ),
    )

    def provider(prompt_text: str) -> str:
        # Style the chevron amber so it matches Claude Code's accent. We wrap
        # the styled string in ``ANSI`` so prompt_toolkit respects the SGR
        # escapes — otherwise they render as literal ``\x1b[...]`` text.
        styled_prompt = ANSI(theme.accent(prompt_text))
        return session.prompt(styled_prompt)

    return provider
