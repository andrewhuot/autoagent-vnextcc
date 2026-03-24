"""SQLite-backed persistence for all registry items.

Provides generic versioned CRUD operations used by type-specific registries.
Each item is stored as a JSON blob with composite (name, version) primary key.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any


_TABLES = ("skills", "policies", "tool_contracts", "handoff_schemas")


class RegistryStore:
    """SQLite-backed persistence for all registry items."""

    def __init__(self, db_path: str = "registry.db") -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    # ------------------------------------------------------------------
    # Schema bootstrap
    # ------------------------------------------------------------------

    def _create_tables(self) -> None:
        """Create all registry tables if they don't exist."""
        for table in _TABLES:
            self._conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    name       TEXT    NOT NULL,
                    version    INTEGER NOT NULL,
                    data       TEXT    NOT NULL,
                    created_at TEXT    NOT NULL,
                    deprecated INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (name, version)
                )
            """)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Generic CRUD
    # ------------------------------------------------------------------

    def _insert(
        self,
        table: str,
        name: str,
        version: int,
        data: dict[str, Any],
        created_at: str,
    ) -> None:
        """Insert a new registry item."""
        self._conn.execute(
            f"INSERT INTO {table} (name, version, data, created_at) VALUES (?, ?, ?, ?)",
            (name, version, json.dumps(data, sort_keys=True), created_at),
        )
        self._conn.commit()

    def _get(
        self,
        table: str,
        name: str,
        version: int | None = None,
    ) -> dict[str, Any] | None:
        """Get an item by name and optional version. None version = latest."""
        if version is None:
            row = self._conn.execute(
                f"SELECT * FROM {table} WHERE name = ? ORDER BY version DESC LIMIT 1",
                (name,),
            ).fetchone()
        else:
            row = self._conn.execute(
                f"SELECT * FROM {table} WHERE name = ? AND version = ?",
                (name, version),
            ).fetchone()

        if row is None:
            return None

        return {
            "name": row["name"],
            "version": row["version"],
            "data": json.loads(row["data"]),
            "created_at": row["created_at"],
            "deprecated": bool(row["deprecated"]),
        }

    def _get_latest_version(self, table: str, name: str) -> int:
        """Return the latest version number for a name, or 0 if none exist."""
        row = self._conn.execute(
            f"SELECT MAX(version) as max_v FROM {table} WHERE name = ?",
            (name,),
        ).fetchone()
        val = row["max_v"] if row else None
        return val if val is not None else 0

    def _list(
        self,
        table: str,
        include_deprecated: bool = False,
    ) -> list[dict[str, Any]]:
        """List all items, optionally including deprecated ones."""
        if include_deprecated:
            rows = self._conn.execute(
                f"SELECT * FROM {table} ORDER BY name, version"
            ).fetchall()
        else:
            rows = self._conn.execute(
                f"SELECT * FROM {table} WHERE deprecated = 0 ORDER BY name, version"
            ).fetchall()

        return [
            {
                "name": r["name"],
                "version": r["version"],
                "data": json.loads(r["data"]),
                "created_at": r["created_at"],
                "deprecated": bool(r["deprecated"]),
            }
            for r in rows
        ]

    def _deprecate(self, table: str, name: str, version: int) -> bool:
        """Mark a specific version as deprecated. Returns True if a row was updated."""
        cursor = self._conn.execute(
            f"UPDATE {table} SET deprecated = 1 WHERE name = ? AND version = ?",
            (name, version),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def _search(self, table: str, query: str) -> list[dict[str, Any]]:
        """Search items by substring match in name or JSON data."""
        pattern = f"%{query}%"
        rows = self._conn.execute(
            f"SELECT * FROM {table} WHERE (name LIKE ? OR data LIKE ?) AND deprecated = 0 "
            f"ORDER BY name, version",
            (pattern, pattern),
        ).fetchall()

        return [
            {
                "name": r["name"],
                "version": r["version"],
                "data": json.loads(r["data"]),
                "created_at": r["created_at"],
                "deprecated": bool(r["deprecated"]),
            }
            for r in rows
        ]

    def _diff(
        self,
        table: str,
        name: str,
        v1: int,
        v2: int,
    ) -> dict[str, Any]:
        """Compare two versions of the same item. Returns {v1: data, v2: data, changes: [...]}."""
        item1 = self._get(table, name, v1)
        item2 = self._get(table, name, v2)

        data1 = item1["data"] if item1 else {}
        data2 = item2["data"] if item2 else {}

        changes: list[dict[str, Any]] = []
        all_keys = set(data1.keys()) | set(data2.keys())
        for key in sorted(all_keys):
            old_val = data1.get(key)
            new_val = data2.get(key)
            if old_val != new_val:
                changes.append({"field": key, "old": old_val, "new": new_val})

        return {"v1": data1, "v2": data2, "changes": changes}

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
