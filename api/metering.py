"""Hosted Control Plane — usage metering and aggregation."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class MeterReading:
    """A single meter reading event."""

    meter_id: str
    value: float
    timestamp: str
    labels: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "meter_id": self.meter_id,
            "value": self.value,
            "timestamp": self.timestamp,
            "labels": self.labels,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MeterReading":
        return cls(
            meter_id=data["meter_id"],
            value=data["value"],
            timestamp=data["timestamp"],
            labels=data.get("labels", {}),
        )


# ---------------------------------------------------------------------------
# Meter
# ---------------------------------------------------------------------------

class UsageMeter:
    """Record and aggregate meter readings (SQLite-backed)."""

    def __init__(self, db_path: str = ".autoagent/metering.db") -> None:
        self.db_path = db_path
        self._init_db()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        import json as _json
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS readings (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    meter_id  TEXT NOT NULL,
                    value     REAL NOT NULL,
                    timestamp TEXT NOT NULL,
                    labels    TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record(self, reading: MeterReading) -> None:
        """Persist a MeterReading."""
        import json as _json
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO readings (meter_id, value, timestamp, labels) VALUES (?, ?, ?, ?)",
                (
                    reading.meter_id,
                    reading.value,
                    reading.timestamp,
                    _json.dumps(reading.labels),
                ),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_readings(
        self,
        meter_id: str,
        since: Optional[str] = None,
    ) -> list[MeterReading]:
        """Return all readings for *meter_id*, optionally filtered by *since*."""
        import json as _json
        with sqlite3.connect(self.db_path) as conn:
            if since:
                rows = conn.execute(
                    "SELECT meter_id, value, timestamp, labels FROM readings "
                    "WHERE meter_id = ? AND timestamp >= ? ORDER BY timestamp ASC",
                    (meter_id, since),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT meter_id, value, timestamp, labels FROM readings "
                    "WHERE meter_id = ? ORDER BY timestamp ASC",
                    (meter_id,),
                ).fetchall()
        return [
            MeterReading(
                meter_id=r[0],
                value=r[1],
                timestamp=r[2],
                labels=_json.loads(r[3]),
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def aggregate(self, meter_id: str, period: str = "daily") -> dict[str, Any]:
        """Return aggregated (sum/count/avg) readings grouped by *period*.

        Supported period values: ``"hourly"``, ``"daily"``, ``"monthly"``.
        """
        # SQLite date truncation patterns
        _period_formats: dict[str, str] = {
            "hourly": "%Y-%m-%dT%H",
            "daily": "%Y-%m-%d",
            "monthly": "%Y-%m",
        }
        fmt = _period_formats.get(period, "%Y-%m-%d")

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT strftime('{fmt}', timestamp) AS bucket,
                       SUM(value)   AS total,
                       COUNT(*)     AS count,
                       AVG(value)   AS avg,
                       MIN(value)   AS min,
                       MAX(value)   AS max
                FROM readings
                WHERE meter_id = ?
                GROUP BY bucket
                ORDER BY bucket ASC
                """,
                (meter_id,),
            ).fetchall()

        buckets = [
            {
                "bucket": row[0],
                "total": row[1],
                "count": row[2],
                "avg": round(row[3], 6) if row[3] is not None else 0.0,
                "min": row[4],
                "max": row[5],
            }
            for row in rows
        ]
        return {
            "meter_id": meter_id,
            "period": period,
            "buckets": buckets,
            "generated_at": _now_iso(),
        }
