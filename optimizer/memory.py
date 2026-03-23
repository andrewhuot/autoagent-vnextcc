"""SQLite-backed optimization attempt memory."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass
class OptimizationAttempt:
    attempt_id: str
    timestamp: float
    change_description: str
    config_diff: str
    status: str  # "accepted", "rejected_invalid", "rejected_safety", "rejected_no_improvement", "rejected_regression", "rejected_noop"
    config_section: str = ""
    score_before: float = 0.0
    score_after: float = 0.0
    health_context: str = ""  # JSON string of health metrics that triggered this


class OptimizationMemory:
    """Persistent store for optimization attempts using SQLite."""

    def __init__(self, db_path: str = "optimizer_memory.db") -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Create the attempts table if it doesn't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS attempts (
                    attempt_id TEXT PRIMARY KEY,
                    timestamp REAL NOT NULL,
                    change_description TEXT NOT NULL,
                    config_diff TEXT NOT NULL,
                    config_section TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    score_before REAL DEFAULT 0.0,
                    score_after REAL DEFAULT 0.0,
                    health_context TEXT DEFAULT ''
                )
                """
            )
            # Lightweight migration for DBs created before config_section existed.
            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(attempts)").fetchall()
            }
            if "config_section" not in columns:
                conn.execute(
                    "ALTER TABLE attempts ADD COLUMN config_section TEXT NOT NULL DEFAULT ''"
                )
            conn.commit()

    def log(self, attempt: OptimizationAttempt) -> None:
        """Insert an optimization attempt into the database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO attempts
                    (attempt_id, timestamp, change_description, config_diff, config_section, status,
                     score_before, score_after, health_context)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt.attempt_id,
                    attempt.timestamp,
                    attempt.change_description,
                    attempt.config_diff,
                    attempt.config_section,
                    attempt.status,
                    attempt.score_before,
                    attempt.score_after,
                    attempt.health_context,
                ),
            )
            conn.commit()

    def recent(self, limit: int = 20) -> list[OptimizationAttempt]:
        """Get the most recent attempts ordered by timestamp descending."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT attempt_id, timestamp, change_description, config_diff, config_section,
                       status, score_before, score_after, health_context
                FROM attempts
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [self._row_to_attempt(row) for row in rows]

    def accepted(self, limit: int = 10) -> list[OptimizationAttempt]:
        """Get recently accepted attempts."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT attempt_id, timestamp, change_description, config_diff, config_section,
                       status, score_before, score_after, health_context
                FROM attempts
                WHERE status = 'accepted'
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [self._row_to_attempt(row) for row in rows]

    def get_all(self) -> list[OptimizationAttempt]:
        """Get all attempts ordered by timestamp descending."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT attempt_id, timestamp, change_description, config_diff, config_section,
                       status, score_before, score_after, health_context
                FROM attempts
                ORDER BY timestamp DESC
                """
            ).fetchall()
            return [self._row_to_attempt(row) for row in rows]

    def clear(self) -> None:
        """Delete all attempts (for testing)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM attempts")
            conn.commit()

    @staticmethod
    def _row_to_attempt(row: tuple) -> OptimizationAttempt:
        """Convert a database row tuple to an OptimizationAttempt."""
        return OptimizationAttempt(
            attempt_id=row[0],
            timestamp=row[1],
            change_description=row[2],
            config_diff=row[3],
            config_section=row[4],
            status=row[5],
            score_before=row[6],
            score_after=row[7],
            health_context=row[8],
        )
