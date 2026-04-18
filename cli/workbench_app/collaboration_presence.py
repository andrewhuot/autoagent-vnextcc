"""Derived collaboration presence for the Workbench.

This module does not schedule work. It translates the existing coordinator
workers, background tasks, and review counters into one user-facing team-state
view so the terminal can explain who owns what and what needs attention.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from rich.markup import escape as escape_markup

from cli.workbench_app.background_panel import BackgroundTask, TaskStatus
from cli.workbench_app.store import (
    AppState,
    CoordinatorStatus,
    WorkerPhase,
    WorkerState,
)


class CollaborationTeamState(str, Enum):
    """High-level state shown in the collaboration presence panel."""

    IDLE = "idle"
    RUNNING = "running"
    NEEDS_ATTENTION = "needs_attention"
    WAITING_REVIEW = "waiting_review"
    FINISHED_RECENTLY = "finished_recently"


@dataclass(frozen=True)
class CollaborationPresenceItem:
    """One visible unit of collaboration work."""

    item_id: str
    source: str
    owner: str
    task: str
    state: str
    detail: str = ""
    requires_attention: bool = False


@dataclass(frozen=True)
class CollaborationPresenceSnapshot:
    """A compact summary of current team and orchestration state."""

    team_state: CollaborationTeamState
    running_count: int = 0
    blocked_count: int = 0
    waiting_review_count: int = 0
    finished_recently_count: int = 0
    items: tuple[CollaborationPresenceItem, ...] = ()

    @property
    def has_visible_activity(self) -> bool:
        """Return whether the presence panel has useful content to show."""
        return (
            self.team_state != CollaborationTeamState.IDLE
            or bool(self.items)
            or self.waiting_review_count > 0
        )


_ACTIVE_WORKER_PHASES = {
    WorkerPhase.QUEUED,
    WorkerPhase.GATHERING_CONTEXT,
    WorkerPhase.ACTING,
    WorkerPhase.VERIFYING,
}
_ATTENTION_WORKER_PHASES = {WorkerPhase.BLOCKED, WorkerPhase.FAILED}
_RECENT_WORKER_PHASES = {WorkerPhase.COMPLETED}

_ACTIVE_TASK_STATUSES = {TaskStatus.QUEUED, TaskStatus.RUNNING}
_ATTENTION_TASK_STATUSES = {TaskStatus.FAILED}
_RECENT_TASK_STATUSES = {TaskStatus.COMPLETED}


def build_presence_snapshot(state: AppState) -> CollaborationPresenceSnapshot:
    """Build collaboration presence from the current immutable app state."""

    items: list[CollaborationPresenceItem] = []
    running_count = 0
    blocked_count = 0
    finished_recently_count = 0

    for worker in state.coordinator_workers:
        item = _worker_item(worker)
        items.append(item)
        if worker.phase in _ACTIVE_WORKER_PHASES:
            running_count += 1
        elif worker.phase in _ATTENTION_WORKER_PHASES:
            blocked_count += 1
        elif worker.phase in _RECENT_WORKER_PHASES:
            finished_recently_count += 1

    for raw_task in state.background_tasks:
        item, status = _background_item(raw_task)
        if item is None or status is None:
            continue
        items.append(item)
        if status in _ACTIVE_TASK_STATUSES:
            running_count += 1
        elif status in _ATTENTION_TASK_STATUSES:
            blocked_count += 1
        elif status in _RECENT_TASK_STATUSES:
            finished_recently_count += 1

    team_state = _team_state(
        coordinator_status=state.coordinator_status,
        running_count=running_count,
        blocked_count=blocked_count,
        waiting_review_count=state.pending_reviews,
        finished_recently_count=finished_recently_count,
    )
    return CollaborationPresenceSnapshot(
        team_state=team_state,
        running_count=running_count,
        blocked_count=blocked_count,
        waiting_review_count=state.pending_reviews,
        finished_recently_count=finished_recently_count,
        items=tuple(items),
    )


def build_presence_snapshot_from_tasks_snapshot(
    snapshot: Mapping[str, Any],
) -> CollaborationPresenceSnapshot:
    """Build presence from ``CoordinatorSession.tasks_snapshot()`` output."""

    items: list[CollaborationPresenceItem] = []
    running_count = 0
    blocked_count = 0
    finished_recently_count = 0
    active_run_count = int(snapshot.get("active_run_count") or 0)

    for run in snapshot.get("runs") or []:
        if not isinstance(run, Mapping):
            continue
        run_status = str(run.get("status") or "").lower()
        for worker in run.get("workers") or []:
            if not isinstance(worker, Mapping):
                continue
            item = _snapshot_worker_item(worker)
            items.append(item)
            status = str(worker.get("status") or "").lower()
            if status in {"pending", "gathering_context", "acting", "verifying"}:
                running_count += 1
            elif status in {"blocked", "failed"}:
                blocked_count += 1
            elif status == "completed":
                finished_recently_count += 1
        if not run.get("workers"):
            if run_status in {"running", "pending"}:
                running_count += int(run.get("worker_count") or 0)
            elif run_status in {"blocked", "failed"}:
                blocked_count += int(run.get("worker_count") or 0)
            elif run_status == "completed":
                finished_recently_count += int(run.get("worker_count") or 0)

    coordinator_status = (
        CoordinatorStatus.RUNNING if active_run_count else CoordinatorStatus.IDLE
    )
    return CollaborationPresenceSnapshot(
        team_state=_team_state(
            coordinator_status=coordinator_status,
            running_count=running_count,
            blocked_count=blocked_count,
            waiting_review_count=0,
            finished_recently_count=finished_recently_count,
        ),
        running_count=running_count,
        blocked_count=blocked_count,
        waiting_review_count=0,
        finished_recently_count=finished_recently_count,
        items=tuple(items),
    )


def render_presence_lines(
    snapshot: CollaborationPresenceSnapshot,
    *,
    markup: bool = False,
    indent: str = "",
) -> list[str]:
    """Render a collaboration presence snapshot for slash output or TUI."""

    state_label = snapshot.team_state.value.replace("_", " ")
    header = f"Team state: {state_label}"
    lines = [f"{indent}{_state_style(header, snapshot.team_state, markup)}"]
    lines.append(
        f"{indent}  Running: {snapshot.running_count} | "
        f"Blocked: {snapshot.blocked_count} | "
        f"Waiting review: {snapshot.waiting_review_count} | "
        f"Finished recently: {snapshot.finished_recently_count}"
    )

    if not snapshot.items:
        if snapshot.waiting_review_count:
            lines.append(
                f"{indent}  Review queue: {snapshot.waiting_review_count} item(s) waiting"
            )
        else:
            lines.append(f"{indent}  No active coordinator workers or background tasks.")
        return lines

    lines.append(f"{indent}  Roster:")
    for item in snapshot.items[:8]:
        owner = _display_text(_display_owner(item.owner), markup)
        marker = "!" if item.requires_attention else "*"
        task = _display_text(item.task, markup)
        detail = f" - {_display_text(item.detail, markup)}" if item.detail else ""
        status = _item_style(item.state, item.requires_attention, markup)
        status_text = status if markup else f"[{status}]"
        lines.append(
            f"{indent}    {marker} {owner} owns {task} {status_text}{detail}"
        )
    remaining = len(snapshot.items) - 8
    if remaining > 0:
        lines.append(f"{indent}    ... {remaining} more item(s)")
    return lines


def _worker_item(worker: WorkerState) -> CollaborationPresenceItem:
    owner = worker.owner or worker.role or "worker"
    task = worker.title or _display_owner(worker.role) or "Coordinator task"
    detail = worker.detail or ""
    return CollaborationPresenceItem(
        item_id=worker.worker_id,
        source="coordinator",
        owner=owner,
        task=task,
        state=_worker_phase_label(worker.phase),
        detail=detail,
        requires_attention=worker.phase in _ATTENTION_WORKER_PHASES,
    )


def _background_item(
    raw_task: Any,
) -> tuple[CollaborationPresenceItem | None, TaskStatus | None]:
    if isinstance(raw_task, BackgroundTask):
        return (
            CollaborationPresenceItem(
                item_id=raw_task.task_id,
                source="background",
                owner=raw_task.owner or "background",
                task=raw_task.description,
                state=raw_task.status.value,
                detail=raw_task.detail,
                requires_attention=raw_task.status in _ATTENTION_TASK_STATUSES,
            ),
            raw_task.status,
        )
    if isinstance(raw_task, Mapping):
        try:
            status = TaskStatus(str(raw_task.get("status") or "queued"))
        except ValueError:
            return None, None
        return (
            CollaborationPresenceItem(
                item_id=str(raw_task.get("task_id") or ""),
                source="background",
                owner=str(raw_task.get("owner") or "background"),
                task=str(
                    raw_task.get("description")
                    or raw_task.get("task")
                    or "Background task"
                ),
                state=status.value,
                detail=str(raw_task.get("detail") or ""),
                requires_attention=status in _ATTENTION_TASK_STATUSES,
            ),
            status,
        )
    return None, None


def _snapshot_worker_item(worker: Mapping[str, Any]) -> CollaborationPresenceItem:
    status = str(worker.get("status") or "pending")
    detail = str(worker.get("detail") or "")
    return CollaborationPresenceItem(
        item_id=str(worker.get("worker_id") or worker.get("node_id") or ""),
        source="coordinator",
        owner=str(worker.get("owner") or worker.get("role") or "worker"),
        task=str(worker.get("title") or worker.get("task") or "Coordinator task"),
        state=status,
        detail=detail,
        requires_attention=status in {"blocked", "failed"},
    )


def _team_state(
    *,
    coordinator_status: CoordinatorStatus,
    running_count: int,
    blocked_count: int,
    waiting_review_count: int,
    finished_recently_count: int,
) -> CollaborationTeamState:
    if blocked_count > 0 or coordinator_status == CoordinatorStatus.FAILED:
        return CollaborationTeamState.NEEDS_ATTENTION
    if waiting_review_count > 0:
        return CollaborationTeamState.WAITING_REVIEW
    if running_count > 0 or coordinator_status == CoordinatorStatus.RUNNING:
        return CollaborationTeamState.RUNNING
    if finished_recently_count > 0:
        return CollaborationTeamState.FINISHED_RECENTLY
    return CollaborationTeamState.IDLE


def _worker_phase_label(phase: WorkerPhase) -> str:
    if phase == WorkerPhase.GATHERING_CONTEXT:
        return "gathering context"
    return phase.value.replace("_", " ")


def _display_owner(owner: str) -> str:
    return " ".join(str(owner or "worker").replace("_", " ").split()).lower()


def _display_text(text: str, markup: bool) -> str:
    if not markup:
        return str(text)
    return escape_markup(str(text))


def _state_style(
    text: str,
    state: CollaborationTeamState,
    markup: bool,
) -> str:
    if not markup:
        return text
    if state == CollaborationTeamState.NEEDS_ATTENTION:
        return f"[red bold]{text}[/]"
    if state == CollaborationTeamState.WAITING_REVIEW:
        return f"[yellow bold]{text}[/]"
    if state == CollaborationTeamState.RUNNING:
        return f"[cyan bold]{text}[/]"
    if state == CollaborationTeamState.FINISHED_RECENTLY:
        return f"[green bold]{text}[/]"
    return f"[dim]{text}[/]"


def _item_style(state: str, requires_attention: bool, markup: bool) -> str:
    if not markup:
        return state
    if requires_attention:
        return f"[red]{state}[/]"
    if state in {"completed", "finished"}:
        return f"[green]{state}[/]"
    if state in {"running", "acting", "verifying"}:
        return f"[cyan]{state}[/]"
    return f"[dim]{state}[/]"


__all__ = [
    "CollaborationPresenceItem",
    "CollaborationPresenceSnapshot",
    "CollaborationTeamState",
    "build_presence_snapshot",
    "build_presence_snapshot_from_tasks_snapshot",
    "render_presence_lines",
]
