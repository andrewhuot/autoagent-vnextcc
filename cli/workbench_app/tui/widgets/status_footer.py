"""Reactive status footer for the TUI workbench.

The footer renders two stacked lines:

* a **status line** describing the workspace / model / session — the
  slow-moving context the user needs at a glance when switching terminals;
* a **footer line** describing live activity — permission mode, running
  shells / tasks, and the coordinator's last published state.

The render logic is factored into pure helpers (``format_status_line`` /
``format_footer_line``) so tests can assert the visible output without a
Textual app — the widget is a thin reactive wrapper on top.
"""

from __future__ import annotations

from typing import Callable

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from cli.workbench_app.store import (
    AppState,
    CoordinatorStatus,
    FooterSlice,
    StatusBarSlice,
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
        self._last_sb: StatusBarSlice | None = None
        self._last_ft: FooterSlice | None = None

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

        if self._status_line is not None:
            self._status_line.update(format_status_line(sb))
        if self._footer_line is not None:
            self._footer_line.update(format_footer_line(ft))


def format_status_line(sb: StatusBarSlice) -> str:
    """Render the top footer line — workspace / model / session context.

    Returns a ``rich``-markup string the ``Static`` widget renders with
    colours. Segments are separated by ``·`` vertical bars so the line
    reads like a breadcrumb. Empty/None segments are dropped silently so
    the line stays compact on fresh installs.
    """
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
    if sb.session_title:
        parts.append(f"[magenta]{sb.session_title}[/]")
    if sb.tokens_used is not None and sb.context_limit:
        percent = int(round((sb.tokens_used / sb.context_limit) * 100)) if sb.context_limit else 0
        colour = "yellow" if percent >= 80 else "green" if percent >= 0 else ""
        if colour:
            parts.append(
                f"[{colour}]{sb.tokens_used:,}/{sb.context_limit:,} tok ({percent}%)[/]"
            )
        else:
            parts.append(f"{sb.tokens_used:,}/{sb.context_limit:,} tok")
    if sb.pending_reviews > 0:
        parts.append(f"[yellow]{sb.pending_reviews} review(s)[/]")
    if sb.best_score:
        parts.append(f"[green]best: {sb.best_score}[/]")
    if sb.agentlab_version:
        parts.append(f"[dim]{sb.agentlab_version}[/]")
    return " \u2502 ".join(parts) if parts else ""


def format_footer_line(ft: FooterSlice) -> str:
    """Render the bottom footer line — permission mode / activity / badges.

    Uses the same Claude-Code-style ``⏵ <mode> permissions on`` prefix the
    prompt_toolkit path renders, then appends the aggregated activity
    summary and a coloured coordinator badge when one is relevant.
    """
    activity = _format_activity(
        active_shells=ft.active_shells, active_tasks=ft.active_tasks
    )
    coord_badge = ""
    if ft.coordinator_status == CoordinatorStatus.RUNNING:
        coord_badge = " [cyan]\u25cf running[/]"
    elif ft.coordinator_status == CoordinatorStatus.FAILED:
        coord_badge = " [red]\u25cf failed[/]"
    mode_label = ft.permission_mode
    return (
        f"\u23f5 {mode_label} permissions on \u00b7 {activity}{coord_badge}"
    )


def _format_activity(*, active_shells: int = 0, active_tasks: int = 0) -> str:
    parts: list[str] = []
    if active_shells > 0:
        noun = "shell" if active_shells == 1 else "shells"
        parts.append(f"{active_shells} {noun}")
    if active_tasks > 0:
        noun = "task" if active_tasks == 1 else "tasks"
        parts.append(f"{active_tasks} {noun}")
    return ", ".join(parts) if parts else "idle"


__all__ = [
    "StatusFooter",
    "format_footer_line",
    "format_status_line",
]
