"""One-time migration of legacy AgentLab config into the new settings cascade.

Pre-P0 users had two stale shapes for their config:

* environment variables like ``AGENTLAB_MODEL``, ``AGENTLAB_PROVIDER``,
  and the various ``*_API_KEY`` vars,
* a flat single-file ``~/.agentlab/config.json`` with dotted keys.

P0 introduces a typed three-layer cascade with the canonical user file at
``~/.agentlab/settings.json``. On first launch after P0 lands we lift any
legacy state into that file so the rest of the runtime sees a consistent
view. The migration is:

* idempotent — guarded by a marker file at ``.settings_migrated_v1``,
* non-destructive — legacy ``config.json`` is left in place,
* opt-out — set ``AGENTLAB_NO_SETTINGS_MIGRATION=1`` to skip,
* forward-compatible — unknown keys in the legacy config are preserved.

The function takes the AgentLab home directory (typically ``~/.agentlab``)
rather than guessing it itself, so tests can drive it against ``tmp_path``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .env_bridge import env_overrides
from .loader import _deep_merge, _flatten_dotted, _load_json


MARKER_FILENAME = ".settings_migrated_v1"
SETTINGS_FILENAME = "settings.json"
LEGACY_CONFIG_FILENAME = "config.json"

# Additional legacy env vars that env_bridge does NOT cover. Migration
# captures these into settings.json so the user can drop them from their
# shell profile after upgrading.
_EXTRA_ENV_BRIDGES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("AGENTLAB_MODEL", ("providers", "default_model")),
    ("AGENTLAB_PROVIDER", ("providers", "default_provider")),
)


@dataclass
class MigrationResult:
    """What the migration did, for reporting via /doctor and logs."""

    migrated: bool = False
    source: str = "none"
    keys_migrated: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def migrate_legacy_settings(home_dir: Path) -> MigrationResult:
    """Migrate legacy env vars and config.json into ``home_dir/settings.json``.

    Parameters
    ----------
    home_dir:
        The AgentLab home directory — typically ``~/.agentlab``. Created
        if absent. The migration writes ``settings.json`` and
        ``.settings_migrated_v1`` inside this directory.
    """
    if _env_truthy(os.environ.get("AGENTLAB_NO_SETTINGS_MIGRATION")):
        return MigrationResult(migrated=False, source="skipped")

    marker = home_dir / MARKER_FILENAME
    if marker.exists():
        return MigrationResult(migrated=False, source="already_migrated")

    settings_path = home_dir / SETTINGS_FILENAME
    if settings_path.exists():
        # The user already has a new-style file; just stamp the marker so
        # we never re-scan again.
        _ensure_dir(home_dir)
        _touch(marker)
        return MigrationResult(migrated=False, source="settings_present")

    legacy_path = home_dir / LEGACY_CONFIG_FILENAME
    legacy_payload, legacy_keys = _read_legacy_config(legacy_path)
    env_payload, env_keys = _read_legacy_env(os.environ)

    if not legacy_payload and not env_payload:
        # Nothing to migrate; still stamp the marker so we skip the work
        # next time.
        _ensure_dir(home_dir)
        _touch(marker)
        return MigrationResult(migrated=False, source="none")

    merged = _deep_merge(legacy_payload, env_payload)
    keys_migrated = sorted(set(legacy_keys) | set(env_keys))

    _ensure_dir(home_dir)
    settings_path.write_text(
        json.dumps(merged, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _touch(marker)

    if legacy_payload and env_payload:
        source = "legacy_config+env"
    elif legacy_payload:
        source = "legacy_config"
    else:
        source = "env"

    return MigrationResult(
        migrated=True,
        source=source,
        keys_migrated=keys_migrated,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_legacy_config(path: Path) -> tuple[dict[str, Any], list[str]]:
    """Load and normalize the legacy single-file config, if present.

    Returns the nested dict plus the list of dotted keys we lifted, so the
    caller can report exactly what changed.
    """
    if not path.exists():
        return {}, []
    raw = _load_json(path)
    if not isinstance(raw, dict) or not raw:
        return {}, []

    keys: list[str] = []
    nested: dict[str, Any] = {}
    for key, value in raw.items():
        if isinstance(key, str) and "." in key:
            keys.append(key)
        else:
            keys.extend(_walk_keys(key, value))
        nested = _deep_merge(nested, _flatten_dotted({key: value}))
    return nested, keys


def _walk_keys(prefix: Any, value: Any) -> list[str]:
    """Build dotted-key strings for an already-nested mapping for reporting."""
    if not isinstance(prefix, str):
        return []
    if not isinstance(value, dict):
        return [prefix]
    out: list[str] = []
    for child_key, child_value in value.items():
        if not isinstance(child_key, str):
            continue
        out.extend(_walk_keys(f"{prefix}.{child_key}", child_value))
    return out


def _read_legacy_env(environ: Mapping[str, str]) -> tuple[dict[str, Any], list[str]]:
    """Combine env_bridge overrides with the migration-only AGENTLAB_* vars."""
    payload, applied = env_overrides(environ)
    keys = [_path_to_dotted(_lookup_env_path(name)) for name in applied]
    keys = [k for k in keys if k]

    for env_name, dotted_path in _EXTRA_ENV_BRIDGES:
        raw = environ.get(env_name)
        if raw is None or raw == "":
            continue
        _set_nested(payload, dotted_path, raw)
        keys.append(_path_to_dotted(dotted_path))

    return payload, keys


def _lookup_env_path(env_name: str) -> tuple[str, ...]:
    """Map an env var name back to its dotted path. Empty tuple if unknown."""
    from .env_bridge import _ENV_BRIDGES

    for name, path, _kind in _ENV_BRIDGES:
        if name == env_name:
            return path
    return ()


def _path_to_dotted(path: tuple[str, ...]) -> str:
    return ".".join(path)


def _set_nested(target: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    node: dict[str, Any] = target
    for part in path[:-1]:
        child = node.setdefault(part, {})
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    node[path[-1]] = value


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def _env_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


__all__ = ["MigrationResult", "migrate_legacy_settings"]
