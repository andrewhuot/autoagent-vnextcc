"""Persistent archive of evaluated architecture candidates (SQLite-backed)."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from optimizer.adas import ArchitectureCandidate


class ArchitectureArchive:
    """Store and retrieve architecture candidates with similarity search."""

    def __init__(self, db_path: str = ".autoagent/arch_archive.db") -> None:
        self.db_path = db_path
        self._init_db()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS candidates (
                    arch_id       TEXT PRIMARY KEY,
                    topology      TEXT NOT NULL,
                    agent_count   INTEGER NOT NULL,
                    agent_types   TEXT NOT NULL,
                    tree_depth    INTEGER NOT NULL,
                    fan_out       INTEGER NOT NULL,
                    performance_score REAL DEFAULT 0.0,
                    metadata      TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def store(self, candidate: ArchitectureCandidate) -> str:
        """Persist *candidate* and return its arch_id."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO candidates
                    (arch_id, topology, agent_count, agent_types,
                     tree_depth, fan_out, performance_score, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.arch_id,
                    json.dumps(candidate.topology),
                    candidate.agent_count,
                    json.dumps(candidate.agent_types),
                    candidate.tree_depth,
                    candidate.fan_out,
                    candidate.performance_score,
                    json.dumps(candidate.metadata),
                ),
            )
            conn.commit()
        return candidate.arch_id

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_best(self, n: int = 5) -> list[ArchitectureCandidate]:
        """Return the *n* highest-scoring candidates."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM candidates ORDER BY performance_score DESC LIMIT ?",
                (n,),
            ).fetchall()
        return [self._row_to_candidate(r) for r in rows]

    def search_similar(self, topology: dict[str, Any]) -> list[ArchitectureCandidate]:
        """Return candidates whose agent_count is within ±2 of *topology*."""
        agent_count = len(topology.get("agent_types", {}))
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM candidates
                WHERE ABS(agent_count - ?) <= 2
                ORDER BY performance_score DESC
                """,
                (agent_count,),
            ).fetchall()
        return [self._row_to_candidate(r) for r in rows]

    def get_cross_domain_transfers(self) -> list[dict[str, Any]]:
        """Return candidate pairs that share topology shape but differ in type mix."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT a.arch_id AS src, b.arch_id AS dst,
                       a.tree_depth, a.fan_out,
                       a.agent_types AS src_types,
                       b.agent_types AS dst_types,
                       a.performance_score AS src_score,
                       b.performance_score AS dst_score
                FROM candidates a
                JOIN candidates b
                  ON  a.tree_depth = b.tree_depth
                  AND a.fan_out = b.fan_out
                  AND a.arch_id != b.arch_id
                  AND a.agent_types != b.agent_types
                ORDER BY (a.performance_score + b.performance_score) DESC
                LIMIT 50
                """
            ).fetchall()
        result = []
        for row in rows:
            result.append(
                {
                    "source_arch_id": row[0],
                    "target_arch_id": row[1],
                    "tree_depth": row[2],
                    "fan_out": row[3],
                    "source_agent_types": json.loads(row[4]),
                    "target_agent_types": json.loads(row[5]),
                    "source_score": row[6],
                    "target_score": row[7],
                }
            )
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_candidate(row: tuple) -> ArchitectureCandidate:
        arch_id, topology, agent_count, agent_types, tree_depth, fan_out, score, meta = row
        return ArchitectureCandidate(
            arch_id=arch_id,
            topology=json.loads(topology),
            agent_count=agent_count,
            agent_types=json.loads(agent_types),
            tree_depth=tree_depth,
            fan_out=fan_out,
            performance_score=score,
            metadata=json.loads(meta),
        )
