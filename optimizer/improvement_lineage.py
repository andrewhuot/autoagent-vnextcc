"""Improvement lineage store.

Tracks the lifecycle of a single optimizer proposal from acceptance through
deploy and post-deploy measurement. Complements :class:`OptimizationMemory`
(which holds the proposal and its immediate acceptance/rejection verdict) by
persisting the downstream deploy and measurement events keyed by
``attempt_id``. The Improvements API joins these together and returns a full
lineage card per proposal.

Schema lives in its own SQLite file so it can be migrated independently of
``optimizer_memory.db``.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


DEFAULT_DB_PATH = ".agentlab/improvement_lineage.db"


@dataclass
class LineageEvent:
    event_id: str
    attempt_id: str
    event_type: str  # deploy_canary | promote | rollback | measurement | accept | reject
    timestamp: float
    version: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)


class ImprovementLineageStore:
    """Append-only store of post-proposal lineage events."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS lineage_events (
                    event_id TEXT PRIMARY KEY,
                    attempt_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    version INTEGER,
                    payload TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_lineage_attempt "
                "ON lineage_events(attempt_id, timestamp)"
            )
            conn.commit()

    def record(
        self,
        attempt_id: str,
        event_type: str,
        *,
        version: int | None = None,
        payload: dict[str, Any] | None = None,
        timestamp: float | None = None,
    ) -> LineageEvent:
        event = LineageEvent(
            event_id=str(uuid.uuid4()),
            attempt_id=attempt_id,
            event_type=event_type,
            timestamp=timestamp if timestamp is not None else time.time(),
            version=version,
            payload=dict(payload or {}),
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO lineage_events(event_id, attempt_id, event_type, timestamp, version, payload) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    event.event_id,
                    event.attempt_id,
                    event.event_type,
                    event.timestamp,
                    event.version,
                    json.dumps(event.payload),
                ),
            )
            conn.commit()
        return event

    def events_for(self, attempt_id: str) -> list[LineageEvent]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT event_id, attempt_id, event_type, timestamp, version, payload "
                "FROM lineage_events WHERE attempt_id = ? ORDER BY timestamp ASC",
                (attempt_id,),
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def recent(self, limit: int = 50) -> list[LineageEvent]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT event_id, attempt_id, event_type, timestamp, version, payload "
                "FROM lineage_events ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def latest_deployed_version_for(self, attempt_id: str) -> int | None:
        for event in reversed(self.events_for(attempt_id)):
            if event.event_type in ("promote", "deploy_canary") and event.version is not None:
                return event.version
        return None

    @staticmethod
    def _row_to_event(row: tuple) -> LineageEvent:
        event_id, attempt_id, event_type, timestamp, version, payload = row
        try:
            parsed = json.loads(payload) if payload else {}
        except json.JSONDecodeError:
            parsed = {"raw": payload}
        return LineageEvent(
            event_id=event_id,
            attempt_id=attempt_id,
            event_type=event_type,
            timestamp=float(timestamp),
            version=int(version) if version is not None else None,
            payload=parsed if isinstance(parsed, dict) else {"raw": parsed},
        )
