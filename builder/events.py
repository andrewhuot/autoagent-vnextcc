"""Streaming event helpers for Builder Workspace.

Events flow through two channels:
  1. In-memory deque — for live SSE streaming to connected clients.
  2. SQLite persistence — for durable history that survives restarts.

When a ``durable_store`` is provided to ``EventBroker``, every published
event is also written to the ``builder_session_events`` table so that
``GET /api/builder/events`` always returns complete history.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import deque
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Any, Deque, Iterator

from builder.types import now_ts, new_id

logger = logging.getLogger(__name__)


class BuilderEventType(str, Enum):
    """Allowed builder streaming events."""

    MESSAGE_DELTA = "message.delta"
    TASK_STARTED = "task.started"
    TASK_PROGRESS = "task.progress"
    PLAN_READY = "plan.ready"
    ARTIFACT_UPDATED = "artifact.updated"
    EVAL_STARTED = "eval.started"
    EVAL_COMPLETED = "eval.completed"
    APPROVAL_REQUESTED = "approval.requested"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    SESSION_OPENED = "session.opened"
    SESSION_CLOSED = "session.closed"
    COORDINATOR_EXECUTION_STARTED = "coordinator.execution.started"
    WORKER_GATHERING_CONTEXT = "worker.gathering_context"
    WORKER_ACTING = "worker.acting"
    WORKER_VERIFYING = "worker.verifying"
    WORKER_COMPLETED = "worker.completed"
    WORKER_FAILED = "worker.failed"
    WORKER_BLOCKED = "worker.blocked"
    WORKER_MESSAGE_DELTA = "worker.message.delta"
    COORDINATOR_SYNTHESIS_COMPLETED = "coordinator.synthesis.completed"
    COORDINATOR_EXECUTION_COMPLETED = "coordinator.execution.completed"
    COORDINATOR_EXECUTION_FAILED = "coordinator.execution.failed"
    COORDINATOR_EXECUTION_BLOCKED = "coordinator.execution.blocked"


# Event types that represent significant lifecycle transitions and should
# be bridged to the system-wide EventLog for unified observability.
LIFECYCLE_EVENT_TYPES = frozenset({
    BuilderEventType.TASK_STARTED,
    BuilderEventType.TASK_COMPLETED,
    BuilderEventType.TASK_FAILED,
    BuilderEventType.SESSION_OPENED,
    BuilderEventType.SESSION_CLOSED,
    BuilderEventType.EVAL_STARTED,
    BuilderEventType.EVAL_COMPLETED,
    BuilderEventType.COORDINATOR_EXECUTION_STARTED,
    BuilderEventType.WORKER_COMPLETED,
    BuilderEventType.WORKER_FAILED,
    BuilderEventType.WORKER_BLOCKED,
    BuilderEventType.COORDINATOR_SYNTHESIS_COMPLETED,
    BuilderEventType.COORDINATOR_EXECUTION_COMPLETED,
    BuilderEventType.COORDINATOR_EXECUTION_FAILED,
    BuilderEventType.COORDINATOR_EXECUTION_BLOCKED,
})


@dataclass
class BuilderEvent:
    """One event emitted by builder backend services."""

    event_id: str = field(default_factory=new_id)
    event_type: BuilderEventType = BuilderEventType.TASK_PROGRESS
    session_id: str = ""
    task_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=now_ts)


# ---------------------------------------------------------------------------
# Durable event store — SQLite-backed persistence for builder events
# ---------------------------------------------------------------------------


class DurableEventStore:
    """SQLite-backed append-only store for builder session events.

    This is intentionally a standalone class (not part of BuilderStore) so
    it can be unit-tested in isolation and injected into EventBroker without
    pulling in the full builder store dependency graph.
    """

    def __init__(self, db_path: str = ".agentlab/builder_events.db") -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS builder_session_events (
                    event_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    task_id TEXT,
                    event_type TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    payload TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_bse_session
                    ON builder_session_events(session_id, timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_bse_task
                    ON builder_session_events(task_id, timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_bse_type
                    ON builder_session_events(event_type);
                CREATE INDEX IF NOT EXISTS idx_bse_ts
                    ON builder_session_events(timestamp DESC);
                """
            )
            conn.commit()

    def persist(self, event: BuilderEvent) -> None:
        """Write a single event to the durable store."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO builder_session_events
                    (event_id, session_id, task_id, event_type, timestamp, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.session_id,
                    event.task_id,
                    event.event_type.value,
                    event.timestamp,
                    json.dumps(event.payload, sort_keys=True, default=str),
                ),
            )
            conn.commit()

    def list_events(
        self,
        *,
        session_id: str | None = None,
        task_id: str | None = None,
        event_type: str | None = None,
        limit: int = 200,
    ) -> list[BuilderEvent]:
        """Query persisted events with optional filters."""
        clauses: list[str] = []
        params: list[Any] = []
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        if task_id is not None:
            clauses.append("task_id = ?")
            params.append(task_id)
        if event_type is not None:
            clauses.append("event_type = ?")
            params.append(event_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT event_id, session_id, task_id, event_type, timestamp, payload
                FROM builder_session_events
                {where}
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()

        events: list[BuilderEvent] = []
        for row in reversed(rows):  # reverse to chronological order
            try:
                etype = BuilderEventType(row["event_type"])
            except ValueError:
                etype = BuilderEventType.TASK_PROGRESS
            events.append(BuilderEvent(
                event_id=row["event_id"],
                event_type=etype,
                session_id=row["session_id"],
                task_id=row["task_id"],
                payload=json.loads(row["payload"]) if row["payload"] else {},
                timestamp=row["timestamp"],
            ))
        return events


# ---------------------------------------------------------------------------
# Event broker — in-memory for live SSE + optional durable persistence
# ---------------------------------------------------------------------------


class EventBroker:
    """Event broker with in-memory buffer for SSE and optional SQLite durability.

    When ``durable_store`` is provided, every published event is persisted.
    When ``system_event_log`` is provided, lifecycle events are bridged to
    the system-wide event log for unified observability.
    """

    def __init__(
        self,
        max_events: int = 2000,
        durable_store: DurableEventStore | None = None,
        system_event_log: Any | None = None,
    ) -> None:
        self._events: Deque[BuilderEvent] = deque(maxlen=max_events)
        self._lock = Lock()
        self._durable_store = durable_store
        self._system_event_log = system_event_log

    def publish(
        self,
        event_type: BuilderEventType,
        session_id: str,
        task_id: str | None,
        payload: dict[str, Any],
    ) -> BuilderEvent:
        """Store and return a new event.

        Writes to the in-memory buffer (for SSE), the durable store (for
        history), and optionally the system event log (for lifecycle events).
        """

        event = BuilderEvent(
            event_type=event_type,
            session_id=session_id,
            task_id=task_id,
            payload=payload,
        )
        with self._lock:
            self._events.append(event)

        # Persist to SQLite for durability
        if self._durable_store is not None:
            try:
                self._durable_store.persist(event)
            except Exception:
                logger.warning("Failed to persist builder event %s", event.event_id, exc_info=True)

        # Bridge lifecycle events to system event log
        if self._system_event_log is not None and event_type in LIFECYCLE_EVENT_TYPES:
            self._bridge_to_system_log(event)

        return event

    def _bridge_to_system_log(self, event: BuilderEvent) -> None:
        """Write significant builder events to the system-wide EventLog."""
        system_type = f"builder_{event.event_type.value.replace('.', '_')}"
        bridge_payload = {
            "builder_event_id": event.event_id,
            **({"task_id": event.task_id} if event.task_id else {}),
            **event.payload,
        }
        try:
            self._system_event_log.append(
                event_type=system_type,
                payload=bridge_payload,
                session_id=event.session_id,
            )
        except Exception:
            # System log may not accept this event type yet — that's fine,
            # we don't want bridge failures to break builder operations.
            logger.debug("Could not bridge event %s to system log", system_type)

    def list_events(
        self,
        session_id: str | None = None,
        task_id: str | None = None,
        limit: int = 200,
    ) -> list[BuilderEvent]:
        """Return recent events — from durable store if available, else in-memory."""

        if self._durable_store is not None:
            return self._durable_store.list_events(
                session_id=session_id,
                task_id=task_id,
                limit=limit,
            )

        # Fallback to in-memory buffer
        with self._lock:
            events = list(self._events)
        filtered: list[BuilderEvent] = []
        for event in reversed(events):
            if session_id and event.session_id != session_id:
                continue
            if task_id and event.task_id != task_id:
                continue
            filtered.append(event)
            if len(filtered) >= limit:
                break
        return list(reversed(filtered))

    def iter_events(
        self,
        session_id: str | None = None,
        task_id: str | None = None,
        since_timestamp: float | None = None,
    ) -> Iterator[BuilderEvent]:
        """Yield events matching the filter from the in-memory buffer.

        This always uses the in-memory buffer for low-latency SSE streaming.
        """

        with self._lock:
            events = list(self._events)
        for event in events:
            if session_id and event.session_id != session_id:
                continue
            if task_id and event.task_id != task_id:
                continue
            if since_timestamp is not None and event.timestamp <= since_timestamp:
                continue
            yield event


def serialize_sse_event(event: BuilderEvent) -> str:
    """Serialize a builder event into SSE wire format."""

    payload = {
        "id": event.event_id,
        "type": event.event_type.value,
        "session_id": event.session_id,
        "task_id": event.task_id,
        "timestamp": event.timestamp,
        "payload": event.payload,
    }
    return f"id: {event.event_id}\nevent: {event.event_type.value}\ndata: {json.dumps(payload)}\n\n"


def event_to_dict(event: BuilderEvent) -> dict[str, Any]:
    """Return a JSON-serializable dictionary for one event."""

    data = asdict(event)
    data["event_type"] = event.event_type.value
    return data
