"""Versioned CRUD for skills. Wraps SkillVersion from core/types.py."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from registry.store import RegistryStore


class SkillRegistry:
    """Versioned CRUD for skills."""

    TABLE = "skills"

    def __init__(self, store: RegistryStore) -> None:
        self.store = store

    def register(
        self,
        name: str,
        instructions: str,
        examples: list[dict[str, Any]] | None = None,
        tool_requirements: list[str] | None = None,
        constraints: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[str, int]:
        """Register a new skill version. Returns (name, version)."""
        version = self.store._get_latest_version(self.TABLE, name) + 1
        now = datetime.now(timezone.utc).isoformat()

        data: dict[str, Any] = {
            "name": name,
            "instructions": instructions,
            "examples": examples or [],
            "tool_requirements": tool_requirements or [],
            "constraints": constraints or [],
            "metadata": metadata or {},
        }

        self.store._insert(self.TABLE, name, version, data, now)
        return (name, version)

    def get(self, name: str, version: int | None = None) -> dict[str, Any] | None:
        """Get a skill by name and optional version."""
        return self.store._get(self.TABLE, name, version)

    def list(self, include_deprecated: bool = False) -> list[dict[str, Any]]:
        """List all skills."""
        return self.store._list(self.TABLE, include_deprecated)

    def update(self, name: str, **updates: Any) -> tuple[str, int]:
        """Create a new version with the given updates applied on top of the latest."""
        current = self.store._get(self.TABLE, name)
        if current is None:
            raise ValueError(f"Skill '{name}' not found")

        data = dict(current["data"])
        data.update(updates)

        version = self.store._get_latest_version(self.TABLE, name) + 1
        now = datetime.now(timezone.utc).isoformat()
        self.store._insert(self.TABLE, name, version, data, now)
        return (name, version)

    def deprecate(self, name: str, version: int) -> bool:
        """Deprecate a specific skill version."""
        return self.store._deprecate(self.TABLE, name, version)

    def diff(self, name: str, v1: int, v2: int) -> dict[str, Any]:
        """Compare two versions of a skill."""
        return self.store._diff(self.TABLE, name, v1, v2)

    def search(self, query: str) -> list[dict[str, Any]]:
        """Search skills by substring match."""
        return self.store._search(self.TABLE, query)

    def export(self, name: str, version: int | None = None) -> dict[str, Any]:
        """Export a skill for YAML/JSON serialisation."""
        item = self.store._get(self.TABLE, name, version)
        if item is None:
            return {}
        return {
            "name": item["name"],
            "version": item["version"],
            **item["data"],
        }
