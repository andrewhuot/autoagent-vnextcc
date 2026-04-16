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


# Event type constants (stable strings; never rename — api/ and cli/ consume these).
EVENT_EVAL_RUN = "eval_run"
EVENT_ATTEMPT = "attempt"
EVENT_REJECTION = "rejection"
EVENT_DEPLOYMENT = "deployment"
EVENT_MEASUREMENT = "measurement"


@dataclass
class LineageEvent:
    event_id: str
    attempt_id: str
    event_type: str  # deploy_canary | promote | rollback | measurement | accept | reject
    timestamp: float
    version: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class AttemptLineageView:
    """Denormalized view of one attempt's full lineage chain.

    Derived from the append-only lineage_events stream by
    ``ImprovementLineageStore.view_attempt()``. Any field may be ``None``
    when the corresponding event has not yet been emitted.
    """
    attempt_id: str
    eval_run_id: str | None = None
    deployment_id: str | None = None
    deployed_version: int | None = None
    measurement_id: str | None = None
    composite_delta: float | None = None
    status: str | None = None
    score_before: float | None = None
    score_after: float | None = None
    parent_attempt_id: str | None = None
    rejection_reason: str | None = None
    rejection_detail: str | None = None
    rolled_back: bool = False
    events: list[LineageEvent] = field(default_factory=list)


class ImprovementLineageStore:
    """Append-only store of post-proposal lineage events."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
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

    def record_eval_run(
        self,
        *,
        eval_run_id: str,
        attempt_id: str = "",
        config_path: str = "",
        composite_score: float | None = None,
        case_count: int | None = None,
        **extra: Any,
    ) -> LineageEvent:
        payload = {
            "eval_run_id": eval_run_id,
            "config_path": config_path,
            "composite_score": composite_score,
            "case_count": case_count,
            **extra,
        }
        return self.record(attempt_id, EVENT_EVAL_RUN, payload=payload)

    def record_attempt(
        self,
        *,
        attempt_id: str,
        status: str,
        score_before: float | None = None,
        score_after: float | None = None,
        eval_run_id: str | None = None,
        parent_attempt_id: str | None = None,
        **extra: Any,
    ) -> LineageEvent:
        payload = {
            "status": status,
            "score_before": score_before,
            "score_after": score_after,
            "eval_run_id": eval_run_id,
            "parent_attempt_id": parent_attempt_id,
            **extra,
        }
        return self.record(attempt_id, EVENT_ATTEMPT, payload=payload)

    def record_rejection(
        self,
        *,
        attempt_id: str,
        reason: str,
        detail: str = "",
        **extra: Any,
    ) -> LineageEvent:
        payload = {"reason": reason, "detail": detail, **extra}
        return self.record(attempt_id, EVENT_REJECTION, payload=payload)

    def record_deployment(
        self,
        *,
        attempt_id: str,
        deployment_id: str,
        version: int | None = None,
        **extra: Any,
    ) -> LineageEvent:
        payload = {"deployment_id": deployment_id, **extra}
        return self.record(attempt_id, EVENT_DEPLOYMENT, version=version, payload=payload)

    def record_measurement(
        self,
        *,
        attempt_id: str,
        measurement_id: str,
        composite_delta: float | None = None,
        eval_run_id: str | None = None,
        **extra: Any,
    ) -> LineageEvent:
        payload = {
            "measurement_id": measurement_id,
            "composite_delta": composite_delta,
            "eval_run_id": eval_run_id,
            **extra,
        }
        return self.record(attempt_id, EVENT_MEASUREMENT, payload=payload)

    def events_for(self, attempt_id: str) -> list[LineageEvent]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT event_id, attempt_id, event_type, timestamp, version, payload "
                "FROM lineage_events WHERE attempt_id = ? ORDER BY timestamp ASC",
                (attempt_id,),
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def view_attempt(self, attempt_id: str) -> AttemptLineageView:
        """Flatten the event stream for *attempt_id* into a denormalized view.

        Events are processed in chronological order; later events of the
        same kind overwrite earlier values. Recognises both new event types
        (``attempt``, ``deployment``, ``measurement``, ``rejection``,
        ``eval_run``) and legacy types still emitted by the API path
        (``promote``, ``deploy_canary``, ``rollback``).
        """
        events = self.events_for(attempt_id)
        view = AttemptLineageView(attempt_id=attempt_id, events=events)
        for ev in events:
            t = ev.event_type
            p = ev.payload
            if t == EVENT_EVAL_RUN:
                if p.get("eval_run_id"):
                    view.eval_run_id = p["eval_run_id"]
            elif t == EVENT_ATTEMPT:
                view.status = p.get("status", view.status)
                if p.get("eval_run_id"):
                    view.eval_run_id = p["eval_run_id"]
                if p.get("parent_attempt_id"):
                    view.parent_attempt_id = p["parent_attempt_id"]
                if p.get("score_before") is not None:
                    view.score_before = p["score_before"]
                if p.get("score_after") is not None:
                    view.score_after = p["score_after"]
            elif t == EVENT_REJECTION:
                view.rejection_reason = p.get("reason", view.rejection_reason)
                view.rejection_detail = p.get("detail", view.rejection_detail)
            elif t in (EVENT_DEPLOYMENT, "promote", "deploy_canary"):
                if p.get("deployment_id"):
                    view.deployment_id = p["deployment_id"]
                if ev.version is not None:
                    view.deployed_version = ev.version
            elif t == "rollback":
                view.rolled_back = True
            elif t == EVENT_MEASUREMENT:
                if p.get("measurement_id"):
                    view.measurement_id = p["measurement_id"]
                if p.get("composite_delta") is not None:
                    view.composite_delta = p["composite_delta"]
        return view

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
