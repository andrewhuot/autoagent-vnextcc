"""Unified SQLite-backed skill store for both build-time and run-time skills.

This is the single source of truth for all skills in AutoAgent, providing:
- CRUD operations with versioning support
- Thread-safe concurrent access
- Full-text search across skill metadata
- Advanced filtering by kind, domain, tags, status
- Dependency tracking and resolution
- Effectiveness tracking and analytics
- Recommendation engine based on failure patterns and metrics
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from core.skills.types import (
    EffectivenessMetrics,
    Skill,
    SkillKind,
)


_DDL = """
-- Core executable skills table: all skill data stored as JSON blob with indexed metadata
CREATE TABLE IF NOT EXISTS executable_skills (
    id          TEXT    PRIMARY KEY,
    name        TEXT    NOT NULL,
    kind        TEXT    NOT NULL,
    version     TEXT    NOT NULL,
    data        TEXT    NOT NULL,
    domain      TEXT    NOT NULL DEFAULT 'general',
    status      TEXT    NOT NULL DEFAULT 'active',
    created_at  REAL    NOT NULL,
    updated_at  REAL    NOT NULL,
    UNIQUE(name, version)
);

-- Track outcomes for effectiveness metrics
CREATE TABLE IF NOT EXISTS skill_outcomes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id    TEXT    NOT NULL,
    improvement REAL    NOT NULL,
    success     INTEGER NOT NULL,
    recorded_at REAL    NOT NULL,
    FOREIGN KEY (skill_id) REFERENCES executable_skills(id) ON DELETE CASCADE
);

