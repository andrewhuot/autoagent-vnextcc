"""Background task manager for long-running operations."""

from __future__ import annotations

import threading
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Callable


class Task:
    """Represents a single background task."""

    __slots__ = (
        "task_id", "task_type", "status", "progress", "result",
        "error", "created_at", "updated_at", "_thread",
    )

    def __init__(self, task_id: str, task_type: str) -> None:
        self.task_id = task_id
        self.task_type = task_type
        self.status: str = "pending"
        self.progress: int = 0
        self.result: Any = None
        self.error: str | None = None
        self.created_at: datetime = datetime.now(timezone.utc)
        self.updated_at: datetime = self.created_at
        self._thread: threading.Thread | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "status": self.status,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class TaskManager:
    """Thread-safe manager for background tasks.

    Each task runs in its own daemon thread. The callable receives the Task
    object so it can update progress/result as it runs.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, Task] = {}

    def create_task(
        self,
        task_type: str,
        fn: Callable[[Task], Any],
    ) -> Task:
        """Create and start a background task.

        ``fn`` is called with the Task instance. It should:
        - update ``task.progress`` as work proceeds
        - store its final payload in ``task.result``
        Exceptions are caught automatically and stored in ``task.error``.
        """
        task_id = str(uuid.uuid4())[:12]
        task = Task(task_id=task_id, task_type=task_type)

        def _run() -> None:
            try:
                with self._lock:
                    task.status = "running"
                    task.updated_at = datetime.now(timezone.utc)
                result = fn(task)
                with self._lock:
                    task.status = "completed"
                    task.progress = 100
                    if task.result is None:
                        task.result = result
                    task.updated_at = datetime.now(timezone.utc)
            except Exception as exc:
                with self._lock:
                    task.status = "failed"
                    task.error = f"{exc}\n{traceback.format_exc()}"
                    task.updated_at = datetime.now(timezone.utc)

        thread = threading.Thread(target=_run, daemon=True)
        task._thread = thread

        with self._lock:
            self._tasks[task_id] = task

        thread.start()
        return task

    def update_task(
        self,
        task_id: str,
        *,
        progress: int | None = None,
        result: Any = None,
        status: str | None = None,
        error: str | None = None,
    ) -> Task | None:
        """Update fields on an existing task. Returns None if not found."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            if progress is not None:
                task.progress = progress
            if result is not None:
                task.result = result
            if status is not None:
                task.status = status
            if error is not None:
                task.error = error
            task.updated_at = datetime.now(timezone.utc)
            return task

    def get_task(self, task_id: str) -> Task | None:
        with self._lock:
            return self._tasks.get(task_id)

    def list_tasks(self, task_type: str | None = None) -> list[Task]:
        with self._lock:
            tasks = list(self._tasks.values())
        if task_type:
            tasks = [t for t in tasks if t.task_type == task_type]
        return sorted(tasks, key=lambda t: t.created_at, reverse=True)
