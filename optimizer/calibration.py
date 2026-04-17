"""Calibration store for predicted-vs-actual optimization outcomes.

Owns the ``predicted_vs_actual`` SQLite table and exposes a
per-``(surface, strategy)`` calibration factor — the mean residual
``actual_delta - predicted_effectiveness`` over the most recent ``n``
rows. Callers use this to debias future effectiveness predictions.

Sparse history (fewer than ``n`` rows) returns ``None`` so callers fall
through to their existing render paths rather than pretending a zero
correction is meaningful.

This module stands alone: no imports from other ``optimizer`` modules.
Later tasks wire it into the loop and CLI surfaces.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path


DEFAULT_DB_PATH = ".agentlab/calibration.db"


class CalibrationStore:
    """SQLite-backed table of predicted-vs-actual optimization attempts."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS predicted_vs_actual (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    attempt_id TEXT NOT NULL,
                    surface TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    predicted_effectiveness REAL NOT NULL,
                    actual_delta REAL NOT NULL,
                    recorded_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_pva_surface_strategy "
                "ON predicted_vs_actual(surface, strategy)"
            )
            conn.commit()

    def record(
        self,
        *,
        attempt_id: str,
        surface: str,
        strategy: str,
        predicted_effectiveness: float,
        actual_delta: float,
        recorded_at: float | None = None,
    ) -> int:
        """Persist one predicted-vs-actual datapoint.

        Returns the new row id.
        """
        ts = recorded_at if recorded_at is not None else time.time()
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO predicted_vs_actual("
                "attempt_id, surface, strategy, predicted_effectiveness, "
                "actual_delta, recorded_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    attempt_id,
                    surface,
                    strategy,
                    predicted_effectiveness,
                    actual_delta,
                    ts,
                ),
            )
            conn.commit()
            row_id = cur.lastrowid
        assert row_id is not None  # sqlite3 always returns lastrowid on INSERT
        return int(row_id)

    def factor(
        self,
        *,
        surface: str,
        strategy: str,
        n: int = 20,
    ) -> float | None:
        """Calibration factor for ``(surface, strategy)``.

        Computes ``mean(actual_delta - predicted_effectiveness)`` over the
        most recent ``n`` rows, ordered by ``recorded_at`` descending.
        Returns ``None`` when fewer than ``n`` rows exist for the key —
        never ``0.0`` — so callers can detect insufficient history.
        """
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "SELECT actual_delta - predicted_effectiveness "
                "FROM predicted_vs_actual "
                "WHERE surface = ? AND strategy = ? "
                "ORDER BY recorded_at DESC "
                "LIMIT ?",
                (surface, strategy, n),
            )
            diffs = [row[0] for row in cur.fetchall()]

        if len(diffs) < n:
            return None
        return sum(diffs) / len(diffs)
