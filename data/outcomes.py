"""OutcomeStore and OutcomeService — P0-9 Business-Outcome Joins."""

from __future__ import annotations

import csv
import io
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from data.outcome_types import (
    BusinessOutcome,
    JudgeCalibrationSignal,
    OutcomeJoin,
    OutcomeType,
    SkillCalibrationSignal,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# OutcomeStore
# ---------------------------------------------------------------------------

class OutcomeStore:
    """SQLite-backed store for business outcomes and trace join records."""

    def __init__(self, db_path: str = ".autoagent/outcomes.db") -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS outcomes (
                    id           TEXT PRIMARY KEY,
                    trace_id     TEXT NOT NULL DEFAULT '',
                    outcome_type TEXT NOT NULL,
                    outcome_value REAL NOT NULL DEFAULT 0.0,
                    timestamp    TEXT NOT NULL,
                    confidence   REAL NOT NULL DEFAULT 1.0,
                    source       TEXT NOT NULL DEFAULT '',
                    delay_hours  REAL NOT NULL DEFAULT 0.0,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS outcome_joins (
                    join_id     TEXT PRIMARY KEY,
                    trace_id    TEXT NOT NULL,
                    outcome_id  TEXT NOT NULL,
                    joined_at   TEXT NOT NULL,
                    join_method TEXT NOT NULL DEFAULT 'exact_match'
                )
                """
            )
            # Indexes
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_outcomes_trace_id ON outcomes(trace_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_outcomes_type ON outcomes(outcome_type)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_outcomes_ts ON outcomes(timestamp DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_joins_trace_id ON outcome_joins(trace_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_joins_outcome_id ON outcome_joins(outcome_id)"
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    def store_outcome(self, outcome: BusinessOutcome) -> str:
        """Persist a BusinessOutcome and return its outcome_id."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO outcomes
                    (id, trace_id, outcome_type, outcome_value, timestamp,
                     confidence, source, delay_hours, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    outcome.outcome_id,
                    outcome.trace_id,
                    outcome.outcome_type.value,
                    outcome.outcome_value,
                    outcome.timestamp,
                    outcome.confidence,
                    outcome.source,
                    outcome.delay_hours,
                    json.dumps(outcome.metadata, default=str),
                ),
            )
            conn.commit()
        return outcome.outcome_id

    def join_outcome_to_trace(self, trace_id: str, outcome_id: str) -> OutcomeJoin:
        """Create and persist an OutcomeJoin record."""
        join = OutcomeJoin(
            join_id=_new_uuid(),
            trace_id=trace_id,
            outcome_id=outcome_id,
            joined_at=_now_iso(),
            join_method="exact_match",
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO outcome_joins
                    (join_id, trace_id, outcome_id, joined_at, join_method)
                VALUES (?, ?, ?, ?, ?)
                """,
                (join.join_id, join.trace_id, join.outcome_id,
                 join.joined_at, join.join_method),
            )
            conn.commit()
        return join

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def get_outcomes_for_trace(self, trace_id: str) -> list[BusinessOutcome]:
        """Return all outcomes directly linked to *trace_id*."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM outcomes WHERE trace_id = ? ORDER BY timestamp DESC",
                (trace_id,),
            ).fetchall()
        return [self._row_to_outcome(r) for r in rows]

    def get_unjoined_outcomes(self, limit: int = 100) -> list[BusinessOutcome]:
        """Return outcomes that have a non-empty trace_id but no join record yet."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT o.* FROM outcomes o
                LEFT JOIN outcome_joins j ON o.id = j.outcome_id
                WHERE j.outcome_id IS NULL
                  AND o.trace_id != ''
                ORDER BY o.timestamp DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_outcome(r) for r in rows]

    def query_outcomes(
        self,
        outcome_type: OutcomeType | str | None = None,
        since: str | None = None,
        limit: int = 100,
    ) -> list[BusinessOutcome]:
        """Flexible outcome query with optional type and timestamp filters."""
        clauses: list[str] = []
        params: list[Any] = []

        if outcome_type is not None:
            type_val = outcome_type.value if isinstance(outcome_type, OutcomeType) else str(outcome_type)
            clauses.append("outcome_type = ?")
            params.append(type_val)
        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(since)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT * FROM outcomes {where} ORDER BY timestamp DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._row_to_outcome(r) for r in rows]

    def get_judge_calibration_signals(
        self, judge_id: str | None = None
    ) -> list[JudgeCalibrationSignal]:
        """Return judge calibration signals derived from joined outcomes.

        For each outcome join we look for a judge_score stored in the outcome
        metadata (key ``judge_score``) and pair it with the outcome value.
        """
        signals: list[JudgeCalibrationSignal] = []
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT o.id, o.trace_id, o.outcome_value, o.metadata_json
                FROM outcomes o
                INNER JOIN outcome_joins j ON o.id = j.outcome_id
                ORDER BY o.timestamp DESC
                LIMIT 500
                """
            ).fetchall()

        for row in rows:
            meta = json.loads(row[3]) if row[3] else {}
            judge_score_raw = meta.get("judge_score")
            jid = meta.get("judge_id", "default")
            if judge_score_raw is None:
                continue
            if judge_id is not None and jid != judge_id:
                continue
            try:
                judge_score = float(judge_score_raw)
            except (TypeError, ValueError):
                continue
            outcome_value = float(row[2])
            # Drift heuristic: more than 0.2 normalised difference
            drift = abs(judge_score - outcome_value) > 0.2
            signals.append(
                JudgeCalibrationSignal(
                    judge_id=jid,
                    trace_id=row[1],
                    judge_score=judge_score,
                    business_outcome_value=outcome_value,
                    drift_detected=drift,
                )
            )
        return signals

    def get_skill_calibration_signals(
        self, skill_name: str | None = None
    ) -> list[SkillCalibrationSignal]:
        """Return skill calibration signals derived from joined outcomes.

        Looks for ``skill_name``, ``judge_improvement``, and
        ``business_outcome_delta`` keys in outcome metadata.
        """
        signals: list[SkillCalibrationSignal] = []
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT o.metadata_json
                FROM outcomes o
                INNER JOIN outcome_joins j ON o.id = j.outcome_id
                ORDER BY o.timestamp DESC
                LIMIT 500
                """
            ).fetchall()

        for (meta_json,) in rows:
            meta = json.loads(meta_json) if meta_json else {}
            sname = meta.get("skill_name")
            if sname is None:
                continue
            if skill_name is not None and sname != skill_name:
                continue
            try:
                judge_improvement = float(meta.get("judge_improvement", 0.0))
                business_outcome_delta = float(meta.get("business_outcome_delta", 0.0))
            except (TypeError, ValueError):
                continue
            # Misaligned if judge improved but outcome went negative (or vice versa)
            misaligned = (judge_improvement > 0) != (business_outcome_delta >= 0)
            signals.append(
                SkillCalibrationSignal(
                    skill_name=sname,
                    judge_improvement=judge_improvement,
                    business_outcome_delta=business_outcome_delta,
                    misaligned=misaligned,
                )
            )
        return signals

    def compute_outcome_stats(self) -> dict[str, Any]:
        """Aggregate outcome statistics for the dashboard."""
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0]
            joined = conn.execute("SELECT COUNT(DISTINCT outcome_id) FROM outcome_joins").fetchone()[0]
            by_type_rows = conn.execute(
                "SELECT outcome_type, COUNT(*), AVG(outcome_value) FROM outcomes GROUP BY outcome_type"
            ).fetchall()
            latest_ts = conn.execute(
                "SELECT MAX(timestamp) FROM outcomes"
            ).fetchone()[0]

        by_type = {
            row[0]: {"count": row[1], "avg_value": round(row[2], 4) if row[2] else None}
            for row in by_type_rows
        }
        return {
            "total_outcomes": total,
            "joined_outcomes": joined,
            "unjoined_outcomes": total - joined,
            "by_type": by_type,
            "latest_outcome_at": latest_ts,
        }

    # ------------------------------------------------------------------
    # Row converter
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_outcome(row: tuple) -> BusinessOutcome:
        return BusinessOutcome(
            outcome_id=row[0],
            trace_id=row[1],
            outcome_type=OutcomeType(row[2]),
            outcome_value=row[3],
            timestamp=row[4],
            confidence=row[5],
            source=row[6],
            delay_hours=row[7],
            metadata=json.loads(row[8]) if row[8] else {},
        )


# ---------------------------------------------------------------------------
# OutcomeService
# ---------------------------------------------------------------------------

class OutcomeService:
    """High-level service wrapping OutcomeStore with import, join, and calibration logic."""

    def __init__(self, store: OutcomeStore | None = None) -> None:
        self.store = store or OutcomeStore()

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def ingest_outcome(
        self,
        trace_id: str,
        outcome_type: OutcomeType | str,
        value: float,
        source: str = "",
        delay_hours: float = 0.0,
        confidence: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> BusinessOutcome:
        """Create and persist a single BusinessOutcome."""
        if isinstance(outcome_type, str):
            try:
                outcome_type = OutcomeType(outcome_type.upper())
            except ValueError:
                outcome_type = OutcomeType.CUSTOM
        outcome = BusinessOutcome(
            outcome_id=_new_uuid(),
            trace_id=trace_id,
            outcome_type=outcome_type,
            outcome_value=float(value),
            timestamp=_now_iso(),
            confidence=confidence,
            source=source,
            delay_hours=delay_hours,
            metadata=metadata or {},
        )
        self.store.store_outcome(outcome)
        return outcome

    def ingest_batch(self, outcomes: list[dict[str, Any]]) -> int:
        """Ingest a list of outcome dicts. Returns count of successfully stored outcomes."""
        count = 0
        for item in outcomes:
            try:
                outcome = BusinessOutcome.from_dict(item)
                if not outcome.outcome_id:
                    outcome.outcome_id = _new_uuid()
                self.store.store_outcome(outcome)
                count += 1
            except Exception:
                pass  # skip malformed entries
        return count

    # ------------------------------------------------------------------
    # Auto-join
    # ------------------------------------------------------------------

    def auto_join_pending(self) -> int:
        """Join any unjoined outcomes (those with a trace_id) to their traces."""
        pending = self.store.get_unjoined_outcomes(limit=500)
        joined = 0
        for outcome in pending:
            if outcome.trace_id:
                self.store.join_outcome_to_trace(outcome.trace_id, outcome.outcome_id)
                joined += 1
        return joined

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------

    def recalibrate_judges(
        self, judge_id: str | None = None
    ) -> list[JudgeCalibrationSignal]:
        """Compute and return judge calibration signals."""
        return self.store.get_judge_calibration_signals(judge_id=judge_id)

    def recalibrate_skills(
        self, skill_name: str | None = None
    ) -> list[SkillCalibrationSignal]:
        """Compute and return skill calibration signals."""
        return self.store.get_skill_calibration_signals(skill_name=skill_name)

    # ------------------------------------------------------------------
    # Import helpers
    # ------------------------------------------------------------------

    def import_from_webhook(self, payload: dict[str, Any]) -> BusinessOutcome:
        """Parse a webhook payload into a BusinessOutcome and persist it."""
        outcome = BusinessOutcome.from_dict(payload)
        if not outcome.outcome_id:
            outcome.outcome_id = _new_uuid()
        self.store.store_outcome(outcome)
        return outcome

    def import_from_csv(self, csv_path: str) -> int:
        """Import outcomes from a CSV file at *csv_path*. Returns count ingested."""
        from data.outcome_connectors import CsvConnector

        connector = CsvConnector()
        connector.connect({"path": csv_path})
        outcomes = connector.fetch_outcomes()
        count = 0
        for outcome in outcomes:
            self.store.store_outcome(outcome)
            count += 1
        connector.close()
        return count

    def import_from_csv_string(self, csv_content: str) -> int:
        """Import outcomes from a CSV string. Returns count ingested."""
        from data.outcome_connectors import CsvConnector

        connector = CsvConnector()
        outcomes = connector.fetch_from_string(csv_content)
        count = 0
        for outcome in outcomes:
            self.store.store_outcome(outcome)
            count += 1
        return count

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    def dashboard_data(self) -> dict[str, Any]:
        """Return summary statistics suitable for the web console dashboard."""
        stats = self.store.compute_outcome_stats()
        judge_signals = self.store.get_judge_calibration_signals()
        skill_signals = self.store.get_skill_calibration_signals()

        drifted_judges = [s for s in judge_signals if s.drift_detected]
        misaligned_skills = [s for s in skill_signals if s.misaligned]

        return {
            **stats,
            "judge_calibration": {
                "total_signals": len(judge_signals),
                "drifted_judges": len(drifted_judges),
                "drift_rate": (
                    round(len(drifted_judges) / len(judge_signals), 4)
                    if judge_signals else 0.0
                ),
            },
            "skill_calibration": {
                "total_signals": len(skill_signals),
                "misaligned_skills": len(misaligned_skills),
                "misalignment_rate": (
                    round(len(misaligned_skills) / len(skill_signals), 4)
                    if skill_signals else 0.0
                ),
            },
        }
