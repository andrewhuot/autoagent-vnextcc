"""SQLite-backed registry for policy artifacts and training jobs."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from policy_opt.types import PolicyArtifact, TrainingJob, TrainingStatus


class PolicyArtifactRegistry:
    """Versioned CRUD for learned policy artifacts and training jobs."""

    def __init__(self, db_path: str = "policy_opt.db") -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    # ------------------------------------------------------------------
    # Schema bootstrap
    # ------------------------------------------------------------------

    def _create_tables(self) -> None:
        """Create all registry tables if they don't exist."""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS policy_artifacts (
                name        TEXT    NOT NULL,
                version     INTEGER NOT NULL,
                policy_id   TEXT    NOT NULL UNIQUE,
                data        TEXT    NOT NULL,
                status      TEXT    NOT NULL DEFAULT 'candidate',
                created_at  TEXT    NOT NULL,
                deprecated  INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (name, version)
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_policy_artifacts_policy_id
                ON policy_artifacts (policy_id)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_policy_artifacts_status
                ON policy_artifacts (status)
        """)

        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS training_jobs (
                job_id       TEXT    NOT NULL PRIMARY KEY,
                data         TEXT    NOT NULL,
                status       TEXT    NOT NULL DEFAULT 'pending',
                created_at   TEXT    NOT NULL,
                completed_at TEXT    NOT NULL DEFAULT ''
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_training_jobs_status
                ON training_jobs (status)
        """)

        self._conn.commit()

    # ------------------------------------------------------------------
    # Policy Artifact CRUD
    # ------------------------------------------------------------------

    def register(self, artifact: PolicyArtifact) -> tuple[str, int]:
        """Register a new policy artifact. Returns (name, version).

        The version on the artifact is ignored; the registry auto-increments
        the version for the given name so the caller never needs to manage it.
        """
        next_version = self._get_latest_version(artifact.name) + 1
        artifact.version = next_version

        data = artifact.to_dict()
        self._conn.execute(
            """
            INSERT INTO policy_artifacts (name, version, policy_id, data, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                artifact.name,
                next_version,
                artifact.policy_id,
                json.dumps(data, sort_keys=True),
                artifact.status,
                artifact.created_at,
            ),
        )
        self._conn.commit()
        return artifact.name, next_version

    def _get_latest_version(self, name: str) -> int:
        """Return the latest version number for a name, or 0 if none exist."""
        row = self._conn.execute(
            "SELECT MAX(version) AS max_v FROM policy_artifacts WHERE name = ?",
            (name,),
        ).fetchone()
        val = row["max_v"] if row else None
        return val if val is not None else 0

    def get(self, name: str, version: int | None = None) -> PolicyArtifact | None:
        """Get policy by name, optionally specific version. None = latest."""
        if version is None:
            row = self._conn.execute(
                """
                SELECT data FROM policy_artifacts
                WHERE name = ? AND deprecated = 0
                ORDER BY version DESC
                LIMIT 1
                """,
                (name,),
            ).fetchone()
        else:
            row = self._conn.execute(
                """
                SELECT data FROM policy_artifacts
                WHERE name = ? AND version = ?
                """,
                (name, version),
            ).fetchone()

        if row is None:
            return None
        return PolicyArtifact.from_dict(json.loads(row["data"]))

    def get_by_id(self, policy_id: str) -> PolicyArtifact | None:
        """Get policy by its unique policy_id."""
        row = self._conn.execute(
            "SELECT data FROM policy_artifacts WHERE policy_id = ?",
            (policy_id,),
        ).fetchone()
        if row is None:
            return None
        return PolicyArtifact.from_dict(json.loads(row["data"]))

    def list_all(self) -> list[PolicyArtifact]:
        """List all non-deprecated policies (latest version per name)."""
        rows = self._conn.execute(
            """
            SELECT pa.data
            FROM policy_artifacts pa
            INNER JOIN (
                SELECT name, MAX(version) AS max_v
                FROM policy_artifacts
                WHERE deprecated = 0
                GROUP BY name
            ) latest ON pa.name = latest.name AND pa.version = latest.max_v
            WHERE pa.deprecated = 0
            ORDER BY pa.name
            """
        ).fetchall()
        return [PolicyArtifact.from_dict(json.loads(r["data"])) for r in rows]

    def list_by_type(self, policy_type: str) -> list[PolicyArtifact]:
        """Filter by policy type (latest non-deprecated version per name)."""
        rows = self._conn.execute(
            """
            SELECT pa.data
            FROM policy_artifacts pa
            INNER JOIN (
                SELECT name, MAX(version) AS max_v
                FROM policy_artifacts
                WHERE deprecated = 0
                GROUP BY name
            ) latest ON pa.name = latest.name AND pa.version = latest.max_v
            WHERE pa.deprecated = 0
              AND json_extract(pa.data, '$.policy_type') = ?
            ORDER BY pa.name
            """,
            (policy_type,),
        ).fetchall()
        return [PolicyArtifact.from_dict(json.loads(r["data"])) for r in rows]

    def list_by_status(self, status: str) -> list[PolicyArtifact]:
        """Filter by status (candidate, canary, promoted, rolled_back)."""
        rows = self._conn.execute(
            """
            SELECT data FROM policy_artifacts
            WHERE status = ? AND deprecated = 0
            ORDER BY name, version
            """,
            (status,),
        ).fetchall()
        return [PolicyArtifact.from_dict(json.loads(r["data"])) for r in rows]

    def update_status(self, policy_id: str, status: str) -> bool:
        """Update status of a policy artifact. Returns True if a row was updated."""
        # Keep the JSON blob's status field in sync as well.
        row = self._conn.execute(
            "SELECT data FROM policy_artifacts WHERE policy_id = ?",
            (policy_id,),
        ).fetchone()
        if row is None:
            return False

        data = json.loads(row["data"])
        data["status"] = status

        cursor = self._conn.execute(
            """
            UPDATE policy_artifacts
               SET status = ?, data = ?
             WHERE policy_id = ?
            """,
            (status, json.dumps(data, sort_keys=True), policy_id),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def get_active_policy(self, policy_type: str) -> PolicyArtifact | None:
        """Get the currently promoted policy for a given type."""
        row = self._conn.execute(
            """
            SELECT data FROM policy_artifacts
            WHERE status = 'promoted'
              AND deprecated = 0
              AND json_extract(data, '$.policy_type') = ?
            ORDER BY version DESC
            LIMIT 1
            """,
            (policy_type,),
        ).fetchone()
        if row is None:
            return None
        return PolicyArtifact.from_dict(json.loads(row["data"]))

    def deprecate(self, name: str, version: int) -> bool:
        """Mark a specific version as deprecated. Returns True if a row was updated."""
        cursor = self._conn.execute(
            "UPDATE policy_artifacts SET deprecated = 1 WHERE name = ? AND version = ?",
            (name, version),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Training Job CRUD
    # ------------------------------------------------------------------

    def create_job(self, job: TrainingJob) -> str:
        """Create a new training job record. Returns job_id."""
        self._conn.execute(
            """
            INSERT INTO training_jobs (job_id, data, status, created_at, completed_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                job.job_id,
                json.dumps(job.to_dict(), sort_keys=True),
                job.status.value,
                job.created_at,
                job.completed_at,
            ),
        )
        self._conn.commit()
        return job.job_id

    def get_job(self, job_id: str) -> TrainingJob | None:
        """Get training job by ID."""
        row = self._conn.execute(
            "SELECT data FROM training_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        if row is None:
            return None
        return TrainingJob.from_dict(json.loads(row["data"]))

    def list_jobs(self, status: str | None = None, limit: int = 50) -> list[TrainingJob]:
        """List training jobs, optionally filtered by status."""
        if status is not None:
            rows = self._conn.execute(
                """
                SELECT data FROM training_jobs
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (status, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT data FROM training_jobs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [TrainingJob.from_dict(json.loads(r["data"])) for r in rows]

    def update_job_status(
        self,
        job_id: str,
        status: str,
        result: dict[str, Any] | None = None,
        error: str = "",
    ) -> bool:
        """Update job status and optionally set result or error.

        Returns True if a row was updated.
        """
        row = self._conn.execute(
            "SELECT data FROM training_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        if row is None:
            return False

        data = json.loads(row["data"])
        data["status"] = status

        if result is not None:
            data["result"] = result

        if error:
            data["error_message"] = error

        completed_at = ""
        terminal = {TrainingStatus.completed.value, TrainingStatus.failed.value, TrainingStatus.cancelled.value}
        if status in terminal:
            completed_at = datetime.now(timezone.utc).isoformat()
            data["completed_at"] = completed_at

        cursor = self._conn.execute(
            """
            UPDATE training_jobs
               SET status = ?, data = ?, completed_at = ?
             WHERE job_id = ?
            """,
            (status, json.dumps(data, sort_keys=True), completed_at, job_id),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
