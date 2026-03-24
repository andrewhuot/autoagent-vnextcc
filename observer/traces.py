"""ADK Event/Trace-based diagnosis — SQLite-backed trace store and collector."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class TraceEventType(str, Enum):
    """Types of events captured during agent invocations."""

    tool_call = "tool_call"
    tool_response = "tool_response"
    state_delta = "state_delta"
    artifact_delta = "artifact_delta"
    error = "error"
    agent_transfer = "agent_transfer"
    model_call = "model_call"
    model_response = "model_response"
    safety_flag = "safety_flag"
    partial_response = "partial_response"


@dataclass
class TraceEvent:
    """A single event within a trace."""

    event_id: str
    trace_id: str
    event_type: str  # TraceEventType value
    timestamp: float
    invocation_id: str
    session_id: str
    agent_path: str  # e.g., "root/support/orders"
    branch: str  # config version label
    tool_name: str | None = None
    tool_input: str | None = None  # JSON string
    tool_output: str | None = None  # JSON string
    latency_ms: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    error_message: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class TraceSpan:
    """A span representing a logical operation within a trace."""

    span_id: str
    trace_id: str
    parent_span_id: str | None
    operation: str
    agent_path: str
    start_time: float
    end_time: float
    status: str  # "ok", "error"
    attributes: dict[str, str] = field(default_factory=dict)


class TraceStore:
    """SQLite-backed persistent store for trace events and spans."""

    def __init__(self, db_path: str = "traces.db") -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Create trace_events and trace_spans tables with indexes."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trace_events (
                    event_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    invocation_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    agent_path TEXT NOT NULL,
                    branch TEXT NOT NULL DEFAULT '',
                    tool_name TEXT,
                    tool_input TEXT,
                    tool_output TEXT,
                    latency_ms REAL NOT NULL DEFAULT 0.0,
                    tokens_in INTEGER NOT NULL DEFAULT 0,
                    tokens_out INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trace_spans (
                    span_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    parent_span_id TEXT,
                    operation TEXT NOT NULL,
                    agent_path TEXT NOT NULL,
                    start_time REAL NOT NULL,
                    end_time REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'ok',
                    attributes TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_te_trace_id ON trace_events(trace_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_te_session_id ON trace_events(session_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_te_invocation_id ON trace_events(invocation_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_te_agent_path ON trace_events(agent_path)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_te_timestamp ON trace_events(timestamp DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ts_trace_id ON trace_spans(trace_id)"
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    def log_event(self, event: TraceEvent) -> None:
        """Insert a trace event into the database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO trace_events (
                    event_id, trace_id, event_type, timestamp, invocation_id,
                    session_id, agent_path, branch, tool_name, tool_input,
                    tool_output, latency_ms, tokens_in, tokens_out,
                    error_message, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.trace_id,
                    event.event_type,
                    event.timestamp,
                    event.invocation_id,
                    event.session_id,
                    event.agent_path,
                    event.branch,
                    event.tool_name,
                    event.tool_input,
                    event.tool_output,
                    event.latency_ms,
                    event.tokens_in,
                    event.tokens_out,
                    event.error_message,
                    json.dumps(event.metadata),
                ),
            )
            conn.commit()

    def log_span(self, span: TraceSpan) -> None:
        """Insert a trace span into the database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO trace_spans (
                    span_id, trace_id, parent_span_id, operation, agent_path,
                    start_time, end_time, status, attributes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    span.span_id,
                    span.trace_id,
                    span.parent_span_id,
                    span.operation,
                    span.agent_path,
                    span.start_time,
                    span.end_time,
                    span.status,
                    json.dumps(span.attributes),
                ),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def get_trace(self, trace_id: str) -> list[TraceEvent]:
        """Get all events for a trace, ordered by timestamp."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM trace_events WHERE trace_id = ? ORDER BY timestamp ASC",
                (trace_id,),
            ).fetchall()
            return [self._row_to_event(row) for row in rows]

    def get_spans(self, trace_id: str) -> list[TraceSpan]:
        """Get all spans for a trace."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM trace_spans WHERE trace_id = ? ORDER BY start_time ASC",
                (trace_id,),
            ).fetchall()
            return [self._row_to_span(row) for row in rows]

    def get_recent_events(self, limit: int = 100) -> list[TraceEvent]:
        """Get the most recent events ordered by timestamp descending."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM trace_events ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._row_to_event(row) for row in rows]

    def get_events_by_session(self, session_id: str) -> list[TraceEvent]:
        """Get all events for a session, ordered by timestamp."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM trace_events WHERE session_id = ? ORDER BY timestamp ASC",
                (session_id,),
            ).fetchall()
            return [self._row_to_event(row) for row in rows]

    def get_error_events(self, limit: int = 50) -> list[TraceEvent]:
        """Get events where event_type is 'error'."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM trace_events WHERE event_type = ? ORDER BY timestamp DESC LIMIT ?",
                (TraceEventType.error.value, limit),
            ).fetchall()
            return [self._row_to_event(row) for row in rows]

    def get_events_by_agent_path(self, agent_path: str, limit: int = 100) -> list[TraceEvent]:
        """Get events for a specific agent path."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM trace_events WHERE agent_path = ? ORDER BY timestamp DESC LIMIT ?",
                (agent_path, limit),
            ).fetchall()
            return [self._row_to_event(row) for row in rows]

    def count_events(self) -> int:
        """Return total count of trace events."""
        with sqlite3.connect(self.db_path) as conn:
            result = conn.execute("SELECT COUNT(*) FROM trace_events").fetchone()
            return result[0] if result else 0

    def search_events(
        self,
        event_type: str | None = None,
        agent_path: str | None = None,
        since: float | None = None,
        limit: int = 100,
    ) -> list[TraceEvent]:
        """Search events with optional filters on type, agent path, and time."""
        clauses: list[str] = []
        params: list[str | float | int] = []

        if event_type is not None:
            clauses.append("event_type = ?")
            params.append(event_type)
        if agent_path is not None:
            clauses.append("agent_path = ?")
            params.append(agent_path)
        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(since)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT * FROM trace_events {where} ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_event(row) for row in rows]

    # ------------------------------------------------------------------
    # Row converters
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_event(row: tuple) -> TraceEvent:
        """Convert a database row tuple to a TraceEvent."""
        return TraceEvent(
            event_id=row[0],
            trace_id=row[1],
            event_type=row[2],
            timestamp=row[3],
            invocation_id=row[4],
            session_id=row[5],
            agent_path=row[6],
            branch=row[7],
            tool_name=row[8],
            tool_input=row[9],
            tool_output=row[10],
            latency_ms=row[11],
            tokens_in=row[12],
            tokens_out=row[13],
            error_message=row[14],
            metadata=json.loads(row[15]) if row[15] else {},
        )

    @staticmethod
    def _row_to_span(row: tuple) -> TraceSpan:
        """Convert a database row tuple to a TraceSpan."""
        return TraceSpan(
            span_id=row[0],
            trace_id=row[1],
            parent_span_id=row[2],
            operation=row[3],
            agent_path=row[4],
            start_time=row[5],
            end_time=row[6],
            status=row[7],
            attributes=json.loads(row[8]) if row[8] else {},
        )


def _short_uuid() -> str:
    """Generate a 12-character UUID prefix."""
    return str(uuid.uuid4())[:12]


class TraceCollector:
    """High-level API for recording trace events during agent invocations."""

    def __init__(self, store: TraceStore) -> None:
        self.store = store

    def start_trace(
        self,
        session_id: str,
        invocation_id: str,
        agent_path: str,
        branch: str,
    ) -> str:
        """Start a new trace and return its trace_id."""
        trace_id = _short_uuid()
        event = TraceEvent(
            event_id=_short_uuid(),
            trace_id=trace_id,
            event_type=TraceEventType.state_delta.value,
            timestamp=time.time(),
            invocation_id=invocation_id,
            session_id=session_id,
            agent_path=agent_path,
            branch=branch,
            metadata={"action": "trace_start"},
        )
        self.store.log_event(event)
        return trace_id

    def record_tool_call(
        self,
        trace_id: str,
        tool_name: str,
        tool_input: dict,
        agent_path: str,
        session_id: str,
        invocation_id: str,
        branch: str,
    ) -> str:
        """Record a tool call event and return the event_id."""
        event_id = _short_uuid()
        event = TraceEvent(
            event_id=event_id,
            trace_id=trace_id,
            event_type=TraceEventType.tool_call.value,
            timestamp=time.time(),
            invocation_id=invocation_id,
            session_id=session_id,
            agent_path=agent_path,
            branch=branch,
            tool_name=tool_name,
            tool_input=json.dumps(tool_input),
        )
        self.store.log_event(event)
        return event_id

    def record_tool_response(
        self,
        trace_id: str,
        tool_name: str,
        tool_output: dict,
        latency_ms: float,
        agent_path: str,
        session_id: str,
        invocation_id: str,
        branch: str,
        error: str | None = None,
    ) -> str:
        """Record a tool response event and return the event_id."""
        event_id = _short_uuid()
        event_type = TraceEventType.error.value if error else TraceEventType.tool_response.value
        event = TraceEvent(
            event_id=event_id,
            trace_id=trace_id,
            event_type=event_type,
            timestamp=time.time(),
            invocation_id=invocation_id,
            session_id=session_id,
            agent_path=agent_path,
            branch=branch,
            tool_name=tool_name,
            tool_output=json.dumps(tool_output),
            latency_ms=latency_ms,
            error_message=error,
        )
        self.store.log_event(event)
        return event_id

    def record_model_call(
        self,
        trace_id: str,
        tokens_in: int,
        agent_path: str,
        session_id: str,
        invocation_id: str,
        branch: str,
    ) -> str:
        """Record a model call event and return the event_id."""
        event_id = _short_uuid()
        event = TraceEvent(
            event_id=event_id,
            trace_id=trace_id,
            event_type=TraceEventType.model_call.value,
            timestamp=time.time(),
            invocation_id=invocation_id,
            session_id=session_id,
            agent_path=agent_path,
            branch=branch,
            tokens_in=tokens_in,
        )
        self.store.log_event(event)
        return event_id

    def record_model_response(
        self,
        trace_id: str,
        tokens_out: int,
        latency_ms: float,
        agent_path: str,
        session_id: str,
        invocation_id: str,
        branch: str,
    ) -> str:
        """Record a model response event and return the event_id."""
        event_id = _short_uuid()
        event = TraceEvent(
            event_id=event_id,
            trace_id=trace_id,
            event_type=TraceEventType.model_response.value,
            timestamp=time.time(),
            invocation_id=invocation_id,
            session_id=session_id,
            agent_path=agent_path,
            branch=branch,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
        )
        self.store.log_event(event)
        return event_id

    def record_error(
        self,
        trace_id: str,
        error_message: str,
        agent_path: str,
        session_id: str,
        invocation_id: str,
        branch: str,
    ) -> str:
        """Record an error event and return the event_id."""
        event_id = _short_uuid()
        event = TraceEvent(
            event_id=event_id,
            trace_id=trace_id,
            event_type=TraceEventType.error.value,
            timestamp=time.time(),
            invocation_id=invocation_id,
            session_id=session_id,
            agent_path=agent_path,
            branch=branch,
            error_message=error_message,
        )
        self.store.log_event(event)
        return event_id

    def record_agent_transfer(
        self,
        trace_id: str,
        from_agent: str,
        to_agent: str,
        session_id: str,
        invocation_id: str,
        branch: str,
    ) -> str:
        """Record an agent transfer event and return the event_id."""
        event_id = _short_uuid()
        event = TraceEvent(
            event_id=event_id,
            trace_id=trace_id,
            event_type=TraceEventType.agent_transfer.value,
            timestamp=time.time(),
            invocation_id=invocation_id,
            session_id=session_id,
            agent_path=from_agent,
            branch=branch,
            metadata={"from_agent": from_agent, "to_agent": to_agent},
        )
        self.store.log_event(event)
        return event_id
