"""Audit log — immutable event store with SQLite persistence."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class AuditEntry:
    entry_id: str
    timestamp: str
    user_id: str
    action: str
    resource: str
    details: dict
    ip_address: str = ""

    def to_dict(self) -> dict:
        return {
            "entry_id": self.entry_id,
            "timestamp": self.timestamp,
            "user_id": self.user_id,
            "action": self.action,
            "resource": self.resource,
            "details": self.details,
            "ip_address": self.ip_address,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AuditEntry":
        details = d.get("details", {})
        if isinstance(details, str):
            details = json.loads(details)
        return cls(
            entry_id=d["entry_id"],
            timestamp=d["timestamp"],
            user_id=d["user_id"],
            action=d["action"],
            resource=d["resource"],
            details=details,
            ip_address=d.get("ip_address", ""),
        )


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class AuditStore:
    """Append-only audit log persisted in SQLite."""

    def __init__(self, db_path: str = ".autoagent/audit.db") -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    entry_id   TEXT PRIMARY KEY,
                    timestamp  TEXT NOT NULL,
                    user_id    TEXT NOT NULL,
                    action     TEXT NOT NULL,
                    resource   TEXT NOT NULL,
                    details    TEXT NOT NULL DEFAULT '{}',
                    ip_address TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(timestamp)"
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(self, entry: AuditEntry) -> str:
        """Persist an audit entry and return its entry_id."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_log
                    (entry_id, timestamp, user_id, action, resource, details, ip_address)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.entry_id,
                    entry.timestamp,
                    entry.user_id,
                    entry.action,
                    entry.resource,
                    json.dumps(entry.details),
                    entry.ip_address,
                ),
            )
            conn.commit()
        return entry.entry_id

    def query(
        self,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 100,
    ) -> list[AuditEntry]:
        """Query audit entries with optional filters."""
        clauses: list[str] = []
        params: list = []

        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        if action is not None:
            clauses.append("action = ?")
            params.append(action)
        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(since)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM audit_log {where} ORDER BY timestamp DESC LIMIT ?",
                params,
            ).fetchall()
        return [AuditEntry.from_dict(dict(r)) for r in rows]

    def count(self, action: Optional[str] = None) -> int:
        """Count total audit entries, optionally filtered by action."""
        if action is not None:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM audit_log WHERE action = ?", (action,)
                ).fetchone()
        else:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM audit_log"
                ).fetchone()
        return row["cnt"] if row else 0
