"""Background-task registry for long-running agent work.

Distinct from the existing ``&`` background-turn mechanism in
:mod:`cli.workbench_app.app` (fire-and-forget coordinator turns). This
module handles Claude Code's *AgentTool* / subagent panel: the LLM — or
user — spawns a task, we give it a stable id, and the ``/background``
slash command renders the current list with statuses.

Design decisions:

* **In-memory only**. Background tasks are session-local: a workbench
  restart drops them (subprocesses may still be running, but that's the
  orchestrator's problem, not the panel's). Persisting would force us to
  reconcile state with the subprocess supervisor, which is out of scope.
* **No threading here**. The registry is pure data; the orchestrator that
  actually runs the subagent is responsible for updating the task record.
  That keeps tests trivially synchronous and decouples the panel from any
  particular executor.
* **Status is a small enum**. Claude Code tracks richer lifecycle
  (queued/in-progress/paused/failed), but until we have real
  orchestration wired up we only need the four states the UI renders
  meaningfully.
"""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable


class TaskStatus(str, Enum):
    """Lifecycle state for a background task."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class BackgroundTask:
    """One record in the registry.

    The ``owner`` is intentionally freeform — a slash command can record
    itself (``"user:/plan"``), the AgentTool can record ``"agent:reviewer"``,
    etc. Keeping it a string avoids forcing every caller to share an enum.
    """

    task_id: str
    description: str
    owner: str = ""
    status: TaskStatus = TaskStatus.QUEUED
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    detail: str = ""
    """Latest short status string — e.g. the most recent tool call, or a
    progress message. Limited to ~200 chars when rendered so the panel
    stays compact."""

    def touch(self, *, status: TaskStatus | None = None, detail: str = "") -> None:
        """Update the task in place and bump ``updated_at``."""
        if status is not None:
            self.status = status
        if detail:
            self.detail = detail
        self.updated_at = time.time()


@dataclass
class BackgroundTaskRegistry:
    """Mutable collection of :class:`BackgroundTask` keyed by id.

    Fresh ids are monotonic integers prefixed with ``bg-`` so the user can
    type ``/background bg-3`` without quoting. Ids never collide within a
    session because the counter is registry-scoped."""

    tasks: dict[str, BackgroundTask] = field(default_factory=dict)
    _id_seq: itertools.count = field(default_factory=lambda: itertools.count(1))

    def register(
        self,
        description: str,
        *,
        owner: str = "",
        detail: str = "",
    ) -> BackgroundTask:
        """Create a new queued task and return the record.

        The caller gets a stable id back and is expected to call
        :meth:`touch` / :meth:`update` as the work progresses."""
        task_id = f"bg-{next(self._id_seq)}"
        task = BackgroundTask(
            task_id=task_id,
            description=description.strip() or "(no description)",
            owner=owner,
            status=TaskStatus.QUEUED,
            detail=detail,
        )
        self.tasks[task_id] = task
        return task

    def update(
        self,
        task_id: str,
        *,
        status: TaskStatus | None = None,
        detail: str = "",
    ) -> BackgroundTask | None:
        """Update an existing task. Returns ``None`` if the id is unknown —
        callers treat a missing task as a no-op rather than an error because
        the registry can be cleared mid-session by ``/clear``."""
        task = self.tasks.get(task_id)
        if task is None:
            return None
        task.touch(status=status, detail=detail)
        return task

    def get(self, task_id: str) -> BackgroundTask | None:
        return self.tasks.get(task_id)

    def list(self, *, include_completed: bool = True) -> list[BackgroundTask]:
        """Return tasks newest-first for display.

        Completed/failed tasks are shown by default because the panel is
        often consulted after the fact ("did that reviewer subagent
        finish?"); ``include_completed=False`` is available for callers
        that only want the active set (e.g. the status bar indicator)."""
        items = list(self.tasks.values())
        if not include_completed:
            items = [
                task
                for task in items
                if task.status not in {TaskStatus.COMPLETED, TaskStatus.FAILED}
            ]
        items.sort(key=lambda task: task.updated_at, reverse=True)
        return items

    def active_count(self) -> int:
        """Count of tasks in QUEUED/RUNNING — used by the status bar."""
        return sum(
            1
            for task in self.tasks.values()
            if task.status in {TaskStatus.QUEUED, TaskStatus.RUNNING}
        )

    def clear(self, *, completed_only: bool = True) -> int:
        """Drop completed/failed tasks; return the number removed.

        ``completed_only=False`` drops everything, which is only sensible
        after a ``/clear`` — an active agent task should not be forgotten
        about just because the user wants a clean panel."""
        to_remove = [
            task_id
            for task_id, task in self.tasks.items()
            if completed_only
            and task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED}
            or not completed_only
        ]
        for task_id in to_remove:
            self.tasks.pop(task_id, None)
        return len(to_remove)


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def render_panel(
    registry: BackgroundTaskRegistry,
    *,
    include_completed: bool = True,
) -> list[str]:
    """Return the panel lines for the ``/background`` command.

    The output is styled only minimally — rich colouring happens at the
    slash layer via :mod:`cli.workbench_app.theme` — so unit tests can
    assert structure without parsing ANSI. Completed tasks are printed
    with a dimmer label downstream."""
    tasks = registry.list(include_completed=include_completed)
    if not tasks:
        return ["  (no background tasks)"]

    lines = ["  Background tasks (newest first):"]
    for task in tasks:
        summary = _summarise(task)
        lines.append(f"    {summary}")
    return lines


def _summarise(task: BackgroundTask) -> str:
    age_seconds = max(0.0, time.time() - task.created_at)
    age = _format_age(age_seconds)
    owner = f" owner={task.owner}" if task.owner else ""
    detail = f" · {task.detail[:80]}" if task.detail else ""
    return (
        f"{task.task_id}  [{task.status.value}]  "
        f"{task.description[:60]}{owner}  ({age}){detail}"
    )


def _format_age(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s ago"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    return f"{int(seconds // 3600)}h ago"


__all__ = [
    "BackgroundTask",
    "BackgroundTaskRegistry",
    "TaskStatus",
    "render_panel",
]
