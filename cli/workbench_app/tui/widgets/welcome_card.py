"""Startup welcome card for the TUI workbench."""

from __future__ import annotations

import os

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static

from cli.workbench_app.store import AppState, Store


class WelcomeCard(Container):
    """Branded welcome card displayed on startup.

    Mirrors the Claude Code-style rounded welcome box from the legacy
    ``_render_banner()`` in ``app.py``: version, cwd, status, and hints.
    """

    def __init__(self, store: Store[AppState], **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._store = store

    def compose(self) -> ComposeResult:
        state = self._store.get_state()
        version = state.agentlab_version or "dev"

        try:
            cwd = os.getcwd()
        except OSError:
            cwd = "?"

        yield Static(
            f"\u273b Welcome to AgentLab Workbench  v{version}",
            classes="welcome-title",
        )
        yield Static("")
        yield Static(f"cwd: {cwd}", classes="welcome-meta")

        # Status line.
        status_parts: list[str] = []
        if state.workspace_label:
            status_parts.append(state.workspace_label)
        if state.model:
            status_parts.append(state.model)
        status_text = " \u00b7 ".join(status_parts) if status_parts else "no workspace"
        yield Static(f"status: {status_text}", classes="welcome-meta")

        yield Static("")
        mode = state.permission_mode
        yield Static(
            f"{mode} permissions on \u00b7 ? for shortcuts \u00b7 / for commands",
            classes="welcome-meta",
        )
        yield Static(
            "Type /help for commands. Plain text is chat. /exit to leave.",
            classes="welcome-meta",
        )
