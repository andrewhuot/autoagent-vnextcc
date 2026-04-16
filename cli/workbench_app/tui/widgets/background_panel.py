"""Background task panel widget for the TUI workbench.

Displays background tasks with color-coded status badges. Watches
``state.background_tasks`` and re-renders reactively.
"""

from __future__ import annotations

from typing import Any, Callable

from textual.widgets import Static

from cli.workbench_app.background_panel import BackgroundTask, TaskStatus
from cli.workbench_app.store import AppState, Store


# Status → (Rich markup color, display label).
_STATUS_STYLE: dict[TaskStatus, tuple[str, str]] = {
    TaskStatus.QUEUED: ("dim", "\u25cb queued"),
    TaskStatus.RUNNING: ("cyan", "\u25cf running"),
    TaskStatus.COMPLETED: ("green", "\u2713 completed"),
    TaskStatus.FAILED: ("red", "\u2717 failed"),
}


class BackgroundPanel(Static):
    """Reactive widget showing background task status.

    Hidden when no tasks exist. Appears with a compact list of tasks
    and their current status.
    """

    DEFAULT_CSS = """
    BackgroundPanel {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
        display: none;
    }
    """

    def __init__(self, store: Store[AppState], **kwargs: object) -> None:
        super().__init__("", **kwargs)
        self._store = store
        self._unsub: Callable[[], None] = lambda: None
        self._last_tasks: tuple[Any, ...] = ()

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
        tasks = self._store.get_state().background_tasks
        if tasks == self._last_tasks:
            return
        self._last_tasks = tasks

        if not tasks:
            self.display = False
            self.update("")
            return

        self.display = True
        lines = self._render_tasks(tasks)
        self.update("\n".join(lines))

    def _render_tasks(self, tasks: tuple[Any, ...]) -> list[str]:
        lines: list[str] = []
        lines.append("[bold]Background Tasks[/]")

        for task in tasks:
            if isinstance(task, BackgroundTask):
                color, label = _STATUS_STYLE.get(
                    task.status, ("dim", task.status.value)
                )
                desc = task.description[:60]
                detail = f" — {task.detail[:40]}" if task.detail else ""
                lines.append(
                    f"  [{color}]{label}[/]  {task.task_id}: {desc}{detail}"
                )
            elif isinstance(task, dict):
                status = task.get("status", "unknown")
                desc = task.get("description", "?")[:60]
                task_id = task.get("task_id", "?")
                lines.append(f"  {status}  {task_id}: {desc}")
            else:
                lines.append(f"  {task}")

        return lines
