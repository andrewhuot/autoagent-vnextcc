"""CLI settings hierarchy for AutoAgent."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULTS: dict[str, Any] = {
    "shell.prompt": "autoagent> ",
    "shell.show_status_bar": True,
    "output.format": "text",
    "output.color": True,
    "output.banner": True,
    "mode": "default",
    "editor": None,
}

USER_CONFIG_DIR = Path.home() / ".autoagent"
USER_CONFIG_PATH = USER_CONFIG_DIR / "config.json"
PROJECT_SETTINGS_FILENAME = "settings.json"
LOCAL_SETTINGS_FILENAME = "settings.local.json"


def _load_json(path: Path) -> dict[str, Any]:
    """Load a JSON file or return an empty mapping when unavailable."""
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


@dataclass
class ResolvedSettings:
    """Fully resolved CLI settings after all layers are merged."""

    values: dict[str, Any] = field(default_factory=dict)

    def get(self, dotted_key: str, default: Any = None) -> Any:
        """Retrieve a setting by dotted key such as ``shell.prompt``."""
        parts = dotted_key.split(".")
        node: Any = self.values
        for part in parts:
            if isinstance(node, dict):
                node = node.get(part)
            else:
                return default
        return node if node is not None else default


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


def resolve_settings(
    *,
    workspace_dir: Path | None = None,
    session_overrides: dict[str, Any] | None = None,
    flag_overrides: dict[str, Any] | None = None,
) -> ResolvedSettings:
    """Resolve CLI settings from defaults through the highest-priority overrides."""
    merged = _flatten_dotted(DEFAULTS)

    merged = _deep_merge(merged, _flatten_dotted(_load_json(USER_CONFIG_PATH)))

    if workspace_dir is not None:
        project_path = workspace_dir / ".autoagent" / PROJECT_SETTINGS_FILENAME
        merged = _deep_merge(merged, _flatten_dotted(_load_json(project_path)))

        local_path = workspace_dir / ".autoagent" / LOCAL_SETTINGS_FILENAME
        merged = _deep_merge(merged, _flatten_dotted(_load_json(local_path)))

    if session_overrides:
        merged = _deep_merge(merged, _flatten_dotted(session_overrides))

    if flag_overrides:
        merged = _deep_merge(merged, _flatten_dotted(flag_overrides))

    return ResolvedSettings(values=merged)


def save_user_config(data: dict[str, Any]) -> Path:
    """Persist user-level CLI settings to ``~/.autoagent/config.json``."""
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    existing = _load_json(USER_CONFIG_PATH)
    merged = _deep_merge(existing, data)
    USER_CONFIG_PATH.write_text(
        json.dumps(merged, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return USER_CONFIG_PATH


def save_project_settings(workspace_dir: Path, data: dict[str, Any]) -> Path:
    """Persist project-level CLI settings to ``.autoagent/settings.json``."""
    settings_path = workspace_dir / ".autoagent" / PROJECT_SETTINGS_FILENAME
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_json(settings_path)
    merged = _deep_merge(existing, data)
    settings_path.write_text(
        json.dumps(merged, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return settings_path


def save_local_settings(workspace_dir: Path, data: dict[str, Any]) -> Path:
    """Persist local CLI overrides to ``.autoagent/settings.local.json``."""
    local_path = workspace_dir / ".autoagent" / LOCAL_SETTINGS_FILENAME
    local_path.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_json(local_path)
    merged = _deep_merge(existing, data)
    local_path.write_text(
        json.dumps(merged, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return local_path


def settings_file_paths(workspace_dir: Path | None = None) -> list[tuple[str, Path]]:
    """Return the configured settings file paths for diagnostics."""
    paths: list[tuple[str, Path]] = [("user", USER_CONFIG_PATH)]
    if workspace_dir is not None:
        paths.append(("project", workspace_dir / ".autoagent" / PROJECT_SETTINGS_FILENAME))
        paths.append(("local", workspace_dir / ".autoagent" / LOCAL_SETTINGS_FILENAME))
    return paths
