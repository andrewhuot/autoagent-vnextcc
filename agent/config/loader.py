"""Config loading with canary support."""

from __future__ import annotations

import os
import random
from pathlib import Path

import yaml

from agent.config.schema import AgentConfig, validate_config


def load_config(path: str) -> AgentConfig:
    """Load and validate an agent config from a YAML file."""
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(config_path) as f:
        data = yaml.safe_load(f)

    return validate_config(data)


def load_config_with_canary(configs_dir: str) -> AgentConfig:
    """Load active config, with canary_percentage chance of loading canary instead.

    Looks for:
      - active.yaml — the current production config
      - canary.yaml — the canary candidate (optional)
      - canary_percentage.txt — a float 0-1 for canary traffic (optional)

    Falls back to the latest versioned config (v*_*.yaml) if active.yaml missing.
    """
    configs_path = Path(configs_dir)

    # Determine active config path
    active_path = configs_path / "active.yaml"
    if not active_path.exists():
        # Fall back to latest versioned config
        versions = sorted(configs_path.glob("v*_*.yaml"))
        if not versions:
            raise FileNotFoundError(
                f"No config files found in {configs_dir}"
            )
        active_path = versions[-1]

    # Check for canary
    canary_path = configs_path / "canary.yaml"
    canary_pct_path = configs_path / "canary_percentage.txt"

    if canary_path.exists() and canary_pct_path.exists():
        try:
            canary_pct = float(canary_pct_path.read_text().strip())
        except (ValueError, OSError):
            canary_pct = 0.0

        if 0 < canary_pct <= 1 and random.random() < canary_pct:
            return load_config(str(canary_path))

    return load_config(str(active_path))
