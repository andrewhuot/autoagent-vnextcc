"""Hosted Control Plane — SLA target definition, compliance checking, and uptime."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SlaTarget:
    """A single SLA target for a named metric."""

    metric: str
    target: float
    period: str = "monthly"

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "target": self.target,
            "period": self.period,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SlaTarget":
        return cls(
            metric=data["metric"],
            target=data["target"],
            period=data.get("period", "monthly"),
        )


# ---------------------------------------------------------------------------
# Monitor
# ---------------------------------------------------------------------------

class SlaMonitor:
    """Define SLA targets and check compliance against a SQLite metrics store."""

    def __init__(self, db_path: str = ".autoagent/sla.db") -> None:
        self.db_path = db_path
        self._targets: dict[str, SlaTarget] = {}
        self._init_db()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS metric_events (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    service   TEXT NOT NULL,
                    metric    TEXT NOT NULL,
                    value     REAL NOT NULL,
                    timestamp TEXT NOT NULL,
                    status    TEXT NOT NULL DEFAULT 'ok'
                )
                """
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Target management
    # ------------------------------------------------------------------

    def define_target(self, target: SlaTarget) -> None:
        """Register an SLA target for *target.metric*."""
        self._targets[target.metric] = target

    # ------------------------------------------------------------------
    # Compliance check
    # ------------------------------------------------------------------

    def check_compliance(self, metric: str) -> dict[str, Any]:
        """Return a compliance report for *metric* against its registered target.

        If no events exist yet the metric is reported as compliant (no data).
        """
        target = self._targets.get(metric)
        if target is None:
            return {
                "metric": metric,
                "compliant": None,
                "reason": "No SLA target defined for this metric.",
                "checked_at": _now_iso(),
            }

        # Fetch recent metric events
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT value, status FROM metric_events WHERE metric = ? ORDER BY timestamp DESC LIMIT 1000",
                (metric,),
            ).fetchall()

        if not rows:
            return {
                "metric": metric,
                "target": target.target,
                "period": target.period,
                "compliant": True,
                "reason": "No metric events recorded; assuming compliant.",
                "checked_at": _now_iso(),
            }

        total = len(rows)
        ok_count = sum(1 for _, status in rows if status == "ok")
        observed_rate = ok_count / total if total else 1.0
        compliant = observed_rate >= target.target

        return {
            "metric": metric,
            "target": target.target,
            "period": target.period,
            "observed_rate": round(observed_rate, 6),
            "total_events": total,
            "ok_events": ok_count,
            "compliant": compliant,
            "delta": round(observed_rate - target.target, 6),
            "checked_at": _now_iso(),
        }

    # ------------------------------------------------------------------
    # Uptime
    # ------------------------------------------------------------------

    def get_uptime(self, service: str, period_days: int = 30) -> float:
        """Return the uptime fraction (0.0–1.0) for *service* over *period_days*.

        Uptime is computed as ``ok_events / total_events`` for the service.
        Returns 1.0 if no events are recorded (optimistic default).
        """
        since = (
            datetime.now(timezone.utc) - timedelta(days=period_days)
        ).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*), SUM(CASE WHEN status = 'ok' THEN 1 ELSE 0 END) "
                "FROM metric_events WHERE service = ? AND timestamp >= ?",
                (service, since),
            ).fetchone()

        if row is None or row[0] == 0:
            return 1.0

        total, ok = row
        ok = ok or 0
        return round(ok / total, 6)

    # ------------------------------------------------------------------
    # Helper: record a metric event (used in tests / integrations)
    # ------------------------------------------------------------------

    def record_event(
        self,
        service: str,
        metric: str,
        value: float,
        status: str = "ok",
        timestamp: str | None = None,
    ) -> None:
        """Insert a metric event into the store."""
        ts = timestamp or _now_iso()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO metric_events (service, metric, value, timestamp, status) "
                "VALUES (?, ?, ?, ?, ?)",
                (service, metric, value, ts, status),
            )
            conn.commit()
