"""SQLite-backed reward definition registry."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from rewards.types import RewardDefinition


class RewardRegistry:
    """Versioned CRUD for reward definitions."""

    def __init__(self, db_path: str = "rewards.db") -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS rewards (
                name       TEXT    NOT NULL,
                version    INTEGER NOT NULL,
                data       TEXT    NOT NULL,
                created_at TEXT    NOT NULL,
                deprecated INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (name, version)
            )
        """)
        self._conn.commit()

    def register(self, definition: RewardDefinition) -> tuple[str, int]:
        """Register a new reward definition. Returns (name, version)."""
        # Get latest version for this name, increment
        row = self._conn.execute(
            "SELECT MAX(version) as max_v FROM rewards WHERE name = ?",
            (definition.name,),
        ).fetchone()
        new_version = (row["max_v"] or 0) + 1
        definition.version = new_version

        self._conn.execute(
            "INSERT INTO rewards (name, version, data, created_at) VALUES (?, ?, ?, ?)",
            (definition.name, new_version, json.dumps(definition.to_dict(), sort_keys=True), definition.created_at),
        )
        self._conn.commit()
        return (definition.name, new_version)

    def get(self, name: str, version: int | None = None) -> RewardDefinition | None:
        """Get reward by name. None version = latest."""
        if version is None:
            row = self._conn.execute(
                "SELECT * FROM rewards WHERE name = ? AND deprecated = 0 ORDER BY version DESC LIMIT 1",
                (name,),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT * FROM rewards WHERE name = ? AND version = ?",
                (name, version),
            ).fetchone()
        if row is None:
            return None
        return RewardDefinition.from_dict(json.loads(row["data"]))

    def list_all(self) -> list[RewardDefinition]:
        """List all non-deprecated rewards (latest versions)."""
        # Get latest version per name
        rows = self._conn.execute(
            "SELECT r.* FROM rewards r INNER JOIN "
            "(SELECT name, MAX(version) as max_v FROM rewards WHERE deprecated = 0 GROUP BY name) latest "
            "ON r.name = latest.name AND r.version = latest.max_v "
            "ORDER BY r.name"
        ).fetchall()
        return [RewardDefinition.from_dict(json.loads(r["data"])) for r in rows]

    def list_by_kind(self, kind: str) -> list[RewardDefinition]:
        """List rewards filtered by kind."""
        all_rewards = self.list_all()
        return [r for r in all_rewards if r.kind.value == kind]

    def list_hard_gates(self) -> list[RewardDefinition]:
        """List all rewards that are hard gates."""
        all_rewards = self.list_all()
        return [r for r in all_rewards if r.hard_gate]

    def deprecate(self, name: str, version: int) -> bool:
        """Mark a specific version as deprecated."""
        cursor = self._conn.execute(
            "UPDATE rewards SET deprecated = 1 WHERE name = ? AND version = ?",
            (name, version),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def search(self, query: str) -> list[RewardDefinition]:
        """Search by substring in name or data."""
        pattern = f"%{query}%"
        rows = self._conn.execute(
            "SELECT * FROM rewards WHERE (name LIKE ? OR data LIKE ?) AND deprecated = 0 ORDER BY name, version",
            (pattern, pattern),
        ).fetchall()
        return [RewardDefinition.from_dict(json.loads(r["data"])) for r in rows]

    def close(self) -> None:
        self._conn.close()
