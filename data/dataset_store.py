"""SQLite-backed persistence for the dataset service."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


class DatasetStore:
    """SQLite-backed store for datasets, rows, and immutable versions.

    Table layout
    ------------
    datasets        — one row per dataset (id, name, description, current_version, created_at)
    dataset_rows    — individual labelled examples (belongs to a dataset + version)
    dataset_versions — immutable snapshots; create_version freezes the current rows
    """

    def __init__(self, db_path: str = ".autoagent/datasets.db") -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_tables()

    # ------------------------------------------------------------------
    # Schema bootstrap
    # ------------------------------------------------------------------

    def _init_tables(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS datasets (
                    id           TEXT PRIMARY KEY,
                    name         TEXT NOT NULL,
                    description  TEXT NOT NULL DEFAULT '',
                    current_version TEXT NOT NULL DEFAULT '',
                    created_at   TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dataset_rows (
                    id          TEXT PRIMARY KEY,
                    dataset_id  TEXT NOT NULL,
                    version_id  TEXT NOT NULL DEFAULT '',
                    data_json   TEXT NOT NULL,
                    split       TEXT NOT NULL DEFAULT 'tuning',
                    created_at  TEXT NOT NULL,
                    FOREIGN KEY (dataset_id) REFERENCES datasets(id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dataset_versions (
                    id                TEXT PRIMARY KEY,
                    dataset_id        TEXT NOT NULL,
                    content_hash      TEXT NOT NULL DEFAULT '',
                    row_count         INTEGER NOT NULL DEFAULT 0,
                    parent_version_id TEXT,
                    description       TEXT NOT NULL DEFAULT '',
                    created_at        TEXT NOT NULL,
                    FOREIGN KEY (dataset_id) REFERENCES datasets(id)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_rows_dataset ON dataset_rows(dataset_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_rows_version ON dataset_rows(version_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_rows_split ON dataset_rows(split)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_versions_dataset ON dataset_versions(dataset_id)"
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Dataset CRUD
    # ------------------------------------------------------------------

    def create_dataset(
        self,
        name: str,
        description: str = "",
        dataset_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a new dataset record and return its info dict."""
        ds_id = dataset_id or _new_id()
        created_at = _now_iso()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO datasets (id, name, description, current_version, created_at) VALUES (?, ?, ?, ?, ?)",
                (ds_id, name, description, "", created_at),
            )
            conn.commit()
        return {
            "dataset_id": ds_id,
            "name": name,
            "description": description,
            "current_version": "",
            "created_at": created_at,
        }

    def get_dataset(self, dataset_id: str) -> Optional[dict[str, Any]]:
        """Return a dataset info dict or None if not found."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT id, name, description, current_version, created_at FROM datasets WHERE id = ?",
                (dataset_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "dataset_id": row[0],
            "name": row[1],
            "description": row[2],
            "current_version": row[3],
            "created_at": row[4],
        }

    def list_datasets(self) -> list[dict[str, Any]]:
        """Return all datasets ordered by created_at desc."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, name, description, current_version, created_at FROM datasets ORDER BY created_at DESC"
            ).fetchall()
        return [
            {
                "dataset_id": r[0],
                "name": r[1],
                "description": r[2],
                "current_version": r[3],
                "created_at": r[4],
            }
            for r in rows
        ]

    def delete_dataset(self, dataset_id: str) -> bool:
        """Delete a dataset and all its rows and versions. Returns True if found."""
        with sqlite3.connect(self.db_path) as conn:
            affected = conn.execute(
                "DELETE FROM datasets WHERE id = ?", (dataset_id,)
            ).rowcount
            conn.execute(
                "DELETE FROM dataset_rows WHERE dataset_id = ?", (dataset_id,)
            )
            conn.execute(
                "DELETE FROM dataset_versions WHERE dataset_id = ?", (dataset_id,)
            )
            conn.commit()
        return affected > 0

    # ------------------------------------------------------------------
    # Row operations
    # ------------------------------------------------------------------

    def add_rows(
        self,
        dataset_id: str,
        rows: list[dict[str, Any]],
        version_id: str = "",
    ) -> list[str]:
        """Insert rows and return their generated IDs."""
        created_at = _now_iso()
        ids: list[str] = []
        with sqlite3.connect(self.db_path) as conn:
            for row_data in rows:
                row_id = _new_id()
                split = row_data.get("split", "tuning")
                conn.execute(
                    """
                    INSERT INTO dataset_rows
                        (id, dataset_id, version_id, data_json, split, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row_id,
                        dataset_id,
                        version_id,
                        json.dumps(row_data, sort_keys=True, default=str),
                        split,
                        created_at,
                    ),
                )
                ids.append(row_id)
            conn.commit()
        return ids

    def get_rows(
        self,
        dataset_id: str,
        version_id: Optional[str] = None,
        split: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Fetch rows, optionally filtered by version and/or split."""
        params: list[Any] = [dataset_id]
        where = "dataset_id = ?"

        if version_id is not None:
            where += " AND version_id = ?"
            params.append(version_id)

        if split is not None:
            where += " AND split = ?"
            params.append(split)

        with sqlite3.connect(self.db_path) as conn:
            db_rows = conn.execute(
                f"SELECT id, data_json FROM dataset_rows WHERE {where} ORDER BY created_at",
                params,
            ).fetchall()

        result = []
        for r in db_rows:
            data = json.loads(r[1])
            data["_row_id"] = r[0]
            result.append(data)
        return result

    def count_rows(
        self,
        dataset_id: str,
        version_id: Optional[str] = None,
    ) -> int:
        """Count rows for a dataset, optionally within a specific version."""
        params: list[Any] = [dataset_id]
        where = "dataset_id = ?"
        if version_id is not None:
            where += " AND version_id = ?"
            params.append(version_id)
        with sqlite3.connect(self.db_path) as conn:
            count = conn.execute(
                f"SELECT COUNT(*) FROM dataset_rows WHERE {where}", params
            ).fetchone()[0]
        return count

    # ------------------------------------------------------------------
    # Version operations
    # ------------------------------------------------------------------

    def create_version(
        self,
        dataset_id: str,
        description: str = "",
        parent_version_id: Optional[str] = None,
        version_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create an immutable snapshot by tagging current unversioned rows.

        All rows with version_id='' belonging to this dataset are stamped
        with the new version_id, making the snapshot immutable.
        """
        ver_id = version_id or _new_id()
        created_at = _now_iso()

        with sqlite3.connect(self.db_path) as conn:
            # Stamp all unversioned rows with this version_id
            conn.execute(
                "UPDATE dataset_rows SET version_id = ? WHERE dataset_id = ? AND version_id = ''",
                (ver_id, dataset_id),
            )
            # Count the stamped rows
            row_count = conn.execute(
                "SELECT COUNT(*) FROM dataset_rows WHERE dataset_id = ? AND version_id = ?",
                (dataset_id, ver_id),
            ).fetchone()[0]

            # Compute a content hash over the sorted row data
            row_data_rows = conn.execute(
                "SELECT data_json FROM dataset_rows WHERE dataset_id = ? AND version_id = ? ORDER BY id",
                (dataset_id, ver_id),
            ).fetchall()
            content_str = json.dumps(
                [json.loads(r[0]) for r in row_data_rows], sort_keys=True
            )
            content_hash = hashlib.sha256(content_str.encode()).hexdigest()[:16]

            conn.execute(
                """
                INSERT INTO dataset_versions
                    (id, dataset_id, content_hash, row_count, parent_version_id, description, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ver_id,
                    dataset_id,
                    content_hash,
                    row_count,
                    parent_version_id,
                    description,
                    created_at,
                ),
            )
            # Update current_version on the dataset
            conn.execute(
                "UPDATE datasets SET current_version = ? WHERE id = ?",
                (ver_id, dataset_id),
            )
            conn.commit()

        return {
            "version_id": ver_id,
            "dataset_id": dataset_id,
            "content_hash": content_hash,
            "row_count": row_count,
            "parent_version_id": parent_version_id,
            "description": description,
            "created_at": created_at,
        }

    def get_version(self, version_id: str) -> Optional[dict[str, Any]]:
        """Return a version info dict or None if not found."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT id, dataset_id, content_hash, row_count, parent_version_id, description, created_at
                FROM dataset_versions WHERE id = ?
                """,
                (version_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "version_id": row[0],
            "dataset_id": row[1],
            "content_hash": row[2],
            "row_count": row[3],
            "parent_version_id": row[4],
            "description": row[5],
            "created_at": row[6],
        }

    def list_versions(self, dataset_id: str) -> list[dict[str, Any]]:
        """Return all versions for a dataset ordered by created_at desc."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, dataset_id, content_hash, row_count, parent_version_id, description, created_at
                FROM dataset_versions WHERE dataset_id = ? ORDER BY created_at DESC
                """,
                (dataset_id,),
            ).fetchall()
        return [
            {
                "version_id": r[0],
                "dataset_id": r[1],
                "content_hash": r[2],
                "row_count": r[3],
                "parent_version_id": r[4],
                "description": r[5],
                "created_at": r[6],
            }
            for r in rows
        ]
