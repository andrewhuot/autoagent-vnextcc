"""Full-screen session picker (``/resume``).

Mirrors Claude Code's ``ResumeConversation`` screen: a scrollable list of
recent sessions. ``j``/``k`` (or ``up``/``down``) navigate, ``enter`` resumes
the highlighted session, ``f`` forks it, and ``q``/``escape`` cancels.

This is a scaffold for T17 — the action values it returns (``"resume"``,
``"fork"``, ``"cancel"``) describe intent rather than executing it. The slash
dispatcher wrapping the screen is responsible for actually loading the
chosen session into the live workbench context.
"""

from __future__ import annotations

import time
from typing import Iterable, Sequence

import click  # noqa: F401

from cli.sessions import Session, SessionStore
from cli.workbench_app import theme
from cli.workbench_app.screens.base import (
    ACTION_CANCEL,
    EchoFn,
    KeyProvider,
    Screen,
    ScreenResult,
)


ACTION_RESUME = "resume"
ACTION_FORK = "fork"


_UP_KEYS = frozenset({"k", "up"})
_DOWN_KEYS = frozenset({"j", "down"})
_RESUME_KEYS = frozenset({"enter", "return"})
_FORK_KEYS = frozenset({"f"})
_CANCEL_KEYS = frozenset({"q", "escape", "ctrl+c"})


def _format_session_row(session: Session, *, selected: bool) -> str:
    updated = session.updated_at or session.started_at
    stamp = (
        time.strftime("%Y-%m-%d %H:%M", time.localtime(updated))
        if updated
        else "-                "
    )
    title = session.title or "(untitled)"
    goal = session.active_goal or ""
    suffix = f" — {goal}" if goal else ""
    prefix = "▶ " if selected else "  "
    line = f"{prefix}{stamp}  {title}{suffix}"
    if selected:
        return theme.workspace(line)
    return line


class ResumeScreen(Screen):
    """Scrollable list of recent sessions for ``/resume``."""

    name = "resume"
    title = "/resume"

    def __init__(
        self,
        sessions: Sequence[Session] | None = None,
        *,
        store: SessionStore | None = None,
        limit: int = 20,
        keys: KeyProvider | Iterable[str] | None = None,
        echo: EchoFn | None = None,
    ) -> None:
        super().__init__(keys=keys, echo=echo)
        if sessions is None:
            if store is None:
                self._sessions: list[Session] = []
            else:
                self._sessions = list(store.list_sessions(limit=limit))
        else:
            self._sessions = list(sessions)
        self._cursor = 0 if self._sessions else -1

    # ------------------------------------------------------------------ api

    @property
    def sessions(self) -> tuple[Session, ...]:
        return tuple(self._sessions)

    @property
    def cursor(self) -> int:
        return self._cursor

    def render_lines(self) -> list[str]:
        if not self._sessions:
            return [theme.meta("  (no sessions found)")]
        return [
            _format_session_row(session, selected=(i == self._cursor))
            for i, session in enumerate(self._sessions)
        ]

    def footer_lines(self) -> list[str]:
        hint = "  [j/k navigate · enter resume · f fork · q cancel]"
        return ["", theme.meta(hint)]

    def handle_key(self, key: str) -> ScreenResult | None:
        if not self._sessions:
            if key in _CANCEL_KEYS or key in _RESUME_KEYS:
                return ScreenResult(
                    action=ACTION_CANCEL,
                    meta_messages=("No previous session to resume.",),
                )
            return None

        if key in _UP_KEYS:
            self._cursor = max(0, self._cursor - 1)
            return None
        if key in _DOWN_KEYS:
            self._cursor = min(len(self._sessions) - 1, self._cursor + 1)
            return None
        if key in _RESUME_KEYS:
            selected = self._sessions[self._cursor]
            return ScreenResult(
                action=ACTION_RESUME,
                value=selected.session_id,
                meta_messages=(f"Resumed session: {selected.title or selected.session_id}",),
            )
        if key in _FORK_KEYS:
            selected = self._sessions[self._cursor]
            return ScreenResult(
                action=ACTION_FORK,
                value=selected.session_id,
                meta_messages=(f"Forked from session: {selected.title or selected.session_id}",),
            )
        if key in _CANCEL_KEYS:
            return ScreenResult(action=ACTION_CANCEL)
        return None


__all__ = [
    "ACTION_FORK",
    "ACTION_RESUME",
    "ResumeScreen",
]
