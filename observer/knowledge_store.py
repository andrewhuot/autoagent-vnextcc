"""SQLite-backed knowledge entry store."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class KnowledgeStore:
    """Store for mined knowledge entries."""

    def __init__(self, db_path: str = ".autoagent/knowledge.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize knowledge entries table."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_entries (
                    pattern_id TEXT PRIMARY KEY,
                    pattern_type TEXT NOT NULL,
                    description TEXT NOT NULL,
                    evidence_conversations TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    applicable_intents TEXT NOT NULL,
                    suggested_application TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    applied_at REAL,
                    impact_score REAL
                )
            """)
            conn.commit()

    def create(self, entry: dict[str, Any]) -> None:
        """Create a new knowledge entry."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO knowledge_entries
                (pattern_id, pattern_type, description, evidence_conversations,
                 confidence, applicable_intents, suggested_application, status,
                 created_at, applied_at, impact_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry["pattern_id"],
                    entry["pattern_type"],
                    entry["description"],
                    json.dumps(entry["evidence_conversations"]),
                    entry["confidence"],
                    json.dumps(entry["applicable_intents"]),
                    entry["suggested_application"],
                    entry.get("status", "draft"),
                    entry.get("created_at", time.time()),
                    entry.get("applied_at"),
                    entry.get("impact_score"),
                ),
            )
            conn.commit()

    def list(
        self, status: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """List knowledge entries with optional status filter."""
        with sqlite3.connect(self.db_path) as conn:
            if status:
                rows = conn.execute(
                    """
                    SELECT * FROM knowledge_entries
                    WHERE status = ?
                    ORDER BY confidence DESC, created_at DESC
                    LIMIT ?
                    """,
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM knowledge_entries
                    ORDER BY confidence DESC, created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()

        entries = []
        for row in rows:
            entries.append(
                {
                    "pattern_id": row[0],
                    "pattern_type": row[1],
                    "description": row[2],
                    "evidence_conversations": json.loads(row[3]),
                    "confidence": row[4],
                    "applicable_intents": json.loads(row[5]),
                    "suggested_application": row[6],
                    "status": row[7],
                    "created_at": row[8],
                    "applied_at": row[9],
                    "impact_score": row[10],
                }
            )
        return entries

    def get(self, pattern_id: str) -> dict[str, Any] | None:
        """Get a specific knowledge entry."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM knowledge_entries WHERE pattern_id = ?", (pattern_id,)
            ).fetchone()

        if not row:
            return None

        return {
            "pattern_id": row[0],
            "pattern_type": row[1],
            "description": row[2],
            "evidence_conversations": json.loads(row[3]),
            "confidence": row[4],
            "applicable_intents": json.loads(row[5]),
            "suggested_application": row[6],
            "status": row[7],
            "created_at": row[8],
            "applied_at": row[9],
            "impact_score": row[10],
        }

    def update_status(self, pattern_id: str, status: str) -> bool:
        """Update entry status."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE knowledge_entries SET status = ? WHERE pattern_id = ?",
                (status, pattern_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def mark_applied(self, pattern_id: str, impact_score: float | None = None) -> bool:
        """Mark entry as applied."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                UPDATE knowledge_entries
                SET status = 'applied', applied_at = ?, impact_score = ?
                WHERE pattern_id = ?
                """,
                (time.time(), impact_score, pattern_id),
            )
            conn.commit()
            return cursor.rowcount > 0
