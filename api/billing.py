"""Hosted Control Plane — billing and invoice generation."""

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
class UsageRecord:
    """A single metered usage event."""

    timestamp: str
    user_id: str
    resource: str
    quantity: float
    unit: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "user_id": self.user_id,
            "resource": self.resource,
            "quantity": self.quantity,
            "unit": self.unit,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UsageRecord":
        return cls(
            timestamp=data["timestamp"],
            user_id=data["user_id"],
            resource=data["resource"],
            quantity=data["quantity"],
            unit=data["unit"],
        )


# ---------------------------------------------------------------------------
# Default unit prices (per unit of resource)
# ---------------------------------------------------------------------------

_DEFAULT_PRICES: dict[str, float] = {
    "token": 0.000002,
    "request": 0.0001,
    "agent_run": 0.01,
    "storage_gb": 0.02,
}


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class BillingService:
    """Record usage events and compute invoices (SQLite-backed)."""

    def __init__(self, db_path: str = ".autoagent/billing.db") -> None:
        self.db_path = db_path
        self._init_db()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS usage (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp  TEXT NOT NULL,
                    user_id    TEXT NOT NULL,
                    resource   TEXT NOT NULL,
                    quantity   REAL NOT NULL,
                    unit       TEXT NOT NULL
                )
                """
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record_usage(self, record: UsageRecord) -> None:
        """Persist a single UsageRecord."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO usage (timestamp, user_id, resource, quantity, unit) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    record.timestamp,
                    record.user_id,
                    record.resource,
                    record.quantity,
                    record.unit,
                ),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_usage(
        self,
        user_id: str,
        since: Optional[str] = None,
    ) -> list[UsageRecord]:
        """Return all usage records for *user_id*, optionally filtered by *since* (ISO timestamp)."""
        with sqlite3.connect(self.db_path) as conn:
            if since:
                rows = conn.execute(
                    "SELECT timestamp, user_id, resource, quantity, unit "
                    "FROM usage WHERE user_id = ? AND timestamp >= ? ORDER BY timestamp ASC",
                    (user_id, since),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT timestamp, user_id, resource, quantity, unit "
                    "FROM usage WHERE user_id = ? ORDER BY timestamp ASC",
                    (user_id,),
                ).fetchall()
        return [UsageRecord(*row) for row in rows]

    # ------------------------------------------------------------------
    # Invoice
    # ------------------------------------------------------------------

    def compute_invoice(
        self,
        user_id: str,
        period_start: str,
        period_end: str,
    ) -> dict[str, Any]:
        """Generate an invoice dict for *user_id* covering *period_start* to *period_end*."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT resource, SUM(quantity) FROM usage "
                "WHERE user_id = ? AND timestamp >= ? AND timestamp <= ? "
                "GROUP BY resource",
                (user_id, period_start, period_end),
            ).fetchall()

        line_items: list[dict[str, Any]] = []
        total_amount = 0.0
        for resource, total_qty in rows:
            unit_price = _DEFAULT_PRICES.get(resource, 0.0001)
            amount = total_qty * unit_price
            total_amount += amount
            line_items.append(
                {
                    "resource": resource,
                    "quantity": total_qty,
                    "unit_price": unit_price,
                    "amount": round(amount, 6),
                }
            )

        return {
            "user_id": user_id,
            "period_start": period_start,
            "period_end": period_end,
            "line_items": line_items,
            "total_amount": round(total_amount, 6),
            "currency": "USD",
            "generated_at": _now_iso(),
        }
