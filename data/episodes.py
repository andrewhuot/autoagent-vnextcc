"""SQLite-backed RLDS-inspired episode store for offline RL datasets."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from data.episode_types import Episode, EpisodeStep


class EpisodeStore:
    """Stores episodes and steps in SQLite for offline RL training."""

    def __init__(self, db_path: str = "episodes.db") -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    # ------------------------------------------------------------------
    # Schema bootstrap
    # ------------------------------------------------------------------

    def _create_tables(self) -> None:
        """Create episodes and episode_steps tables plus indexes if they don't exist."""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS episodes (
                episode_id        TEXT    NOT NULL PRIMARY KEY,
                trace_id          TEXT    NOT NULL DEFAULT '',
                eval_run_id       TEXT    NOT NULL DEFAULT '',
                experiment_id     TEXT    NOT NULL DEFAULT '',
                agent_version     TEXT    NOT NULL DEFAULT '',
                adk_project       TEXT    NOT NULL DEFAULT '',
                hard_gates_passed INTEGER NOT NULL DEFAULT 1,
                created_at        TEXT    NOT NULL,
                data              TEXT    NOT NULL
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS episode_steps (
                step_id    TEXT    NOT NULL PRIMARY KEY,
                episode_id TEXT    NOT NULL REFERENCES episodes(episode_id) ON DELETE CASCADE,
                step_index INTEGER NOT NULL,
                action_type TEXT   NOT NULL DEFAULT '',
                timestamp  TEXT    NOT NULL,
                data       TEXT    NOT NULL
            )
        """)

        # Indexes for common filter patterns
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_episodes_trace_id      ON episodes (trace_id)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_episodes_eval_run_id   ON episodes (eval_run_id)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_episodes_experiment_id ON episodes (experiment_id)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_episodes_agent_version ON episodes (agent_version)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_episode_steps_episode_id ON episode_steps (episode_id)"
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def store_episode(self, episode: Episode) -> str:
        """Store a complete episode and all its steps. Returns episode_id."""
        data_json = json.dumps(episode.to_dict(), sort_keys=True)
        self._conn.execute(
            """
            INSERT OR REPLACE INTO episodes
                (episode_id, trace_id, eval_run_id, experiment_id,
                 agent_version, adk_project, hard_gates_passed, created_at, data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                episode.episode_id,
                episode.trace_id,
                episode.eval_run_id,
                episode.experiment_id,
                episode.agent_version,
                episode.adk_project,
                int(episode.hard_gates_passed),
                episode.created_at,
                data_json,
            ),
        )

        # Remove stale steps when replacing an existing episode
        self._conn.execute(
            "DELETE FROM episode_steps WHERE episode_id = ?",
            (episode.episode_id,),
        )

        for step in episode.steps:
            self._conn.execute(
                """
                INSERT INTO episode_steps
                    (step_id, episode_id, step_index, action_type, timestamp, data)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    step.step_id,
                    episode.episode_id,
                    step.step_index,
                    step.action_type,
                    step.timestamp,
                    json.dumps(step.to_dict(), sort_keys=True),
                ),
            )

        self._conn.commit()
        return episode.episode_id

    def delete_episode(self, episode_id: str) -> bool:
        """Delete an episode and its steps. Returns True if a row was removed."""
        # Steps are removed via ON DELETE CASCADE
        cursor = self._conn.execute(
            "DELETE FROM episodes WHERE episode_id = ?",
            (episode_id,),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_episode(self, episode_id: str) -> Episode | None:
        """Get episode by ID. Returns None when not found."""
        row = self._conn.execute(
            "SELECT data FROM episodes WHERE episode_id = ?",
            (episode_id,),
        ).fetchone()
        if row is None:
            return None
        return Episode.from_dict(json.loads(row["data"]))

    def list_episodes(
        self,
        trace_id: str | None = None,
        eval_run_id: str | None = None,
        experiment_id: str | None = None,
        agent_version: str | None = None,
        hard_gates_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Episode]:
        """List episodes with optional filters and pagination."""
        conditions: list[str] = []
        params: list[Any] = []

        if trace_id is not None:
            conditions.append("trace_id = ?")
            params.append(trace_id)
        if eval_run_id is not None:
            conditions.append("eval_run_id = ?")
            params.append(eval_run_id)
        if experiment_id is not None:
            conditions.append("experiment_id = ?")
            params.append(experiment_id)
        if agent_version is not None:
            conditions.append("agent_version = ?")
            params.append(agent_version)
        if hard_gates_only:
            conditions.append("hard_gates_passed = 1")

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.extend([limit, offset])

        rows = self._conn.execute(
            f"SELECT data FROM episodes {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params,
        ).fetchall()

        return [Episode.from_dict(json.loads(row["data"])) for row in rows]

    def get_episodes_for_trace(self, trace_id: str) -> list[Episode]:
        """Get all episodes linked to a trace, ordered by creation time."""
        rows = self._conn.execute(
            "SELECT data FROM episodes WHERE trace_id = ? ORDER BY created_at ASC",
            (trace_id,),
        ).fetchall()
        return [Episode.from_dict(json.loads(row["data"])) for row in rows]

    def count_episodes(self, **filters: Any) -> int:
        """Count episodes matching keyword filters.

        Accepted keywords mirror list_episodes():
            trace_id, eval_run_id, experiment_id, agent_version, hard_gates_only.
        Unknown keywords are silently ignored.
        """
        conditions: list[str] = []
        params: list[Any] = []

        if filters.get("trace_id") is not None:
            conditions.append("trace_id = ?")
            params.append(filters["trace_id"])
        if filters.get("eval_run_id") is not None:
            conditions.append("eval_run_id = ?")
            params.append(filters["eval_run_id"])
        if filters.get("experiment_id") is not None:
            conditions.append("experiment_id = ?")
            params.append(filters["experiment_id"])
        if filters.get("agent_version") is not None:
            conditions.append("agent_version = ?")
            params.append(filters["agent_version"])
        if filters.get("hard_gates_only"):
            conditions.append("hard_gates_passed = 1")

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        row = self._conn.execute(
            f"SELECT COUNT(*) AS cnt FROM episodes {where}",
            params,
        ).fetchone()
        return int(row["cnt"])

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_jsonl(
        self,
        episode_ids: list[str] | None = None,
        output_path: str | None = None,
    ) -> str:
        """Export episodes to a JSONL file. Returns the output path.

        When episode_ids is None all stored episodes are exported.
        When output_path is None a timestamped file is written under .autoagent/.
        """
        os.makedirs(".autoagent", exist_ok=True)
        if output_path is None:
            output_path = f".autoagent/episodes_{uuid.uuid4().hex[:8]}.jsonl"

        if episode_ids is not None:
            placeholders = ", ".join("?" for _ in episode_ids)
            rows = self._conn.execute(
                f"SELECT data FROM episodes WHERE episode_id IN ({placeholders})"
                f" ORDER BY created_at ASC",
                episode_ids,
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT data FROM episodes ORDER BY created_at ASC"
            ).fetchall()

        with open(output_path, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(row["data"])
                fh.write("\n")

        return output_path

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
