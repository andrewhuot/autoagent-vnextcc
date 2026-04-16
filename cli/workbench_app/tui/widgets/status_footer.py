"""Reactive status footer for the TUI workbench."""

from __future__ import annotations

from typing import Callable

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from cli.workbench_app.store import (
    AppState,
    CoordinatorStatus,
    Store,
    select_footer,
    select_status_bar,
)


class StatusFooter(Widget):
    """Bottom status bar showing workspace, model, mode, and activity.

    Subscribes to the store and re-renders when the status bar or footer
    slice changes.
    """

    def __init__(self, store: Store[AppState], **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._store = store
        self._unsub: Callable[[], None] = lambda: None
        self._status_line: Static | None = None
        self._footer_line: Static | None = None
        self._last_sb = None
        self._last_ft = None

    def compose(self) -> ComposeResult:
        self._status_line = Static("", classes="footer-divider")
        self._footer_line = Static("", classes="footer-activity")
        yield self._status_line
        yield self._footer_line

    def on_mount(self) -> None:
        self._render_from_store()
        self._unsub = self._store.subscribe(self._on_store_changed)

    def on_unmount(self) -> None:
        self._unsub()

    def _on_store_changed(self) -> None:
        try:
            self.app.call_from_thread(self._render_from_store)
        except RuntimeError:
            try:
                self.call_later(self._render_from_store)
            except Exception:
                pass
        except AttributeError:
            pass

    def _render_from_store(self) -> None:
        state = self._store.get_state()
        sb = select_status_bar(state)
        ft = select_footer(state)

        # Skip re-render if nothing changed.
        if sb == self._last_sb and ft == self._last_ft:
            return
        self._last_sb = sb
        self._last_ft = ft

        # Build status line.
        parts: list[str] = []
        if sb.workspace_label:
            parts.append(f"[bold cyan]{sb.workspace_label}[/]")
        if sb.config_version is not None:
            parts.append(f"v{sb.config_version:03d}")
        if sb.model:
            model_str = sb.model
            if sb.provider:
                model_str += f" \u00b7 {sb.provider}"
            if not sb.provider_key_present:
                model_str += " [red]\\[no key][/]"
            parts.append(model_str)
        if sb.pending_reviews > 0:
            parts.append(f"[yellow]{sb.pending_reviews} review(s)[/]")
        if sb.best_score:
            parts.append(f"[green]best: {sb.best_score}[/]")
        if sb.agentlab_version:
            parts.append(f"[dim]{sb.agentlab_version}[/]")

        if self._status_line is not None:
            self._status_line.update(" \u2502 ".join(parts) if parts else "")

        # Build footer line.
        activity = _format_activity(
            active_shells=ft.active_shells,
            active_tasks=ft.active_tasks,
        )
        coord_badge = ""
        if ft.coordinator_status == CoordinatorStatus.RUNNING:
            coord_badge = " [cyan]\u25cf running[/]"
        elif ft.coordinator_status == CoordinatorStatus.FAILED:
            coord_badge = " [red]\u25cf failed[/]"

        mode_label = ft.permission_mode
        footer_text = f"\u23f5 {mode_label} permissions on \u00b7 {activity}{coord_badge}"

        if self._footer_line is not None:
            self._footer_line.update(footer_text)


def _format_activity(*, active_shells: int = 0, active_tasks: int = 0) -> str:
    parts: list[str] = []
    if active_shells > 0:
        noun = "shell" if active_shells == 1 else "shells"
        parts.append(f"{active_shells} {noun}")
    if active_tasks > 0:
        noun = "task" if active_tasks == 1 else "tasks"
        parts.append(f"{active_tasks} {noun}")
    return ", ".join(parts) if parts else "idle"
