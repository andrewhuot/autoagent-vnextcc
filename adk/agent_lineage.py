"""Agent Lineage Tracker — SQLite-backed history and tree reconstruction."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class LineageNode:
    """A single node in an agent's lineage graph."""

    agent_id: str
    version: str
    parent_id: Optional[str]
    experiment_id: Optional[str]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "version": self.version,
            "parent_id": self.parent_id,
            "experiment_id": self.experiment_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LineageNode":
        return cls(
            agent_id=data["agent_id"],
            version=data["version"],
            parent_id=data.get("parent_id"),
            experiment_id=data.get("experiment_id"),
            created_at=data["created_at"],
        )


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------

class AgentLineageTracker:
    """Persist and query agent lineage nodes using SQLite."""

    def __init__(self, db_path: str = ".autoagent/agent_lineage.db") -> None:
        self.db_path = db_path
        self._init_db()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS lineage (
                    agent_id      TEXT NOT NULL,
                    version       TEXT NOT NULL,
                    parent_id     TEXT,
                    experiment_id TEXT,
                    created_at    TEXT NOT NULL,
                    PRIMARY KEY (agent_id, version)
                )
                """
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record(self, node: LineageNode) -> None:
        """Insert or replace a lineage node."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO lineage
                    (agent_id, version, parent_id, experiment_id, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    node.agent_id,
                    node.version,
                    node.parent_id,
                    node.experiment_id,
                    node.created_at,
                ),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_history(self, agent_id: str) -> list[LineageNode]:
        """Return all lineage nodes for *agent_id* ordered by creation time."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT agent_id, version, parent_id, experiment_id, created_at "
                "FROM lineage WHERE agent_id = ? ORDER BY created_at ASC",
                (agent_id,),
            ).fetchall()
        return [self._row_to_node(r) for r in rows]

    def get_tree(self, root_id: str) -> dict[str, Any]:
        """Return the full descendant tree rooted at *root_id*.

        The returned dict has the shape:
        ``{"node": LineageNode.to_dict(), "children": [<tree>, ...]}``.
        """
        # Fetch all nodes in one query and build in-memory
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT agent_id, version, parent_id, experiment_id, created_at "
                "FROM lineage"
            ).fetchall()

        nodes = [self._row_to_node(r) for r in rows]
        by_id: dict[str, LineageNode] = {n.agent_id: n for n in nodes}
        children_map: dict[str, list[str]] = {}
        for node in nodes:
            if node.parent_id:
                children_map.setdefault(node.parent_id, []).append(node.agent_id)

        def _build(node_id: str) -> dict[str, Any]:
            node = by_id.get(node_id)
            if node is None:
                return {}
            return {
                "node": node.to_dict(),
                "children": [_build(child_id) for child_id in children_map.get(node_id, [])],
            }

        return _build(root_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_node(row: tuple) -> LineageNode:
        agent_id, version, parent_id, experiment_id, created_at = row
        return LineageNode(
            agent_id=agent_id,
            version=version,
            parent_id=parent_id,
            experiment_id=experiment_id,
            created_at=created_at,
        )
