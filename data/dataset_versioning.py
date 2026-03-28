"""Version pinning for reproducible experiment cards.

A ``VersionPin`` captures every version dimension that can affect an
experiment result: dataset snapshot, grader, judge, config, individual
skill versions, and model version.  Pinning all of them into an
experiment card makes any run fully reproducible.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


# ---------------------------------------------------------------------------
# VersionPin dataclass
# ---------------------------------------------------------------------------


@dataclass
class VersionPin:
    """Immutable snapshot of all version dimensions for one experiment run.

    Storing a VersionPin alongside an experiment result guarantees that
    the exact combination of dataset, graders, judges, config, skills,
    and model can be reconstructed at any future point.
    """

    dataset_version: str
    grader_version: str = ""
    judge_version: str = ""
    config_version: str = ""
    skill_versions: dict[str, str] = field(default_factory=dict)
    model_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_version": self.dataset_version,
            "grader_version": self.grader_version,
            "judge_version": self.judge_version,
            "config_version": self.config_version,
            "skill_versions": self.skill_versions,
            "model_version": self.model_version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "VersionPin":
        return cls(
            dataset_version=d.get("dataset_version", ""),
            grader_version=d.get("grader_version", ""),
            judge_version=d.get("judge_version", ""),
            config_version=d.get("config_version", ""),
            skill_versions=d.get("skill_versions", {}),
            model_version=d.get("model_version", ""),
        )


# ---------------------------------------------------------------------------
# ExperimentCard — wraps a VersionPin with experiment metadata
# ---------------------------------------------------------------------------


@dataclass
class ExperimentCard:
    """An experiment card that pins all version dimensions for reproducibility.

    Cards are stored by ``VersionPinStore`` and can be queried by
    ``pin_id`` or ``experiment_id``.
    """

    pin_id: str = field(default_factory=_new_id)
    experiment_id: str = ""
    name: str = ""
    description: str = ""
    created_at: str = field(default_factory=_now_iso)
    pin: Optional[VersionPin] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pin_id": self.pin_id,
            "experiment_id": self.experiment_id,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at,
            "pin": self.pin.to_dict() if self.pin else {},
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ExperimentCard":
        pin_data = d.get("pin", {})
        return cls(
            pin_id=d.get("pin_id", _new_id()),
            experiment_id=d.get("experiment_id", ""),
            name=d.get("name", ""),
            description=d.get("description", ""),
            created_at=d.get("created_at", _now_iso()),
            pin=VersionPin.from_dict(pin_data) if pin_data else None,
            metadata=d.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# VersionPinStore — SQLite persistence
# ---------------------------------------------------------------------------


class VersionPinStore:
    """SQLite-backed store for VersionPin / ExperimentCard records.

    Table layout
    ------------
    version_pins — one row per pin:
        id TEXT, experiment_id TEXT, name TEXT, description TEXT,
        created_at TEXT, pin_json TEXT, metadata_json TEXT
    """

    def __init__(self, db_path: str = ".autoagent/version_pins.db") -> None:
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
                CREATE TABLE IF NOT EXISTS version_pins (
                    id             TEXT PRIMARY KEY,
                    experiment_id  TEXT NOT NULL DEFAULT '',
                    name           TEXT NOT NULL DEFAULT '',
                    description    TEXT NOT NULL DEFAULT '',
                    created_at     TEXT NOT NULL,
                    pin_json       TEXT NOT NULL DEFAULT '{}',
                    metadata_json  TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_pins_experiment ON version_pins(experiment_id)"
            )
            conn.commit()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def save_pin(
        self,
        pin: VersionPin,
        *,
        pin_id: Optional[str] = None,
        experiment_id: str = "",
        name: str = "",
        description: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ) -> ExperimentCard:
        """Persist a VersionPin and return the resulting ExperimentCard."""
        card = ExperimentCard(
            pin_id=pin_id or _new_id(),
            experiment_id=experiment_id,
            name=name,
            description=description,
            created_at=_now_iso(),
            pin=pin,
            metadata=metadata or {},
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO version_pins
                    (id, experiment_id, name, description, created_at, pin_json, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    card.pin_id,
                    card.experiment_id,
                    card.name,
                    card.description,
                    card.created_at,
                    json.dumps(pin.to_dict(), sort_keys=True),
                    json.dumps(card.metadata, sort_keys=True, default=str),
                ),
            )
            conn.commit()
        return card

    def get_pin(self, pin_id: str) -> Optional[ExperimentCard]:
        """Fetch an ExperimentCard by its pin_id."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT id, experiment_id, name, description, created_at, pin_json, metadata_json
                FROM version_pins WHERE id = ?
                """,
                (pin_id,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_card(row)

    def get_pin_by_experiment(self, experiment_id: str) -> list[ExperimentCard]:
        """Return all pins associated with a given experiment_id."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, experiment_id, name, description, created_at, pin_json, metadata_json
                FROM version_pins WHERE experiment_id = ? ORDER BY created_at DESC
                """,
                (experiment_id,),
            ).fetchall()
        return [self._row_to_card(r) for r in rows]

    def list_pins(self, limit: int = 100) -> list[ExperimentCard]:
        """Return all pins ordered by created_at descending."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, experiment_id, name, description, created_at, pin_json, metadata_json
                FROM version_pins ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_card(r) for r in rows]

    def delete_pin(self, pin_id: str) -> bool:
        """Delete a pin by id. Returns True if a row was deleted."""
        with sqlite3.connect(self.db_path) as conn:
            affected = conn.execute(
                "DELETE FROM version_pins WHERE id = ?", (pin_id,)
            ).rowcount
            conn.commit()
        return affected > 0

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_card(row: tuple[Any, ...]) -> ExperimentCard:
        pin_data = json.loads(row[5]) if row[5] else {}
        meta = json.loads(row[6]) if row[6] else {}
        return ExperimentCard(
            pin_id=row[0],
            experiment_id=row[1],
            name=row[2],
            description=row[3],
            created_at=row[4],
            pin=VersionPin.from_dict(pin_data) if pin_data else None,
            metadata=meta,
        )
