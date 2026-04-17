"""Canary scoring primitives: paired (baseline, candidate) observations.

Provides the deployment-platform-agnostic interface used to record
``(baseline_output, candidate_output)`` pairs on the SAME input during
a canary rollout, plus a SQLite-backed reference implementation.

The ``CanaryRouter`` Protocol is the seam: a Kubernetes, Cloud Run, or
Lambda adapter can implement it without depending on this module's
storage. ``LocalCanaryRouter`` is the local-mode reference impl and the
fixture used by tests and B.5's scoring aggregator.

This module stands alone: stdlib + ``typing`` + ``dataclasses`` only.
B.5's aggregator imports from here, not the other way around.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


DEFAULT_DB_PATH = ".agentlab/canary_pairs.db"


@dataclass(frozen=True)
class CanaryPair:
    """One paired observation: baseline + candidate ran on the same input."""

    pair_id: str
    input_id: str
    baseline_label: str
    candidate_label: str
    baseline_output: str
    candidate_output: str
    metadata: dict[str, Any] = field(default_factory=dict)
    recorded_at: float = 0.0


@runtime_checkable
class CanaryRouter(Protocol):
    """Deploy-platform-specific adapter for paired canary observations.

    Implementations record one ``(baseline_output, candidate_output)`` pair
    per call, keyed by a logical ``input_id`` so the scoring aggregator can
    match them up later.
    """

    def record_pair(
        self,
        *,
        input_id: str,
        baseline_label: str,
        candidate_label: str,
        baseline_output: str,
        candidate_output: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Store one pair; return the ``pair_id``."""
        ...


class LocalCanaryRouter:
    """SQLite-backed :class:`CanaryRouter`.

    Reference implementation suitable for tests and local-mode canary
    deploys. Persists every pair so B.5's aggregator can read deterministic
    history without coupling to any specific deployment platform.
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS canary_pairs (
                    pair_id TEXT PRIMARY KEY,
                    input_id TEXT NOT NULL,
                    baseline_label TEXT NOT NULL,
                    candidate_label TEXT NOT NULL,
                    baseline_output TEXT NOT NULL,
                    candidate_output TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    recorded_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_cp_labels_recorded "
                "ON canary_pairs(baseline_label, candidate_label, recorded_at)"
            )
            conn.commit()

    def record_pair(
        self,
        *,
        input_id: str,
        baseline_label: str,
        candidate_label: str,
        baseline_output: str,
        candidate_output: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Persist one paired observation; return the new ``pair_id``."""
        pair_id = uuid.uuid4().hex
        metadata_json = json.dumps(metadata or {}, default=str, sort_keys=True)
        recorded_at = time.time()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO canary_pairs("
                "pair_id, input_id, baseline_label, candidate_label, "
                "baseline_output, candidate_output, metadata_json, "
                "recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    pair_id,
                    input_id,
                    baseline_label,
                    candidate_label,
                    baseline_output,
                    candidate_output,
                    metadata_json,
                    recorded_at,
                ),
            )
            conn.commit()
        return pair_id

    def list_recent(
        self,
        *,
        baseline_label: str,
        candidate_label: str,
        window_s: float | None = None,
        limit: int = 1000,
    ) -> list[CanaryPair]:
        """Return recent pairs for ``(baseline_label, candidate_label)``.

        Ordered most-recent first. When ``window_s`` is set, restrict to
        rows with ``recorded_at > time.time() - window_s``.
        """
        params: list[Any] = [baseline_label, candidate_label]
        sql = (
            "SELECT pair_id, input_id, baseline_label, candidate_label, "
            "baseline_output, candidate_output, metadata_json, recorded_at "
            "FROM canary_pairs "
            "WHERE baseline_label = ? AND candidate_label = ?"
        )
        if window_s is not None:
            sql += " AND recorded_at > ?"
            params.append(time.time() - window_s)
        sql += " ORDER BY recorded_at DESC LIMIT ?"
        params.append(limit)

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(sql, params).fetchall()

        return [
            CanaryPair(
                pair_id=row[0],
                input_id=row[1],
                baseline_label=row[2],
                candidate_label=row[3],
                baseline_output=row[4],
                candidate_output=row[5],
                metadata=json.loads(row[6]),
                recorded_at=row[7],
            )
            for row in rows
        ]

    def count(
        self,
        *,
        baseline_label: str,
        candidate_label: str,
        window_s: float | None = None,
    ) -> int:
        """Count pairs for ``(baseline_label, candidate_label)``.

        When ``window_s`` is set, restrict to rows with
        ``recorded_at > time.time() - window_s``.
        """
        params: list[Any] = [baseline_label, candidate_label]
        sql = (
            "SELECT COUNT(*) FROM canary_pairs "
            "WHERE baseline_label = ? AND candidate_label = ?"
        )
        if window_s is not None:
            sql += " AND recorded_at > ?"
            params.append(time.time() - window_s)

        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(sql, params).fetchone()
        return int(row[0])
