"""Config endpoints — list versions, show YAML, diff two configs."""

from __future__ import annotations


import json
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from api.models import (
    ConfigDiffResponse,
    ConfigListResponse,
    ConfigShowResponse,
    ConfigVersionInfo,
)
from cli.stream2_helpers import ConfigImporter
from cli.workspace import discover_workspace

router = APIRouter(prefix="/api/config", tags=["config"])


class ActivateConfigRequest(BaseModel):
    version: int


class ImportConfigRequest(BaseModel):
    file_path: str


class MigrateConfigRequest(BaseModel):
    input_file: str
    output_file: str | None = None


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


def _load_config_dict(path: str) -> dict:
    """Load a YAML or JSON config file from disk."""
    config_path = Path(path)
    raw = config_path.read_text(encoding="utf-8")
    if config_path.suffix.lower() == ".json":
        loaded = json.loads(raw)
    else:
        loaded = yaml.safe_load(raw)
    if not isinstance(loaded, dict):
        raise HTTPException(status_code=400, detail="Config file must contain an object or mapping")
    return loaded


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


@router.post("/activate")
async def activate_config(body: ActivateConfigRequest, request: Request) -> dict:
    """Promote a config version to active and update workspace metadata when present."""
    vm = request.app.state.version_manager
    entry = _get_version_entry(vm, body.version)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Version {body.version} not found")

    try:
        vm.promote(body.version)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    workspace_updated = False
    workspace = discover_workspace()
    if workspace is not None and workspace.configs_dir.resolve() == vm.configs_dir.resolve():
        resolved = workspace.resolve_config_path(body.version)
        if resolved is not None:
            workspace.set_active_config(body.version, filename=resolved.name)
            workspace_updated = True

    return {
        "version": body.version,
        "filename": entry["filename"],
        "status": "active",
        "workspace_updated": workspace_updated,
    }


@router.post("/import")
async def import_config(body: ImportConfigRequest, request: Request) -> dict:
    """Import a YAML or JSON config into the versioned config store."""
    vm = request.app.state.version_manager
    importer = ConfigImporter(configs_dir=str(vm.configs_dir))
    try:
        return importer.import_config(body.file_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/migrate")
async def migrate_config(body: MigrateConfigRequest) -> dict:
    """Migrate an older optimizer config shape into the current optimization layout."""
    from optimizer.mode_router import ModeRouter

    old_config = _load_config_dict(body.input_file)
    router = ModeRouter()
    new_config = router.migrate_config(old_config)
    yaml_content = yaml.safe_dump(new_config, default_flow_style=False, sort_keys=False)

    output_path = None
    if body.output_file:
        output_path = Path(body.output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(yaml_content, encoding="utf-8")

    return {
        "input_file": body.input_file,
        "output_file": str(output_path) if output_path is not None else None,
        "yaml_content": yaml_content,
        "config": new_config,
    }
