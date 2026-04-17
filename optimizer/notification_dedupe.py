"""SQLite-backed dedupe store for notification emissions (R6.4 / R6.5).

Collapses repeated (event_type, workspace, signature) tuples within a
configurable time window so the continuous-improvement loop cannot spam
the same alert on every cycle.

Schema is a single ``notification_log`` table. Lookups are indexed by the
full dedupe key plus the ISO timestamp so ``was_sent_within`` stays cheap.

Defaults to ``<workspace>/.agentlab/notification_log.db``; callers pass a
concrete path so this module does not have to reach into workspace state.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


class NotificationDedupeStore:
    """Dedupe store backed by a single SQLite table.

    The store never raises from a dedupe query on a fresh db — it creates
    the table on construction, before the first query.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notification_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    workspace TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    sent_at_iso TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_dedupe
                ON notification_log(event_type, workspace, signature, sent_at_iso)
                """
            )
            conn.commit()

    # ------------------------------------------------------------------

    def record_sent(
        self,
        event_type: str,
        workspace: str,
        signature: str,
        *,
        sent_at: datetime,
    ) -> None:
        """Persist a "successfully sent" marker for dedupe lookups."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO notification_log
                (event_type, workspace, signature, sent_at_iso)
                VALUES (?, ?, ?, ?)
                """,
                (event_type, workspace, signature, sent_at.isoformat()),
            )
            conn.commit()

    def was_sent_within(
        self,
        event_type: str,
        workspace: str,
        signature: str,
        *,
        window_seconds: int,
        now: datetime,
    ) -> bool:
        """Return True iff a matching row exists with sent_at in [now-window, now]."""
        threshold = now - timedelta(seconds=window_seconds)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT 1 FROM notification_log
                WHERE event_type = ?
                  AND workspace = ?
                  AND signature = ?
                  AND sent_at_iso >= ?
                LIMIT 1
                """,
                (event_type, workspace, signature, threshold.isoformat()),
            ).fetchone()
        return row is not None
