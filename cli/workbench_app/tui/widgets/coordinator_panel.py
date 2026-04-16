"""Coordinator worker progress tree widget.

Renders the coordinator's worker roster as a compact tree with glyphs
matching the legacy ``coordinator_render.py`` style::

    ● Coordinator running (2 workers)
    ├─ BUILD ENGINEER  gathering context
    └─ EVAL AUTHOR     queued

Colors change per phase: queued (dim), gathering (dim), acting (cyan),
verifying (yellow), completed (green), failed (red), blocked (yellow).
"""

from __future__ import annotations

from typing import Callable

from textual.widgets import Static

from cli.workbench_app.store import (
    AppState,
    CoordinatorStatus,
    Store,
    WorkerPhase,
    WorkerState,
    select_footer,
)


# Tree glyphs matching coordinator_render.py.
_RUNNING_GLYPH = "\u25cf"  # ●
_BRANCH_GLYPH = "\u251c\u2500"  # ├─
_END_GLYPH = "\u2514\u2500"  # └─

# Phase → (Rich markup color, display label).
_PHASE_STYLE: dict[WorkerPhase, tuple[str, str]] = {
    WorkerPhase.QUEUED: ("dim", "queued"),
    WorkerPhase.GATHERING_CONTEXT: ("dim", "gathering context"),
    WorkerPhase.ACTING: ("cyan", "acting"),
    WorkerPhase.VERIFYING: ("yellow", "verifying"),
    WorkerPhase.COMPLETED: ("green", "completed"),
    WorkerPhase.FAILED: ("red", "failed"),
    WorkerPhase.BLOCKED: ("yellow", "blocked"),
}


def _format_role(role: str) -> str:
    """Normalize worker role for display."""
    return role.replace("_", " ").strip().upper() or "WORKER"


class CoordinatorPanel(Static):
    """Reactive widget showing coordinator worker progress.

    Hidden when coordinator is idle. Appears during active coordinator
    workflows and renders a tree of worker states.
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
        self._last_status: CoordinatorStatus | None = None
        self._last_workers: tuple[WorkerState, ...] = ()

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
        state = self._store.get_state()
        status = state.coordinator_status
        workers = state.coordinator_workers

        # Skip if nothing changed.
        if status == self._last_status and workers == self._last_workers:
            return
        self._last_status = status
        self._last_workers = workers

        if status == CoordinatorStatus.IDLE or not workers:
            self.display = False
            self.update("")
            return

        self.display = True
        lines = self._render_tree(status, workers)
        self.update("\n".join(lines))

    def _render_tree(
        self,
        status: CoordinatorStatus,
        workers: tuple[WorkerState, ...],
    ) -> list[str]:
        """Build the worker tree as Rich-markup lines."""
        lines: list[str] = []

        # Header line.
        status_color = "cyan" if status == CoordinatorStatus.RUNNING else "red"
        lines.append(
            f"[{status_color} bold]{_RUNNING_GLYPH} Coordinator {status.value} "
            f"({len(workers)} worker{'s' if len(workers) != 1 else ''})[/]"
        )

        # Worker lines.
        for i, worker in enumerate(workers):
            is_last = i == len(workers) - 1
            glyph = _END_GLYPH if is_last else _BRANCH_GLYPH
            color, label = _PHASE_STYLE.get(
                worker.phase, ("dim", worker.phase.value)
            )
            role = _format_role(worker.role)

            detail = ""
            if worker.detail:
                detail = f" — {worker.detail}"

            lines.append(
                f"[dim]  {glyph} [/][{color}]{role}[/]  {label}{detail}"
            )

        return lines
