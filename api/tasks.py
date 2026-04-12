"""Background task manager for long-running operations.

Tasks are persisted to SQLite so that eval/optimize history survives
server restarts.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
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
        continuity = _task_continuity(self.status)
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "status": self.status,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "continuity": continuity,
            "continuity_state": continuity["state"],
            "state_label": _task_state_label(self.status, continuity),
            "state_detail": _task_state_detail(self.status, continuity),
        }


def _task_continuity(status: str) -> dict[str, Any]:
    """Return display metadata explaining whether task state is live history."""
    if status in ("pending", "running"):
        return {
            "state": "live",
            "label": "Live task",
            "detail": "This task is still active and may update while the server is running.",
            "is_live": True,
            "is_historical": False,
            "can_rerun": False,
        }
    if status == "interrupted":
        return {
            "state": "interrupted",
            "label": "Interrupted by restart",
            "detail": "This task was pending or running when the server restarted. It did not finish; rerun it to continue.",
            "is_live": False,
            "is_historical": True,
            "can_rerun": True,
        }
    return {
        "state": "historical",
        "label": "Historical task",
        "detail": "This task record was restored from durable history.",
        "is_live": False,
        "is_historical": True,
        "can_rerun": False,
    }


def _task_state_label(status: str, continuity: dict[str, Any]) -> str:
    """Return a compact top-level label for task lists."""
    if status == "interrupted":
        return "Interrupted after restart"
    return str(continuity["label"])


def _task_state_detail(status: str, continuity: dict[str, Any]) -> str:
    """Return a compact top-level detail for task lists."""
    if status == "interrupted":
        return "This task was active during a server restart. Start a new run to continue."
    return str(continuity["detail"])


def _serialize_result(result: Any) -> str | None:
    """Serialize a task result to JSON for storage."""
    if result is None:
        return None
    try:
        return json.dumps(result, default=str)
    except (TypeError, ValueError):
        return json.dumps({"_raw": str(result)})


def _deserialize_result(raw: str | None) -> Any:
    """Deserialize a task result from JSON storage."""
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


class TaskManager:
    """Thread-safe manager for background tasks.

    Each task runs in its own daemon thread. The callable receives the Task
    object so it can update progress/result as it runs.

    Tasks are persisted to SQLite so that task history (eval runs, optimize
    cycles) survives server restarts. On startup, any previously-running
    tasks are marked as ``interrupted``.
    """

    def __init__(self, db_path: str = ".agentlab/tasks.db") -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, Task] = {}
        self._db_path = db_path
        self._init_db()
        self._load_historical_tasks()

    def _init_db(self) -> None:
        """Create the tasks table if it does not exist."""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id    TEXT PRIMARY KEY,
                    task_type  TEXT NOT NULL,
                    status     TEXT NOT NULL DEFAULT 'pending',
                    progress   INTEGER NOT NULL DEFAULT 0,
                    result     TEXT,
                    error      TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_type_created
                ON tasks (task_type, created_at DESC)
            """)

    def _load_historical_tasks(self) -> None:
        """Load tasks from the database on startup.

        Any task that was ``running`` or ``pending`` when the server stopped
        is marked ``interrupted`` so the UI shows an honest status.
        """
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT 500"
            ).fetchall()

        interrupted_ids: list[str] = []
        for row in rows:
            task = Task(task_id=row["task_id"], task_type=row["task_type"])
            task.status = row["status"]
            task.progress = row["progress"]
            task.result = _deserialize_result(row["result"])
            task.error = row["error"]
            task.created_at = datetime.fromisoformat(row["created_at"])
            task.updated_at = datetime.fromisoformat(row["updated_at"])

            if task.status in ("running", "pending"):
                task.status = "interrupted"
                if not task.error:
                    task.error = _task_state_detail("interrupted", _task_continuity("interrupted"))
                task.updated_at = datetime.now(timezone.utc)
                interrupted_ids.append(task.task_id)

            self._tasks[task.task_id] = task

        if interrupted_ids:
            with sqlite3.connect(self._db_path) as conn:
                now = datetime.now(timezone.utc).isoformat()
                conn.executemany(
                    "UPDATE tasks SET status = 'interrupted', error = COALESCE(error, ?), updated_at = ? WHERE task_id = ?",
                    [(_task_state_detail("interrupted", _task_continuity("interrupted")), now, tid) for tid in interrupted_ids],
                )

    def _persist_task(self, task: Task) -> None:
        """Write or update a task row in the database."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """INSERT INTO tasks (task_id, task_type, status, progress, result, error, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(task_id) DO UPDATE SET
                       status = excluded.status,
                       progress = excluded.progress,
                       result = excluded.result,
                       error = excluded.error,
                       updated_at = excluded.updated_at
                """,
                (
                    task.task_id,
                    task.task_type,
                    task.status,
                    task.progress,
                    _serialize_result(task.result),
                    task.error,
                    task.created_at.isoformat(),
                    task.updated_at.isoformat(),
                ),
            )

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
                self._persist_task(task)
                result = fn(task)
                with self._lock:
                    task.status = "completed"
                    task.progress = 100
                    if task.result is None:
                        task.result = result
                    task.updated_at = datetime.now(timezone.utc)
                self._persist_task(task)
            except Exception as exc:
                with self._lock:
                    task.status = "failed"
                    task.error = f"{exc}\n{traceback.format_exc()}"
                    task.updated_at = datetime.now(timezone.utc)
                self._persist_task(task)

        thread = threading.Thread(target=_run, daemon=True)
        task._thread = thread

        with self._lock:
            self._tasks[task_id] = task

        self._persist_task(task)
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
        self._persist_task(task)
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
