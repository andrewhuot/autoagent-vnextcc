"""Versioned CRUD for policy packs. Wraps PolicyPackVersion."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from registry.store import RegistryStore


class PolicyRegistry:
    """Versioned CRUD for policy packs."""

    TABLE = "policies"

    def __init__(self, store: RegistryStore) -> None:
        self.store = store

    def register(
        self,
        name: str,
        rules: list[str],
        enforcement: str = "hard",
        scope: str = "global",
        metadata: dict[str, Any] | None = None,
    ) -> tuple[str, int]:
        """Register a new policy version. Returns (name, version)."""
        version = self.store._get_latest_version(self.TABLE, name) + 1
        now = datetime.now(timezone.utc).isoformat()

        data: dict[str, Any] = {
            "name": name,
            "rules": rules,
            "enforcement": enforcement,
            "scope": scope,
            "metadata": metadata or {},
        }

        self.store._insert(self.TABLE, name, version, data, now)
        return (name, version)

    def get(self, name: str, version: int | None = None) -> dict[str, Any] | None:
        """Get a policy by name and optional version."""
        return self.store._get(self.TABLE, name, version)

    def list(self, include_deprecated: bool = False) -> list[dict[str, Any]]:
        """List all policies."""
        return self.store._list(self.TABLE, include_deprecated)

    def update(self, name: str, **updates: Any) -> tuple[str, int]:
        """Create a new version with the given updates applied on top of the latest."""
        current = self.store._get(self.TABLE, name)
        if current is None:
            raise ValueError(f"Policy '{name}' not found")

        data = dict(current["data"])
        data.update(updates)

        version = self.store._get_latest_version(self.TABLE, name) + 1
        now = datetime.now(timezone.utc).isoformat()
        self.store._insert(self.TABLE, name, version, data, now)
        return (name, version)

    def deprecate(self, name: str, version: int) -> bool:
        """Deprecate a specific policy version."""
        return self.store._deprecate(self.TABLE, name, version)

    def diff(self, name: str, v1: int, v2: int) -> dict[str, Any]:
        """Compare two versions of a policy."""
        return self.store._diff(self.TABLE, name, v1, v2)

    def search(self, query: str) -> list[dict[str, Any]]:
        """Search policies by substring match."""
        return self.store._search(self.TABLE, query)
