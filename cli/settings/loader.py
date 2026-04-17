"""Load and merge AgentLab settings files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .env_bridge import env_overrides
from .schema import Settings

SYSTEM_SETTINGS_PATH = Path("/etc/agentlab/settings.json")
USER_CONFIG_DIR = Path.home() / ".agentlab"
USER_CONFIG_PATH = USER_CONFIG_DIR / "config.json"
USER_SETTINGS_PATH = USER_CONFIG_DIR / "settings.json"
PROJECT_SETTINGS_FILENAME = "settings.json"
LOCAL_SETTINGS_FILENAME = "settings.local.json"


def _load_json(path: Path) -> dict[str, Any]:
    """Load a JSON file or return an empty mapping when unavailable."""
    import json

    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` into a copy of ``base``."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _flatten_dotted(source: dict[str, Any]) -> dict[str, Any]:
    """Expand dotted keys into nested dictionaries."""
    result: dict[str, Any] = {}
    for key, value in source.items():
        parts = key.split(".")
        node = result
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return result


def _normalize_layer(data: dict[str, Any]) -> dict[str, Any]:
    """Merge flat dotted keys and nested mappings into one nested layer."""
    normalized: dict[str, Any] = {}
    for key, value in data.items():
        normalized = _deep_merge(normalized, _flatten_dotted({key: value}))
    return normalized


def load_settings(workspace_root: Path | None) -> Settings:
    """Load typed settings by cascading defaults, system, user, project, and local files."""
    merged: dict[str, Any] = Settings().model_dump()
    loaded_layers: list[dict[str, str]] = []

    def apply_layer(label: str, path: Path) -> None:
        nonlocal merged
        raw = _load_json(path)
        loaded_layers.append({"layer": label, "path": str(path)})
        if raw:
            merged = _deep_merge(merged, _normalize_layer(raw))

    apply_layer("system", SYSTEM_SETTINGS_PATH)
    apply_layer("legacy_user", USER_CONFIG_PATH)
    apply_layer("user", USER_SETTINGS_PATH)

    if workspace_root is not None:
        workspace_settings_dir = workspace_root / ".agentlab"
        apply_layer("project", workspace_settings_dir / PROJECT_SETTINGS_FILENAME)
        apply_layer("local", workspace_settings_dir / LOCAL_SETTINGS_FILENAME)

    env_layer, env_names = env_overrides()
    if env_layer:
        merged = _deep_merge(merged, env_layer)

    settings = Settings.model_validate(merged)
    settings._loaded_layers = loaded_layers
    settings._env_overrides = env_names
    return settings
