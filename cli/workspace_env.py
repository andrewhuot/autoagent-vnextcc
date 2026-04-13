"""Workspace-local environment helpers for provider API keys."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from cli.workspace import discover_workspace


WORKSPACE_ENV_FILENAME = ".env"
PROVIDER_API_KEY_ENV_VARS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
)


def workspace_env_path(start: Path | None = None) -> Path:
    """Return the workspace-local env-file path used for saved provider keys."""
    workspace = discover_workspace(start=start)
    if workspace is not None:
        return workspace.agentlab_dir / WORKSPACE_ENV_FILENAME
    base = (start or Path.cwd()).resolve()
    return base / ".agentlab" / WORKSPACE_ENV_FILENAME


def _parse_env_value(value: str) -> str:
    """Normalize one env-file value with basic quote handling."""
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        cleaned = cleaned[1:-1]
    return cleaned.replace("\\n", "\n")


def read_workspace_env(path: Path | None = None) -> dict[str, str]:
    """Read the workspace-local env file into a plain mapping."""
    env_path = path or workspace_env_path()
    if not env_path.exists():
        return {}

    payload: dict[str, str] = {}
    raw = env_path.read_text(encoding="utf-8")
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        key, separator, value = stripped.partition("=")
        if not separator:
            continue
        normalized_key = key.strip()
        if not normalized_key:
            continue
        payload[normalized_key] = _parse_env_value(value)
    return payload


def _encode_env_value(value: str) -> str:
    """Encode one value for the simple workspace env file format."""
    return value.replace("\n", "\\n")


def write_workspace_env_values(
    updates: dict[str, str | None],
    path: Path | None = None,
) -> Path:
    """Merge updates into the workspace env file, removing blank values."""
    env_path = path or workspace_env_path()
    existing = read_workspace_env(env_path)

    for key, raw_value in updates.items():
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        normalized_value = str(raw_value or "").strip()
        if normalized_value:
            existing[normalized_key] = normalized_value
        else:
            existing.pop(normalized_key, None)

    env_path.parent.mkdir(parents=True, exist_ok=True)
    if not existing:
        if env_path.exists():
            env_path.unlink()
        return env_path

    lines = [f"{key}={_encode_env_value(existing[key])}" for key in sorted(existing)]
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        env_path.chmod(0o600)
    except OSError:
        pass
    return env_path


def load_workspace_env(
    start: Path | None = None,
    *,
    override: bool = False,
    environ: dict[str, str] | None = None,
) -> dict[str, str]:
    """Load saved workspace env vars into the target environment mapping."""
    target = environ if environ is not None else os.environ
    loaded = read_workspace_env(workspace_env_path(start))
    for key, value in loaded.items():
        if override or key not in target:
            target[key] = value
    return loaded


def resolve_workspace_env_value(
    env_name: str,
    start: Path | None = None,
    *,
    environ: dict[str, str] | None = None,
) -> str | None:
    """Return the active value for an env var after workspace-env hydration."""
    target = environ if environ is not None else os.environ
    load_workspace_env(start, override=False, environ=target)
    value = str(target.get(env_name) or "").strip()
    return value or None


def mask_secret(value: str | None) -> str | None:
    """Return a safe, human-readable mask for a secret value."""
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    if len(cleaned) <= 6:
        return "*" * len(cleaned)
    return f"{cleaned[:3]}...{cleaned[-6:]}"


def collect_provider_api_key_statuses(
    start: Path | None = None,
    *,
    environ: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Return masked API-key readiness metadata for UI and diagnostics surfaces."""
    target = environ if environ is not None else os.environ
    env_path = workspace_env_path(start)
    saved_values = read_workspace_env(env_path)
    load_workspace_env(start, override=False, environ=target)

    statuses: list[dict[str, Any]] = []
    for env_name in PROVIDER_API_KEY_ENV_VARS:
        active_value = str(target.get(env_name) or "").strip()
        saved_value = str(saved_values.get(env_name) or "").strip()
        source: str | None = None
        if active_value:
            source = "workspace" if saved_value and active_value == saved_value else "environment"
        elif saved_value:
            active_value = saved_value
            source = "workspace"

        statuses.append(
            {
                "name": env_name,
                "configured": bool(active_value),
                "masked_value": mask_secret(active_value),
                "source": source,
                "saved_to_workspace": bool(saved_value),
                "env_path": str(env_path),
            }
        )
    return statuses
