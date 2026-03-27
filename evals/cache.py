"""Eval cache store for deterministic run reuse."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class EvalCacheStore:
    """SQLite-backed cache keyed by eval fingerprint."""

    def __init__(self, db_path: str = ".autoagent/eval_cache.db") -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS eval_cache (
                    cache_key TEXT PRIMARY KEY,
                    created_at REAL NOT NULL,
                    summary TEXT NOT NULL,
                    case_payloads TEXT NOT NULL,
                    metadata TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_eval_cache_created ON eval_cache(created_at DESC)"
            )
            conn.commit()

    def get(self, cache_key: str) -> dict[str, Any] | None:
        """Return cached payload for key, or None when absent."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT summary, case_payloads, metadata
                FROM eval_cache
                WHERE cache_key = ?
                """,
                (cache_key,),
            ).fetchone()
        if row is None:
            return None
        return {
            "summary": json.loads(row[0]),
            "case_payloads": json.loads(row[1]),
            "metadata": json.loads(row[2]),
        }

    def put(
        self,
        *,
        cache_key: str,
        summary: dict[str, Any],
        case_payloads: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> None:
        """Persist one cache record."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO eval_cache (
                    cache_key, created_at, summary, case_payloads, metadata
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    cache_key,
                    time.time(),
                    json.dumps(summary, sort_keys=True, default=str),
                    json.dumps(case_payloads, sort_keys=True, default=str),
                    json.dumps(metadata, sort_keys=True, default=str),
                ),
            )
            conn.commit()
