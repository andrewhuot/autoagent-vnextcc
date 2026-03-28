"""SQLite-backed lineage store for full requirement-to-production traceability.

Each :class:`~deployer.release_objects.ReleaseLineage` record captures the
chain from a business requirement, through the builder skill that implemented
it, the eval results that validated it, and the production traces and outcome
IDs that confirm it delivered value.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from deployer.release_objects import ReleaseLineage


class LineageStore:
    """Persistent SQLite store for :class:`~deployer.release_objects.ReleaseLineage` records.

    Args:
        db_path: Path to the SQLite database file.  Parent directories are
            created automatically if they do not exist.
    """

    def __init__(self, db_path: str = ".autoagent/lineage.db") -> None:
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._ensure_table()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _ensure_table(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS lineage_entries (
                    lineage_id            TEXT PRIMARY KEY,
                    requirement_desc      TEXT NOT NULL DEFAULT '',
                    builder_skill_used    TEXT NOT NULL DEFAULT '',
                    code_change_summary   TEXT NOT NULL DEFAULT '',
                    eval_results_summary  TEXT NOT NULL DEFAULT '{}',
                    deployment_id         TEXT NOT NULL DEFAULT '',
                    production_trace_ids  TEXT NOT NULL DEFAULT '[]',
                    business_outcome_ids  TEXT NOT NULL DEFAULT '[]'
                )
                """
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record_lineage(self, lineage: ReleaseLineage) -> str:
        """Persist *lineage* and return its ``lineage_id``.

        If a record with the same ``lineage_id`` already exists it is
        replaced (upsert semantics).

        Args:
            lineage: The lineage record to store.

        Returns:
            The ``lineage_id`` of the stored record.
        """
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO lineage_entries
                    (lineage_id, requirement_desc, builder_skill_used,
                     code_change_summary, eval_results_summary, deployment_id,
                     production_trace_ids, business_outcome_ids)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lineage.lineage_id,
                    lineage.requirement_description,
                    lineage.builder_skill_used,
                    lineage.code_change_summary,
                    json.dumps(lineage.eval_results_summary, default=str),
                    lineage.deployment_id,
                    json.dumps(lineage.production_trace_ids),
                    json.dumps(lineage.business_outcome_ids),
                ),
            )
            conn.commit()
        return lineage.lineage_id

    # ------------------------------------------------------------------
    # Read — single record
    # ------------------------------------------------------------------

    def get_lineage(self, release_id: str) -> ReleaseLineage | None:
        """Retrieve the lineage record whose ``lineage_id`` matches *release_id*.

        Args:
            release_id: The lineage_id (or deployment_id) to look up.  This
                method first tries an exact ``lineage_id`` match, then falls
                back to a ``deployment_id`` match so callers can use either.

        Returns:
            The matching :class:`~deployer.release_objects.ReleaseLineage`, or
            ``None`` if not found.
        """
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                """
                SELECT lineage_id, requirement_desc, builder_skill_used,
                       code_change_summary, eval_results_summary, deployment_id,
                       production_trace_ids, business_outcome_ids
                FROM lineage_entries
                WHERE lineage_id = ? OR deployment_id = ?
                LIMIT 1
                """,
                (release_id, release_id),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_lineage(row)

    # ------------------------------------------------------------------
    # Read — chain and queries
    # ------------------------------------------------------------------

    def get_chain(self, release_id: str) -> list[ReleaseLineage]:
        """Return all lineage records associated with *release_id*.

        Because a single deployment may have multiple lineage entries (e.g.
        partial re-deployments or layered skills), this method returns every
        record where the ``deployment_id`` matches *release_id*, ordered by
        ``rowid`` (insertion order) so the caller gets a chronological chain
        back to the original requirement.

        Args:
            release_id: The deployment_id shared across the chain.

        Returns:
            List of :class:`~deployer.release_objects.ReleaseLineage` objects,
            earliest first.  Empty list if none found.
        """
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT lineage_id, requirement_desc, builder_skill_used,
                       code_change_summary, eval_results_summary, deployment_id,
                       production_trace_ids, business_outcome_ids
                FROM lineage_entries
                WHERE deployment_id = ?
                ORDER BY rowid ASC
                """,
                (release_id,),
            ).fetchall()
        return [self._row_to_lineage(r) for r in rows]

    def query_by_outcome(self, outcome_id: str) -> list[ReleaseLineage]:
        """Return all lineage records that reference *outcome_id*.

        The ``business_outcome_ids`` column stores a JSON array; this method
        performs a substring search so it works without JSON functions that
        may not be available in older SQLite versions.

        Args:
            outcome_id: The business outcome identifier to search for.

        Returns:
            List of matching :class:`~deployer.release_objects.ReleaseLineage`
            objects.  Empty list if none found.
        """
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT lineage_id, requirement_desc, builder_skill_used,
                       code_change_summary, eval_results_summary, deployment_id,
                       production_trace_ids, business_outcome_ids
                FROM lineage_entries
                WHERE business_outcome_ids LIKE ?
                ORDER BY rowid ASC
                """,
                (f"%{outcome_id}%",),
            ).fetchall()
        # Re-filter in Python to avoid false positives from substring match
        results = []
        for row in rows:
            lineage = self._row_to_lineage(row)
            if outcome_id in lineage.business_outcome_ids:
                results.append(lineage)
        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_lineage(row: tuple) -> ReleaseLineage:
        return ReleaseLineage(
            lineage_id=row[0],
            requirement_description=row[1],
            builder_skill_used=row[2],
            code_change_summary=row[3],
            eval_results_summary=json.loads(row[4]),
            deployment_id=row[5],
            production_trace_ids=json.loads(row[6]),
            business_outcome_ids=json.loads(row[7]),
        )
