"""Config endpoints — list versions, show YAML, diff two configs."""

from __future__ import annotations

from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException, Query, Request

from api.models import (
    ConfigDiffResponse,
    ConfigListResponse,
    ConfigShowResponse,
    ConfigVersionInfo,
)

router = APIRouter(prefix="/api/config", tags=["config"])


def _get_version_entry(version_manager: object, version: int) -> dict | None:
    """Find a version entry in the manifest by version number."""
    for v in version_manager.manifest["versions"]:
        if v["version"] == version:
            return v
    return None


def _load_version_config(version_manager: object, entry: dict) -> dict:
    """Load the YAML config dict for a version entry."""
    filepath = version_manager.configs_dir / entry["filename"]
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"Config file missing: {entry['filename']}")
    with filepath.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@router.get("/list", response_model=ConfigListResponse)
async def list_configs(request: Request) -> ConfigListResponse:
    """List all config versions with metadata."""
    vm = request.app.state.version_manager
    versions = []
    for v in vm.manifest.get("versions", []):
        versions.append(ConfigVersionInfo(
            version=v["version"],
            config_hash=v["config_hash"],
            filename=v["filename"],
            timestamp=v["timestamp"],
            scores=v.get("scores", {}),
            status=v["status"],
        ))
    return ConfigListResponse(
        versions=versions,
        active_version=vm.manifest.get("active_version"),
        canary_version=vm.manifest.get("canary_version"),
    )


@router.get("/show/{version}", response_model=ConfigShowResponse)
async def show_config(version: int, request: Request) -> ConfigShowResponse:
    """Show the full YAML and parsed dict for a specific config version."""
    vm = request.app.state.version_manager
    entry = _get_version_entry(vm, version)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Version {version} not found")

    config = _load_version_config(vm, entry)
    yaml_content = yaml.safe_dump(config, default_flow_style=False, sort_keys=False)
    return ConfigShowResponse(version=version, yaml_content=yaml_content, config=config)


@router.get("/diff", response_model=ConfigDiffResponse)
async def diff_configs(
    request: Request,
    a: int = Query(..., description="First version number"),
    b: int = Query(..., description="Second version number"),
) -> ConfigDiffResponse:
    """Diff two config versions and return a human-readable diff."""
    from agent.config.schema import validate_config, config_diff

    vm = request.app.state.version_manager

    entry_a = _get_version_entry(vm, a)
    entry_b = _get_version_entry(vm, b)
    if entry_a is None:
        raise HTTPException(status_code=404, detail=f"Version {a} not found")
    if entry_b is None:
        raise HTTPException(status_code=404, detail=f"Version {b} not found")

    config_a = _load_version_config(vm, entry_a)
    config_b = _load_version_config(vm, entry_b)

    try:
        validated_a = validate_config(config_a)
        validated_b = validate_config(config_b)
        diff_str = config_diff(validated_a, validated_b)
    except Exception as exc:
        diff_str = f"Error computing diff: {exc}"

    return ConfigDiffResponse(version_a=a, version_b=b, diff=diff_str)


@router.get("/active")
async def get_active_config(request: Request) -> dict:
    """Get the currently active config."""
    vm = request.app.state.version_manager
    active = vm.get_active_config()
    if active is None:
        raise HTTPException(status_code=404, detail="No active config")
    active_ver = vm.manifest.get("active_version")
    return {
        "version": active_ver,
        "config": active,
        "yaml": yaml.safe_dump(active, default_flow_style=False, sort_keys=False),
    }
