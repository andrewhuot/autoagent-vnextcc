"""Audit logging for permission checks.

All allow/deny decisions are written to a SQLite database so that
operators can review the agent's permission history, detect anomalies,
and demonstrate compliance.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from control.types import ActionDecision


@dataclass
class AuditEntry:
    """A single immutable record of a permission decision."""

    entry_id: str
    timestamp: str
    action_type: str
    resource: str
    requestor: str
    decision: str       # "granted" or "denied"
    reason: str
    profile: str
    tier: str
    environment: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "timestamp": self.timestamp,
            "action_type": self.action_type,
            "resource": self.resource,
            "requestor": self.requestor,
            "decision": self.decision,
            "reason": self.reason,
            "profile": self.profile,
            "tier": self.tier,
            "environment": self.environment,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AuditEntry":
        import json as _json

        metadata = d.get("metadata", {})
        if isinstance(metadata, str):
            try:
                metadata = _json.loads(metadata)
            except (ValueError, TypeError):
                metadata = {}
        return cls(
            entry_id=d["entry_id"],
            timestamp=d["timestamp"],
            action_type=d["action_type"],
            resource=d["resource"],
            requestor=d["requestor"],
            decision=d["decision"],
            reason=d["reason"],
            profile=d.get("profile", ""),
            tier=d["tier"],
            environment=d["environment"],
            metadata=metadata,
        )


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS audit_log (
    entry_id    TEXT PRIMARY KEY,
    timestamp   TEXT NOT NULL,
    action_type TEXT NOT NULL,
    resource    TEXT NOT NULL,
    requestor   TEXT NOT NULL,
    decision    TEXT NOT NULL,
    reason      TEXT NOT NULL,
    profile     TEXT NOT NULL,
    tier        TEXT NOT NULL,
    environment TEXT NOT NULL,
    metadata    TEXT NOT NULL
);
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_audit_timestamp  ON audit_log (timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_decision   ON audit_log (decision);
CREATE INDEX IF NOT EXISTS idx_audit_action     ON audit_log (action_type);
CREATE INDEX IF NOT EXISTS idx_audit_resource   ON audit_log (resource);
"""


class AuditLog:
    """SQLite-backed append-only audit log for permission decisions.

    Follows the same pattern as other SQLite stores in the project
    (e.g. ConversationStore, CostTracker).
    """

    def __init__(self, db_path: str = ".autoagent/audit.db") -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create table and indexes if they do not exist."""
        with self._connect() as conn:
            conn.executescript(_CREATE_TABLE_SQL + _CREATE_INDEX_SQL)

    def _row_to_entry(self, row: sqlite3.Row) -> AuditEntry:
        import json as _json

        raw_metadata = row["metadata"]
        try:
            metadata = _json.loads(raw_metadata)
        except (ValueError, TypeError):
            metadata = {}
        return AuditEntry(
            entry_id=row["entry_id"],
            timestamp=row["timestamp"],
            action_type=row["action_type"],
            resource=row["resource"],
            requestor=row["requestor"],
            decision=row["decision"],
            reason=row["reason"],
            profile=row["profile"],
            tier=row["tier"],
            environment=row["environment"],
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(self, decision: ActionDecision, profile: str = "") -> str:
        """Record an ActionDecision and return the generated entry_id.

        Args:
            decision: The ActionDecision produced by PermissionEngine.evaluate().
            profile:  Name of the active permission profile (optional).

        Returns:
            The UUID entry_id of the newly created audit record.
        """
        import json as _json

        entry_id = uuid.uuid4().hex
        decision_str = "granted" if decision.allowed else "denied"
        req = decision.request
        metadata_json = _json.dumps(req.metadata, sort_keys=True)

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_log
                    (entry_id, timestamp, action_type, resource, requestor,
                     decision, reason, profile, tier, environment, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    decision.timestamp or datetime.now(timezone.utc).isoformat(),
                    req.action_type,
                    req.resource,
                    req.requestor,
                    decision_str,
                    decision.reason,
                    profile,
                    req.tier_required.value,
                    req.environment.value,
                    metadata_json,
                ),
            )
        return entry_id

    def query(
        self,
        action_type: str | None = None,
        resource: str | None = None,
        decision: str | None = None,
        limit: int = 100,
    ) -> list[AuditEntry]:
        """Query audit entries with optional filters.

        Args:
            action_type: Filter by action type (e.g. "deploy").
            resource:    Filter by resource name (exact match).
            decision:    Filter by decision: "granted" or "denied".
            limit:       Maximum number of entries to return (default 100).

        Returns:
            List of matching AuditEntry objects, newest first.
        """
        sql = "SELECT * FROM audit_log WHERE 1=1"
        params: list[Any] = []
        if action_type is not None:
            sql += " AND action_type = ?"
            params.append(action_type)
        if resource is not None:
            sql += " AND resource = ?"
            params.append(resource)
        if decision is not None:
            sql += " AND decision = ?"
            params.append(decision)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def count(self, decision: str | None = None) -> int:
        """Return total number of audit entries, optionally filtered by decision."""
        if decision is not None:
            sql = "SELECT COUNT(*) FROM audit_log WHERE decision = ?"
            params: tuple[Any, ...] = (decision,)
        else:
            sql = "SELECT COUNT(*) FROM audit_log"
            params = ()

        with self._connect() as conn:
            (total,) = conn.execute(sql, params).fetchone()
        return int(total)

    def recent(self, limit: int = 20) -> list[AuditEntry]:
        """Return the most recent audit entries.

        Args:
            limit: Maximum number of entries to return (default 20).

        Returns:
            List of AuditEntry objects ordered newest-first.
        """
        return self.query(limit=limit)
