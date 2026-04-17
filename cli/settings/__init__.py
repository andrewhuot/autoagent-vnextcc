"""CLI settings hierarchy for AgentLab."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .loader import (
    LOCAL_SETTINGS_FILENAME,
    PROJECT_SETTINGS_FILENAME,
    SYSTEM_SETTINGS_PATH,
    USER_CONFIG_DIR,
    USER_CONFIG_PATH,
    USER_SETTINGS_PATH,
    _deep_merge,
    _flatten_dotted,
    _load_json,
    load_settings as _load_settings,
)
from .schema import (
    HookCommand,
    HookMatcher,
    Hooks,
    Input,
    MCP,
    Paste,
    PermissionRules,
    Permissions,
    Providers,
    Sessions,
    Settings,
)

# Legacy flat defaults stay in place so older imports keep reading the same map.
DEFAULTS: dict[str, Any] = {
    "shell.prompt": "agentlab> ",
    "shell.show_status_bar": True,
    "output.format": "text",
    "output.color": True,
    "output.banner": True,
    "mode": "default",
    "editor": None,
}


@dataclass
class ResolvedSettings:
    """Fully resolved CLI settings after all layers are merged."""

    values: dict[str, Any] = field(default_factory=dict)
    settings: Settings | None = None

    def get(self, dotted_key: str, default: Any = None) -> Any:
        """Read dotted keys while warning that the flat accessor is deprecated."""
        logging.getLogger(__name__).warning(
            'ResolvedSettings.get("%s") is deprecated; use Settings.get() or direct attributes.',
            dotted_key,
        )
        if self.settings is not None:
            value = self.settings.get(dotted_key, _MISSING)
            if value is not _MISSING:
                return value

        parts = dotted_key.split(".")
        node: Any = self.values
        for part in parts:
            if isinstance(node, dict):
                node = node.get(part, _MISSING)
            else:
                return default
            if node is _MISSING:
                return default
        return default if node is None else node


_MISSING = object()


def _sync_loader_constants() -> None:
    """Keep the loader module aligned with package-level monkeypatches."""
    from . import loader as loader_mod

    loader_mod.SYSTEM_SETTINGS_PATH = SYSTEM_SETTINGS_PATH
    loader_mod.USER_CONFIG_DIR = USER_CONFIG_DIR
    loader_mod.USER_CONFIG_PATH = USER_CONFIG_PATH
    loader_mod.USER_SETTINGS_PATH = USER_SETTINGS_PATH
    loader_mod.PROJECT_SETTINGS_FILENAME = PROJECT_SETTINGS_FILENAME
    loader_mod.LOCAL_SETTINGS_FILENAME = LOCAL_SETTINGS_FILENAME


def resolve_settings(
    *,
    workspace_dir: Path | None = None,
    session_overrides: dict[str, Any] | None = None,
    flag_overrides: dict[str, Any] | None = None,
) -> ResolvedSettings:
    """Resolve CLI settings from defaults through the highest-priority overrides."""
    _sync_loader_constants()

    settings = load_settings(workspace_dir)
    merged: dict[str, Any] = settings.model_dump()

    if session_overrides:
        merged = _deep_merge(merged, _flatten_dotted(session_overrides))

    if flag_overrides:
        merged = _deep_merge(merged, _flatten_dotted(flag_overrides))

    resolved_settings = Settings.model_validate(merged)
    return ResolvedSettings(values=resolved_settings.model_dump(), settings=resolved_settings)


def load_settings(workspace_root: Path | None) -> Settings:
    """Load typed settings through the public package surface."""
    _sync_loader_constants()
    return _load_settings(workspace_root)


def save_user_config(data: dict[str, Any]) -> Path:
    """Persist user-level CLI settings to ``~/.agentlab/config.json``."""
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    existing = _load_json(USER_CONFIG_PATH)
    merged = _deep_merge(existing, data)
    USER_CONFIG_PATH.write_text(
        json.dumps(merged, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return USER_CONFIG_PATH


def save_project_settings(workspace_dir: Path, data: dict[str, Any]) -> Path:
    """Persist project-level CLI settings to ``.agentlab/settings.json``."""
    settings_path = workspace_dir / ".agentlab" / PROJECT_SETTINGS_FILENAME
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_json(settings_path)
    merged = _deep_merge(existing, data)
    settings_path.write_text(
        json.dumps(merged, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return settings_path


def save_local_settings(workspace_dir: Path, data: dict[str, Any]) -> Path:
    """Persist local CLI overrides to ``.agentlab/settings.local.json``."""
    local_path = workspace_dir / ".agentlab" / LOCAL_SETTINGS_FILENAME
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
        paths.append(("project", workspace_dir / ".agentlab" / PROJECT_SETTINGS_FILENAME))
        paths.append(("local", workspace_dir / ".agentlab" / LOCAL_SETTINGS_FILENAME))
    return paths


__all__ = [
    "DEFAULTS",
    "HookCommand",
    "HookMatcher",
    "Hooks",
    "Input",
    "LOCAL_SETTINGS_FILENAME",
    "MCP",
    "PROJECT_SETTINGS_FILENAME",
    "Paste",
    "PermissionRules",
    "Permissions",
    "Providers",
    "Sessions",
    "ResolvedSettings",
    "SYSTEM_SETTINGS_PATH",
    "Settings",
    "USER_CONFIG_DIR",
    "USER_CONFIG_PATH",
    "USER_SETTINGS_PATH",
    "_deep_merge",
    "_flatten_dotted",
    "_load_json",
    "load_settings",
    "resolve_settings",
    "save_local_settings",
    "save_project_settings",
    "save_user_config",
    "settings_file_paths",
]
