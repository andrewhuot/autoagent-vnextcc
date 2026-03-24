"""Durable eval history persistence with provenance metadata."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class EvalHistoryStore:
    """SQLite-backed history for eval run summaries and case-level results."""

    def __init__(self, db_path: str = "eval_history.db") -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS eval_runs (
                    run_id TEXT PRIMARY KEY,
                    created_at REAL NOT NULL,
                    provenance TEXT NOT NULL,
                    summary TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS eval_case_results (
                    run_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (run_id, case_id)
                )
                """
            )
            conn.commit()

    def log_run(
        self,
        *,
        run_id: str,
        summary: dict[str, Any],
        case_payloads: list[dict[str, Any]],
        provenance: dict[str, Any],
    ) -> None:
        """Persist one completed eval run."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO eval_runs (run_id, created_at, provenance, summary)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, time.time(), json.dumps(provenance), json.dumps(summary)),
            )
            for payload in case_payloads:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO eval_case_results (run_id, case_id, category, payload)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        payload.get("case_id", ""),
                        payload.get("category", "unknown"),
                        json.dumps(payload),
                    ),
                )
            conn.commit()

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent eval run summaries with provenance."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT run_id, created_at, provenance, summary
                FROM eval_runs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        output: list[dict[str, Any]] = []
        for row in rows:
            output.append(
                {
                    "run_id": row[0],
                    "created_at": row[1],
                    "provenance": json.loads(row[2]),
                    "summary": json.loads(row[3]),
                }
            )
        return output

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Return one run with case-level detail."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT run_id, created_at, provenance, summary FROM eval_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                return None

            case_rows = conn.execute(
                "SELECT payload FROM eval_case_results WHERE run_id = ? ORDER BY case_id ASC",
                (run_id,),
            ).fetchall()

        return {
            "run_id": row[0],
            "created_at": row[1],
            "provenance": json.loads(row[2]),
            "summary": json.loads(row[3]),
            "cases": [json.loads(item[0]) for item in case_rows],
        }
