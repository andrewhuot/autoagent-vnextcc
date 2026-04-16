"""Session resume screen for the TUI workbench.

Port of ``cli.workbench_app.screens.resume.ResumeScreen`` — displays
recent sessions with selection via arrow keys + enter.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.widgets import OptionList, Static

from cli.workbench_app.screens.base import ACTION_CANCEL, ScreenResult
from cli.workbench_app.tui.screens.base import TUIScreen


class ResumeScreen(TUIScreen):
    """Full-screen session picker for resuming previous sessions.

    Displays recent sessions as a selectable list. Press enter to resume
    the selected session, or ``q``/``Esc`` to cancel.
    """

    screen_title = "/resume — Resume Session"

    def __init__(
        self,
        session_store: Any | None = None,
        current_session: Any | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._session_store = session_store
        self._current_session = current_session

    def screen_content(self) -> ComposeResult:
        if self._session_store is None:
            yield Static("[yellow]No session store available[/]")
            return

        sessions = self._load_sessions()
        if not sessions:
            yield Static("[dim]No previous sessions found[/]")
            return

        yield Static("[bold]Recent sessions:[/]")
        yield Static("")

        option_list = OptionList(id="session-list")
        for session in sessions:
            title = getattr(session, "title", None) or getattr(session, "session_id", "?")
            age = self._format_age(session)
            option_list.add_option(f"{title}  [dim]({age})[/]")
        yield option_list

    def hint_text(self) -> str:
        return "Use arrows to select, [Enter] to resume, [q]/[Esc] to cancel"

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        sessions = self._load_sessions()
        if event.option_index < len(sessions):
            session = sessions[event.option_index]
            session_id = getattr(session, "session_id", None)
            self.dismiss(ScreenResult(
                action="resume",
                value=session_id,
                meta_messages=(f"Resumed session: {session_id}",),
            ))

    def _load_sessions(self) -> list[Any]:
        try:
            return self._session_store.list_recent(limit=10)
        except Exception:
            try:
                return list(self._session_store.list())[:10]
            except Exception:
                return []

    def _format_age(self, session: Any) -> str:
        import time
        updated = getattr(session, "updated_at", None) or 0
        if not updated:
            return "unknown"
        age = time.time() - updated
        if age < 60:
            return "just now"
        if age < 3600:
            return f"{int(age // 60)}m ago"
        if age < 86400:
            return f"{int(age // 3600)}h ago"
        return f"{int(age // 86400)}d ago"
