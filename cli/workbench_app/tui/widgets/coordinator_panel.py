"""Collaboration presence widget for coordinator and background work."""

from __future__ import annotations

from typing import Callable

from textual.widgets import Static

from cli.workbench_app.collaboration_presence import (
    CollaborationPresenceSnapshot,
    build_presence_snapshot,
    render_presence_lines,
)
from cli.workbench_app.store import AppState, Store


class CoordinatorPanel(Static):
    """Reactive widget showing collaboration presence and worker progress.

    Hidden when there is no coordinator, background, review, or recent
    worker state. Appears during active coordinator workflows and remains
    visible after completion so recent ownership and progress are legible.
    """

    DEFAULT_CSS = """
    CoordinatorPanel {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
    }
    """

    def __init__(self, store: Store[AppState], **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._store = store
        self._unsub: Callable[[], None] = lambda: None
        self._last_presence: CollaborationPresenceSnapshot | None = None

    def on_mount(self) -> None:
        self._sync()
        self._unsub = self._store.subscribe(self._on_store_changed)

    def on_unmount(self) -> None:
        self._unsub()

    def _on_store_changed(self) -> None:
        try:
            self.app.call_from_thread(self._sync)
        except RuntimeError:
            try:
                self.call_later(self._sync)
            except Exception:
                pass
        except AttributeError:
            pass

    def _sync(self) -> None:
        presence = build_presence_snapshot(self._store.get_state())

        # Skip if nothing changed.
        if presence == self._last_presence:
            return
        self._last_presence = presence

        if not presence.has_visible_activity:
            self.display = False
            self.update("")
            return

        self.display = True
        lines = self._render_presence(presence)
        self.update("\n".join(lines))

    def _render_presence(
        self,
        presence: CollaborationPresenceSnapshot,
    ) -> list[str]:
        """Build collaboration presence lines as Rich markup."""
        return render_presence_lines(presence, markup=True)
