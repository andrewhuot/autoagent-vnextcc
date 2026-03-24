"""SQLite-backed experiment card storage for optimization experiments."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field


@dataclass
class ExperimentCard:
    """Full record of a single optimization experiment, from hypothesis through result."""

    experiment_id: str
    created_at: float
    hypothesis: str
    touched_surfaces: list[str]
    touched_agents: list[str]
    diff_summary: str
    eval_set_versions: dict[str, str]
    replay_set_hash: str
    baseline_sha: str
    candidate_sha: str
    risk_class: str
    deployment_policy: str  # "canary", "pr_only", "auto"
    rollback_handle: str
    total_experiment_cost: float
    status: str  # "pending", "running", "accepted", "rejected", "expired"
    result_summary: str
    operator_name: str
    baseline_scores: dict[str, float] = field(default_factory=dict)
    candidate_scores: dict[str, float] = field(default_factory=dict)
    significance_p_value: float = 1.0
    significance_delta: float = 0.0


_VALID_STATUSES = {"pending", "running", "accepted", "rejected", "expired"}


class ExperimentStore:
    """Persistent SQLite store for experiment cards."""

    def __init__(self, db_path: str = "experiments.db") -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Create the experiments table if it doesn't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS experiments (
                    experiment_id TEXT PRIMARY KEY,
                    created_at REAL NOT NULL,
                    hypothesis TEXT NOT NULL,
                    touched_surfaces TEXT NOT NULL DEFAULT '[]',
                    touched_agents TEXT NOT NULL DEFAULT '[]',
                    diff_summary TEXT NOT NULL DEFAULT '',
                    eval_set_versions TEXT NOT NULL DEFAULT '{}',
                    replay_set_hash TEXT NOT NULL DEFAULT '',
                    baseline_sha TEXT NOT NULL DEFAULT '',
                    candidate_sha TEXT NOT NULL DEFAULT '',
                    risk_class TEXT NOT NULL DEFAULT '',
                    deployment_policy TEXT NOT NULL DEFAULT 'pr_only',
                    rollback_handle TEXT NOT NULL DEFAULT '',
                    total_experiment_cost REAL DEFAULT 0.0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    result_summary TEXT NOT NULL DEFAULT '',
                    operator_name TEXT NOT NULL DEFAULT '',
                    baseline_scores TEXT NOT NULL DEFAULT '{}',
                    candidate_scores TEXT NOT NULL DEFAULT '{}',
                    significance_p_value REAL DEFAULT 1.0,
                    significance_delta REAL DEFAULT 0.0
                )
                """
            )
            conn.commit()

    def save(self, card: ExperimentCard) -> None:
        """Insert or replace an experiment card."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO experiments
                    (experiment_id, created_at, hypothesis, touched_surfaces,
                     touched_agents, diff_summary, eval_set_versions, replay_set_hash,
                     baseline_sha, candidate_sha, risk_class, deployment_policy,
                     rollback_handle, total_experiment_cost, status, result_summary,
                     operator_name, baseline_scores, candidate_scores,
                     significance_p_value, significance_delta)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    card.experiment_id,
                    card.created_at,
                    card.hypothesis,
                    json.dumps(card.touched_surfaces),
                    json.dumps(card.touched_agents),
                    card.diff_summary,
                    json.dumps(card.eval_set_versions),
                    card.replay_set_hash,
                    card.baseline_sha,
                    card.candidate_sha,
                    card.risk_class,
                    card.deployment_policy,
                    card.rollback_handle,
                    card.total_experiment_cost,
                    card.status,
                    card.result_summary,
                    card.operator_name,
                    json.dumps(card.baseline_scores),
                    json.dumps(card.candidate_scores),
                    card.significance_p_value,
                    card.significance_delta,
                ),
            )
            conn.commit()

    def get(self, experiment_id: str) -> ExperimentCard | None:
        """Retrieve a single experiment card by ID, or None if not found."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT experiment_id, created_at, hypothesis, touched_surfaces,
                       touched_agents, diff_summary, eval_set_versions, replay_set_hash,
                       baseline_sha, candidate_sha, risk_class, deployment_policy,
                       rollback_handle, total_experiment_cost, status, result_summary,
                       operator_name, baseline_scores, candidate_scores,
                       significance_p_value, significance_delta
                FROM experiments
                WHERE experiment_id = ?
                """,
                (experiment_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_card(row)

    def list_recent(self, limit: int = 50) -> list[ExperimentCard]:
        """Get the most recent experiment cards ordered by created_at descending."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT experiment_id, created_at, hypothesis, touched_surfaces,
                       touched_agents, diff_summary, eval_set_versions, replay_set_hash,
                       baseline_sha, candidate_sha, risk_class, deployment_policy,
                       rollback_handle, total_experiment_cost, status, result_summary,
                       operator_name, baseline_scores, candidate_scores,
                       significance_p_value, significance_delta
                FROM experiments
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [self._row_to_card(row) for row in rows]

    def list_by_status(self, status: str, limit: int = 50) -> list[ExperimentCard]:
        """Get experiment cards filtered by status, ordered by created_at descending."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT experiment_id, created_at, hypothesis, touched_surfaces,
                       touched_agents, diff_summary, eval_set_versions, replay_set_hash,
                       baseline_sha, candidate_sha, risk_class, deployment_policy,
                       rollback_handle, total_experiment_cost, status, result_summary,
                       operator_name, baseline_scores, candidate_scores,
                       significance_p_value, significance_delta
                FROM experiments
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (status, limit),
            ).fetchall()
            return [self._row_to_card(row) for row in rows]

    def update_status(
        self, experiment_id: str, status: str, result_summary: str = ""
    ) -> None:
        """Update the status (and optionally result_summary) of an experiment."""
        if status not in _VALID_STATUSES:
            raise ValueError(
                f"Invalid status '{status}'. Must be one of: {_VALID_STATUSES}"
            )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE experiments
                SET status = ?, result_summary = CASE WHEN ? = '' THEN result_summary ELSE ? END
                WHERE experiment_id = ?
                """,
                (status, result_summary, result_summary, experiment_id),
            )
            conn.commit()

    def get_all(self) -> list[ExperimentCard]:
        """Get all experiment cards ordered by created_at descending."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT experiment_id, created_at, hypothesis, touched_surfaces,
                       touched_agents, diff_summary, eval_set_versions, replay_set_hash,
                       baseline_sha, candidate_sha, risk_class, deployment_policy,
                       rollback_handle, total_experiment_cost, status, result_summary,
                       operator_name, baseline_scores, candidate_scores,
                       significance_p_value, significance_delta
                FROM experiments
                ORDER BY created_at DESC
                """
            ).fetchall()
            return [self._row_to_card(row) for row in rows]

    @staticmethod
    def _row_to_card(row: tuple) -> ExperimentCard:
        """Convert a database row tuple to an ExperimentCard."""
        return ExperimentCard(
            experiment_id=row[0],
            created_at=row[1],
            hypothesis=row[2],
            touched_surfaces=json.loads(row[3]),
            touched_agents=json.loads(row[4]),
            diff_summary=row[5],
            eval_set_versions=json.loads(row[6]),
            replay_set_hash=row[7],
            baseline_sha=row[8],
            candidate_sha=row[9],
            risk_class=row[10],
            deployment_policy=row[11],
            rollback_handle=row[12],
            total_experiment_cost=row[13],
            status=row[14],
            result_summary=row[15],
            operator_name=row[16],
            baseline_scores=json.loads(row[17]),
            candidate_scores=json.loads(row[18]),
            significance_p_value=row[19],
            significance_delta=row[20],
        )