-- Indexes for fast lookups
CREATE INDEX IF NOT EXISTS idx_executable_skills_name_version ON executable_skills(name, version);
CREATE INDEX IF NOT EXISTS idx_executable_skills_kind ON executable_skills(kind);
CREATE INDEX IF NOT EXISTS idx_executable_skills_domain ON executable_skills(domain);
CREATE INDEX IF NOT EXISTS idx_executable_skills_status ON executable_skills(status);
CREATE INDEX IF NOT EXISTS idx_executable_skills_kind_status ON executable_skills(kind, status);
CREATE INDEX IF NOT EXISTS idx_outcomes_skill_id ON skill_outcomes(skill_id);
CREATE INDEX IF NOT EXISTS idx_outcomes_recorded_at ON skill_outcomes(recorded_at DESC);
"""

_OPERATORS: dict[str, Any] = {
    "gt": lambda v, t: v > t,
    "lt": lambda v, t: v < t,
    "gte": lambda v, t: v >= t,
    "lte": lambda v, t: v <= t,
    "eq": lambda v, t: v == t,
}


class SkillStore:
    """Thread-safe SQLite-backed skill persistence with versioning and analytics.

    This store handles both build-time skills (optimization strategies) and
    run-time skills (agent capabilities) in a unified schema.

    Thread Safety:
        All public methods acquire a lock before accessing the database.
        Safe for concurrent use across multiple threads.

    Attributes:
        db_path: Path to the SQLite database file.
    """

    def __init__(self, db_path: str = "skills.db") -> None:
        """Initialize the skill store.

        Args:
            db_path: Path to SQLite database file. Parent directories created if needed.
        """
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        # Thread-safe connection management: one connection per instance
        # SQLite in serialized mode (default) is thread-safe with connection pooling
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_DDL)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def create(self, skill: Skill) -> str:
        """Create a new skill in the store.

        Args:
            skill: The skill to create. If skill.id is empty, a UUID is generated.

        Returns:
            The ID of the created skill.

        Raises:
            sqlite3.IntegrityError: If a skill with the same (name, version) already exists.
        """
        with self._lock:
            if not skill.id:
                skill.id = str(uuid.uuid4())

            skill.created_at = time.time()
            skill.updated_at = skill.created_at

            data_json = json.dumps(skill.to_dict())

            try:
                self._conn.execute(
                    """
                    INSERT INTO executable_skills (id, name, kind, version, data, domain, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        skill.id,
                        skill.name,
                        skill.kind.value,
                        skill.version,
                        data_json,
                        skill.domain,
                        skill.status,
                        skill.created_at,
                        skill.updated_at,
                    ),
                )
                self._conn.commit()
                return skill.id
            except sqlite3.IntegrityError as e:
                # Improve error message for duplicate key
                if "UNIQUE constraint" in str(e):
                    raise ValueError(
                        f"Skill with name='{skill.name}' version='{skill.version}' already exists"
                    ) from e
                raise

    def get(self, skill_id: str) -> Skill | None:
        """Retrieve a skill by ID.

        Args:
            skill_id: The unique skill identifier.

        Returns:
            The skill if found, None otherwise.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT data FROM executable_skills WHERE id = ?",
                (skill_id,),
            ).fetchone()

            if row is None:
                return None

            return Skill.from_dict(json.loads(row["data"]))

    def get_by_name(self, name: str, version: str | None = None) -> Skill | None:
        """Retrieve a skill by name and optionally version.

        Args:
            name: The skill name.
            version: Specific version to retrieve. If None, returns the latest version.

        Returns:
            The skill if found, None otherwise.
        """
        with self._lock:
            if version is None:
                # Get the latest version by updated_at timestamp
                row = self._conn.execute(
                    """
                    SELECT data FROM executable_skills
                    WHERE name = ?
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (name,),
                ).fetchone()
            else:
                row = self._conn.execute(
                    "SELECT data FROM executable_skills WHERE name = ? AND version = ?",
                    (name, version),
                ).fetchone()

            if row is None:
                return None

            return Skill.from_dict(json.loads(row["data"]))

    def update(self, skill: Skill) -> bool:
        """Update an existing skill.

        Args:
            skill: The skill to update. Must have a valid ID.

        Returns:
            True if the skill was updated, False if not found.

        Raises:
            ValueError: If skill.id is empty.
        """
        if not skill.id:
            raise ValueError("Cannot update skill without an ID")

        with self._lock:
            # Verify skill exists
            existing = self._conn.execute(
                "SELECT id FROM executable_skills WHERE id = ?",
                (skill.id,),
            ).fetchone()

            if existing is None:
                return False

            skill.updated_at = time.time()
            data_json = json.dumps(skill.to_dict())

            self._conn.execute(
                """
                UPDATE executable_skills
                SET name = ?, kind = ?, version = ?, data = ?, domain = ?, status = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    skill.name,
                    skill.kind.value,
                    skill.version,
                    data_json,
                    skill.domain,
                    skill.status,
                    skill.updated_at,
                    skill.id,
                ),
            )
            self._conn.commit()
            return True

    def delete(self, skill_id: str) -> bool:
        """Delete a skill by ID.

        This cascades to skill_outcomes due to foreign key constraint.

        Args:
            skill_id: The unique skill identifier.

        Returns:
            True if the skill was deleted, False if not found.
        """
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM executable_skills WHERE id = ?",
                (skill_id,),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Listing and Filtering
    # ------------------------------------------------------------------

    def list(
        self,
        kind: SkillKind | None = None,
        domain: str | None = None,
        tags: list[str] | None = None,
        status: str | None = None,
    ) -> list[Skill]:
        """List skills with optional filters.

        All filters are AND-ed together. Returns skills sorted by updated_at DESC.

        Args:
            kind: Filter by skill kind (build/runtime).
            domain: Filter by domain (e.g., 'customer-support', 'sales').
            tags: Filter by tags. A skill matches if it has ALL specified tags.
            status: Filter by status (e.g., 'active', 'draft', 'deprecated').

        Returns:
            List of matching skills, most recently updated first.
        """
        with self._lock:
            sql = "SELECT data FROM executable_skills WHERE 1=1"
            params: list[Any] = []

            if kind is not None:
                sql += " AND kind = ?"
                params.append(kind.value)

            if domain is not None:
                sql += " AND domain = ?"
                params.append(domain)

            if status is not None:
                sql += " AND status = ?"
                params.append(status)

            sql += " ORDER BY updated_at DESC"

            rows = self._conn.execute(sql, params).fetchall()
            skills: list[Skill] = []

            for row in rows:
                skill = Skill.from_dict(json.loads(row["data"]))

                # Filter by tags if specified
                if tags is not None:
                    if not all(tag in skill.tags for tag in tags):
                        continue

                skills.append(skill)

            return skills

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        kind: SkillKind | None = None,
    ) -> list[Skill]:
        """Search skills by text query.

        Searches across:
        - Skill name
        - Description
        - Capabilities
        - Tags
        - Full JSON blob for advanced matching

        Args:
            query: Search query string. Case-insensitive partial matching.
            kind: Optional filter by skill kind.

        Returns:
            List of matching skills, most recently updated first.
        """
        with self._lock:
            like_query = f"%{query.lower()}%"
            sql = """
                SELECT data FROM executable_skills
                WHERE (
                    LOWER(name) LIKE ?
                    OR LOWER(data) LIKE ?
                )
            """
            params: list[Any] = [like_query, like_query]

            if kind is not None:
                sql += " AND kind = ?"
                params.append(kind.value)

            sql += " ORDER BY updated_at DESC"

            rows = self._conn.execute(sql, params).fetchall()
            return [Skill.from_dict(json.loads(row["data"])) for row in rows]

    # ------------------------------------------------------------------
    # Effectiveness Tracking
    # ------------------------------------------------------------------

    def record_outcome(self, skill_id: str, improvement: float, success: bool) -> None:
        """Record an outcome for effectiveness tracking.

        This updates the skill's effectiveness metrics by aggregating all outcomes.

        Args:
            skill_id: The skill ID or name.
            improvement: The improvement delta (e.g., accuracy increase, latency reduction).
            success: Whether the skill application was successful.

        Raises:
            ValueError: If skill_id does not exist.
        """
        with self._lock:
            # Verify skill exists (try by ID first, then by name)
            skill = self.get(skill_id)
            if skill is None:
                skill = self.get_by_name(skill_id)
            if skill is None:
                raise ValueError(f"Skill with id='{skill_id}' not found")

            # Use the actual ID for recording
            skill_id = skill.id

            # Record outcome
            self._conn.execute(
                """
                INSERT INTO skill_outcomes (skill_id, improvement, success, recorded_at)
                VALUES (?, ?, ?, ?)
                """,
                (skill_id, improvement, int(success), time.time()),
            )
            self._conn.commit()

            # Recalculate effectiveness metrics
            self._update_effectiveness(skill_id)

    def get_effectiveness(self, skill_id: str) -> EffectivenessMetrics:
        """Get effectiveness metrics for a skill.

        Args:
            skill_id: The skill ID.

        Returns:
            Current effectiveness metrics. Returns default (zero) metrics if skill not found.
        """
        with self._lock:
            skill = self.get(skill_id)
            if skill is None:
                return EffectivenessMetrics()

            return skill.effectiveness

    def _update_effectiveness(self, skill_id: str) -> None:
        """Internal method to recalculate effectiveness metrics from outcomes.

        Must be called within a lock context.
        """
        rows = self._conn.execute(
            "SELECT improvement, success, recorded_at FROM skill_outcomes WHERE skill_id = ? ORDER BY recorded_at DESC",
            (skill_id,),
        ).fetchall()

        if not rows:
            return

        times_applied = len(rows)
        success_count = sum(1 for r in rows if r["success"])
        success_rate = success_count / times_applied if times_applied > 0 else 0.0

        improvements = [r["improvement"] for r in rows if r["success"]]
        avg_improvement = sum(improvements) / len(improvements) if improvements else 0.0
        total_improvement = sum(improvements)
        last_applied = rows[0]["recorded_at"]

        # Update skill's effectiveness in JSON blob
        skill = self.get(skill_id)
        if skill is None:
            return

        skill.effectiveness = EffectivenessMetrics(
            times_applied=times_applied,
            success_count=success_count,
            success_rate=success_rate,
            avg_improvement=avg_improvement,
            total_improvement=total_improvement,
            last_applied=last_applied,
        )

        skill.updated_at = time.time()
        data_json = json.dumps(skill.to_dict())

        self._conn.execute(
            "UPDATE executable_skills SET data = ?, updated_at = ? WHERE id = ?",
            (data_json, skill.updated_at, skill.id),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Recommendation Engine
    # ------------------------------------------------------------------

    def recommend(
        self,
        failure_family: str | None = None,
        metrics: dict[str, float] | None = None,
        kind: SkillKind = SkillKind.BUILD,
    ) -> list[Skill]:
        """Recommend skills based on failure patterns and metrics.

        For build-time skills: matches triggers against failure families and metric thresholds.
        For run-time skills: returns skills sorted by effectiveness.

        Args:
            failure_family: The failure family to match (e.g., 'hallucination', 'refusal').
            metrics: Current metrics to check against thresholds (e.g., {'accuracy': 0.75}).
            kind: The kind of skills to recommend.

        Returns:
            List of recommended skills, ranked by effectiveness (success_rate * avg_improvement).
        """
        with self._lock:
            all_skills = self.list(kind=kind, status="active")

            if kind == SkillKind.BUILD:
                matched: list[Skill] = []

                for skill in all_skills:
                    # Check if any trigger matches
                    for trigger in skill.triggers:
                        # Match by failure family
                        if failure_family is not None and trigger.failure_family == failure_family:
                            matched.append(skill)
                            break

                        # Match by metric threshold
                        if (
                            metrics is not None
                            and trigger.metric_name is not None
                            and trigger.threshold is not None
                            and trigger.metric_name in metrics
                        ):
                            op_fn = _OPERATORS.get(trigger.operator)
                            if op_fn is not None and op_fn(metrics[trigger.metric_name], trigger.threshold):
                                matched.append(skill)
                                break

                # Sort by effectiveness: success_rate * avg_improvement
                matched.sort(
                    key=lambda s: s.effectiveness.success_rate * s.effectiveness.avg_improvement,
                    reverse=True,
                )
                return matched

            else:
                # For runtime skills, just return by effectiveness
                all_skills.sort(
                    key=lambda s: s.effectiveness.success_rate * s.effectiveness.avg_improvement,
                    reverse=True,
                )
                return all_skills

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    def get_top_performers(
        self,
        n: int = 10,
        kind: SkillKind | None = None,
    ) -> list[Skill]:
        """Get top-performing skills by effectiveness.

        Args:
            n: Number of top skills to return.
            kind: Optional filter by skill kind.

        Returns:
            List of top N skills ranked by success_rate * avg_improvement.
        """
        with self._lock:
            skills = self.list(kind=kind, status="active")

            # Filter to skills that have been applied at least once
            eligible = [s for s in skills if s.effectiveness.times_applied > 0]

            # Sort by effectiveness score
            eligible.sort(
                key=lambda s: s.effectiveness.success_rate * s.effectiveness.avg_improvement,
                reverse=True,
            )

            return eligible[:n]

    def get_stats(self) -> dict[str, Any]:
        """Get overall store statistics.

        Returns:
            Dictionary with counts, averages, and other aggregate stats.
        """
        with self._lock:
            total_skills = self._conn.execute("SELECT COUNT(*) FROM executable_skills").fetchone()[0]

            build_skills = self._conn.execute(
                "SELECT COUNT(*) FROM executable_skills WHERE kind = ?",
                (SkillKind.BUILD.value,),
            ).fetchone()[0]

            runtime_skills = self._conn.execute(
                "SELECT COUNT(*) FROM executable_skills WHERE kind = ?",
                (SkillKind.RUNTIME.value,),
            ).fetchone()[0]

            active_skills = self._conn.execute(
                "SELECT COUNT(*) FROM executable_skills WHERE status = 'active'",
            ).fetchone()[0]

            total_outcomes = self._conn.execute(
                "SELECT COUNT(*) FROM skill_outcomes",
            ).fetchone()[0]

            return {
                "total_skills": total_skills,
                "build_skills": build_skills,
                "runtime_skills": runtime_skills,
                "active_skills": active_skills,
                "total_outcomes": total_outcomes,
            }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the database connection.

        Call this when shutting down to ensure all data is flushed.
        """
        with self._lock:
            self._conn.close()

    def clear(self) -> None:
        """Delete all skills and outcomes.

        WARNING: This is destructive and irreversible. Use only for testing.
        """
        with self._lock:
            self._conn.execute("DELETE FROM skill_outcomes")
            self._conn.execute("DELETE FROM executable_skills")
            self._conn.commit()
