"""Versioned CRUD for tool contracts. Wraps ToolContractVersion."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from registry.store import RegistryStore


class ToolContractRegistry:
    """Versioned CRUD for tool contracts."""

    TABLE = "tool_contracts"

    def __init__(self, store: RegistryStore) -> None:
        self.store = store
        # Track which agents use which tools: tool_name -> set of agent names
        self._agent_usage: dict[str, set[str]] = {}

    def register(
        self,
        tool_name: str,
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        side_effect_class: str = "pure",
        replay_mode: str = "deterministic_stub",
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> tuple[str, int]:
        """Register a new tool contract version. Returns (tool_name, version)."""
        version = self.store._get_latest_version(self.TABLE, tool_name) + 1
        now = datetime.now(timezone.utc).isoformat()

        data: dict[str, Any] = {
            "tool_name": tool_name,
            "input_schema": input_schema or {},
            "output_schema": output_schema or {},
            "side_effect_class": side_effect_class,
            "replay_mode": replay_mode,
            "description": description,
            "metadata": metadata or {},
        }

        self.store._insert(self.TABLE, tool_name, version, data, now)
        return (tool_name, version)

    def get(self, name: str, version: int | None = None) -> dict[str, Any] | None:
        """Get a tool contract by name and optional version."""
        return self.store._get(self.TABLE, name, version)

    def list(self, include_deprecated: bool = False) -> list[dict[str, Any]]:
        """List all tool contracts."""
        return self.store._list(self.TABLE, include_deprecated)

    def update(self, name: str, **updates: Any) -> tuple[str, int]:
        """Create a new version with the given updates applied on top of the latest."""
        current = self.store._get(self.TABLE, name)
        if current is None:
            raise ValueError(f"Tool contract '{name}' not found")

        data = dict(current["data"])
        data.update(updates)

        version = self.store._get_latest_version(self.TABLE, name) + 1
        now = datetime.now(timezone.utc).isoformat()
        self.store._insert(self.TABLE, name, version, data, now)
        return (name, version)

    def deprecate(self, name: str, version: int) -> bool:
        """Deprecate a specific tool contract version."""
        return self.store._deprecate(self.TABLE, name, version)

    def register_agent_usage(self, tool_name: str, agent_name: str) -> None:
        """Record that an agent uses a specific tool."""
        if tool_name not in self._agent_usage:
            self._agent_usage[tool_name] = set()
        self._agent_usage[tool_name].add(agent_name)

    def get_agents_using(self, tool_name: str) -> list[str]:
        """Return sorted list of agents that use the given tool."""
        return sorted(self._agent_usage.get(tool_name, set()))
