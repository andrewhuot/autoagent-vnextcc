"""Shared deployment target contract."""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any


@dataclass(slots=True)
class DeploymentTarget:
    """Describe a deployment destination and how it should be reached."""

    target_id: str
    name: str
    kind: str
    strategy: str
    environment: str
    description: str = ""
    status: str = "inactive"
    endpoint: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation for persistence and transport."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeploymentTarget:
        """Rehydrate a deployment target from persisted data."""
        return cls(
            target_id=data["target_id"],
            name=data["name"],
            kind=data["kind"],
            strategy=data["strategy"],
            environment=data["environment"],
            description=data.get("description", ""),
            status=data.get("status", "inactive"),
            endpoint=data.get("endpoint", ""),
            metadata=dict(data.get("metadata", {})),
        )
