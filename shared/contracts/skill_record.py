"""Shared skill record contract."""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any


@dataclass(slots=True)
class SkillRecord:
    """Describe a durable skill entry shared by CLI, API, and UI."""

    skill_id: str
    name: str
    kind: str
    version: str
    domain: str
    status: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    effectiveness: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    skill_layer: str = ""  # "build", "runtime", or "" (unclassified)
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation for persistence and transport."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillRecord:
        """Rehydrate a skill record from persisted data."""
        return cls(
            skill_id=data["skill_id"],
            name=data["name"],
            kind=data["kind"],
            version=data["version"],
            domain=data["domain"],
            status=data["status"],
            description=data.get("description", ""),
            tags=list(data.get("tags", [])),
            effectiveness=dict(data.get("effectiveness", {})),
            source=data.get("source", ""),
            skill_layer=data.get("skill_layer", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            metadata=dict(data.get("metadata", {})),
        )
