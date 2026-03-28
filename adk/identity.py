"""Agent Identity Framework — persistent agent identity management."""

from __future__ import annotations

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
class AgentIdentity:
    """Persistent identity record for a single agent instance."""

    agent_id: str
    display_name: str
    version: str
    lineage_parent: Optional[str]
    created_at: str
    iam_identity: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "display_name": self.display_name,
            "version": self.version,
            "lineage_parent": self.lineage_parent,
            "created_at": self.created_at,
            "iam_identity": self.iam_identity,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentIdentity":
        return cls(
            agent_id=data["agent_id"],
            display_name=data["display_name"],
            version=data["version"],
            lineage_parent=data.get("lineage_parent"),
            created_at=data["created_at"],
            iam_identity=data.get("iam_identity"),
            metadata=data.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class AgentIdentityManager:
    """Create and manage persistent agent identities (in-memory store)."""

    def __init__(self) -> None:
        self._identities: dict[str, AgentIdentity] = {}

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create_identity(self, name: str, version: str) -> AgentIdentity:
        """Create and store a new AgentIdentity, returning it."""
        identity = AgentIdentity(
            agent_id=uuid.uuid4().hex,
            display_name=name,
            version=version,
            lineage_parent=None,
            created_at=_now_iso(),
        )
        self._identities[identity.agent_id] = identity
        return identity

    def get_identity(self, agent_id: str) -> Optional[AgentIdentity]:
        """Return the AgentIdentity for *agent_id*, or None if not found."""
        return self._identities.get(agent_id)

    def update_lineage(self, agent_id: str, parent_id: str) -> None:
        """Set the lineage parent of *agent_id* to *parent_id*."""
        identity = self._identities.get(agent_id)
        if identity is not None:
            identity.lineage_parent = parent_id

    def list_identities(self) -> list[AgentIdentity]:
        """Return all stored identities sorted by creation time."""
        return sorted(
            self._identities.values(),
            key=lambda i: i.created_at,
        )
