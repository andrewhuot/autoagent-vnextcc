"""Task lifecycle management for the A2A protocol layer.

TaskManager is the single source of truth for in-memory A2A task state.
It also provides a bridge to AutoAgent's experiment-tracking conventions.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from a2a.types import A2ATask, TaskStatus


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskManager:
    """Thread-safe in-memory store for A2A task lifecycle management."""

    def __init__(self) -> None:
        self._tasks: dict[str, A2ATask] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create_task(
        self,
        input_message: str,
        agent_name: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> A2ATask:
        """Create a new task in SUBMITTED status.

        Args:
            input_message: The raw user/caller message.
            agent_name: Name of the agent that will handle this task.
            metadata: Optional extra key/value pairs stored on the task.

        Returns:
            The newly created A2ATask.
        """
        now = _now_iso()
        task = A2ATask(
            task_id=uuid.uuid4().hex,
            status=TaskStatus.SUBMITTED.value,
            input_message=input_message,
            created_at=now,
            updated_at=now,
            metadata={**(metadata or {}), "agent_name": agent_name},
        )
        with self._lock:
            self._tasks[task.task_id] = task
        return task

    def update_status(
        self,
        task_id: str,
        status: TaskStatus | str,
        output: Optional[str] = None,
    ) -> A2ATask:
        """Update a task's status and optionally its output message.

        Args:
            task_id: The unique task identifier.
            status: New TaskStatus (enum member or string value).
            output: Optional output text to set on the task.

        Returns:
            The updated A2ATask.

        Raises:
            KeyError: If ``task_id`` is not found.
        """
        status_str = status.value if isinstance(status, TaskStatus) else status
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError(f"Task '{task_id}' not found")
            task.status = status_str
            task.updated_at = _now_iso()
            if output is not None:
                task.output_message = output
            # Append transition to history
            task.history.append(
                {
                    "status": status_str,
                    "timestamp": task.updated_at,
                    "output_snapshot": output,
                }
            )
        return task

    def get_task(self, task_id: str) -> Optional[A2ATask]:
        """Return a task by ID, or None if not found."""
        with self._lock:
            return self._tasks.get(task_id)

    def list_tasks(
        self,
        status: Optional[TaskStatus | str] = None,
        limit: int = 100,
    ) -> list[A2ATask]:
        """Return tasks optionally filtered by status, newest first.

        Args:
            status: If given, only return tasks with this status.
            limit: Maximum number of tasks to return (default 100).

        Returns:
            List of A2ATask objects.
        """
        status_str: Optional[str] = None
        if status is not None:
            status_str = status.value if isinstance(status, TaskStatus) else status

        with self._lock:
            tasks = list(self._tasks.values())

        if status_str is not None:
            tasks = [t for t in tasks if t.status == status_str]

        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return tasks[:limit]

    # ------------------------------------------------------------------
    # Experiment tracking bridge
    # ------------------------------------------------------------------

    def map_to_experiment(self, task: A2ATask) -> dict[str, Any]:
        """Map an A2ATask to an AutoAgent experiment-tracking record.

        The returned dict is compatible with the experiment store schema
        used elsewhere in the AutoAgent platform.

        Args:
            task: The A2ATask to convert.

        Returns:
            A dict suitable for ingestion by the experiment tracker.
        """
        agent_name = task.metadata.get("agent_name", "unknown")
        success = task.status == TaskStatus.COMPLETED.value
        failed = task.status == TaskStatus.FAILED.value

        return {
            "experiment_id": f"a2a-{task.task_id}",
            "source": "a2a",
            "agent_name": agent_name,
            "task_id": task.task_id,
            "status": task.status,
            "input": task.input_message,
            "output": task.output_message,
            "success": success,
            "failed": failed,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "history_length": len(task.history),
            "artifact_count": len(task.artifacts),
            "metadata": task.metadata,
        }
