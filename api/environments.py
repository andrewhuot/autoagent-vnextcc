"""Environment management — named config overlays with secrets."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class Environment:
    name: str
    config_overrides: dict
    secrets: dict[str, str]
    deployment_target: str
    isolated: bool = True

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "config_overrides": self.config_overrides,
            "secrets": self.secrets,
            "deployment_target": self.deployment_target,
            "isolated": self.isolated,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Environment":
        return cls(
            name=d["name"],
            config_overrides=d.get("config_overrides", {}),
            secrets=d.get("secrets", {}),
            deployment_target=d.get("deployment_target", ""),
            isolated=d.get("isolated", True),
        )


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class EnvironmentManager:
    """In-memory environment registry with config-merge support."""

    def __init__(self) -> None:
        self._envs: dict[str, Environment] = {}

    def create(self, name: str, config_overrides: dict | None = None) -> Environment:
        """Create and register a new environment."""
        env = Environment(
            name=name,
            config_overrides=config_overrides or {},
            secrets={},
            deployment_target="local",
        )
        self._envs[name] = env
        return env

    def get(self, name: str) -> Optional[Environment]:
        """Return the named environment or None."""
        return self._envs.get(name)

    def list_environments(self) -> list[Environment]:
        """Return all registered environments."""
        return list(self._envs.values())

    def get_config_for_env(self, env_name: str, base_config: dict) -> dict:
        """Merge base_config with the environment's overrides.

        Override keys take precedence over base_config values.  The original
        base_config dict is not mutated.
        """
        merged = dict(base_config)
        env = self._envs.get(env_name)
        if env is not None:
            merged.update(env.config_overrides)
        return merged
