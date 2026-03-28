"""Hosted Control Plane — multi-tenant management and data isolation."""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Tenant:
    """A single tenant in the hosted control plane."""

    tenant_id: str
    name: str
    plan: str
    data_isolation: bool = True
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "name": self.name,
            "plan": self.plan,
            "data_isolation": self.data_isolation,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Tenant":
        return cls(
            tenant_id=data["tenant_id"],
            name=data["name"],
            plan=data["plan"],
            data_isolation=data.get("data_isolation", True),
            created_at=data.get("created_at", _now_iso()),
        )


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class TenantManager:
    """Create and manage tenants with SQLite-backed persistence."""

    def __init__(self, db_path: str = ".autoagent/tenants.db") -> None:
        self.db_path = db_path
        self._init_db()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tenants (
                    tenant_id      TEXT PRIMARY KEY,
                    name           TEXT NOT NULL,
                    plan           TEXT NOT NULL,
                    data_isolation INTEGER NOT NULL DEFAULT 1,
                    created_at     TEXT NOT NULL
                )
                """
            )
            conn.commit()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create_tenant(self, name: str, plan: str) -> Tenant:
        """Create and persist a new Tenant, returning it."""
        tenant = Tenant(
            tenant_id=uuid.uuid4().hex,
            name=name,
            plan=plan,
            data_isolation=True,
            created_at=_now_iso(),
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO tenants (tenant_id, name, plan, data_isolation, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    tenant.tenant_id,
                    tenant.name,
                    tenant.plan,
                    int(tenant.data_isolation),
                    tenant.created_at,
                ),
            )
            conn.commit()
        return tenant

    def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        """Return the Tenant for *tenant_id*, or None if not found."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT tenant_id, name, plan, data_isolation, created_at "
                "FROM tenants WHERE tenant_id = ?",
                (tenant_id,),
            ).fetchone()
        if row is None:
            return None
        return Tenant(
            tenant_id=row[0],
            name=row[1],
            plan=row[2],
            data_isolation=bool(row[3]),
            created_at=row[4],
        )

    def list_tenants(self) -> list[Tenant]:
        """Return all tenants ordered by creation time."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT tenant_id, name, plan, data_isolation, created_at "
                "FROM tenants ORDER BY created_at ASC"
            ).fetchall()
        return [
            Tenant(
                tenant_id=r[0],
                name=r[1],
                plan=r[2],
                data_isolation=bool(r[3]),
                created_at=r[4],
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Data isolation
    # ------------------------------------------------------------------

    def isolate_data(self, tenant_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Stamp *data* with tenant isolation metadata.

        If the tenant has ``data_isolation=True`` the returned dict will
        contain a ``_tenant`` envelope with the tenant_id and a content
        fingerprint.  Callers should treat the envelope as write-once.
        """
        tenant = self.get_tenant(tenant_id)
        if tenant is None or not tenant.data_isolation:
            return data

        fingerprint = hashlib.sha256(
            (tenant_id + str(sorted(data.items()))).encode()
        ).hexdigest()[:16]

        return {
            "_tenant": {
                "tenant_id": tenant_id,
                "plan": tenant.plan,
                "fingerprint": fingerprint,
                "isolated_at": _now_iso(),
            },
            "data": data,
        }
