"""Registry CRUD API endpoints."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from registry.handoff_schemas import HandoffSchemaRegistry
from registry.importer import import_from_file
from registry.policies import PolicyRegistry
from registry.skills import SkillRegistry
from registry.store import RegistryStore
from registry.tool_contracts import ToolContractRegistry

router = APIRouter(prefix="/api/registry", tags=["registry"])

_VALID_TYPES = {"skills", "policies", "tool_contracts", "handoff_schemas"}

_REGISTRY_CLASSES: dict[str, type] = {
    "skills": SkillRegistry,
    "policies": PolicyRegistry,
    "tool_contracts": ToolContractRegistry,
    "handoff_schemas": HandoffSchemaRegistry,
}


def _get_store(request: Request) -> RegistryStore:
    store = getattr(request.app.state, "registry_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Registry store not configured")
    return store


def _get_registry(request: Request, item_type: str) -> Any:
    if item_type not in _VALID_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid item_type '{item_type}'. Must be one of: {sorted(_VALID_TYPES)}",
        )
    store = _get_store(request)
    cls = _REGISTRY_CLASSES[item_type]
    return cls(store)


@router.get("/search")
async def search_registry(
    request: Request,
    q: str = Query(..., description="Search query"),
    type: Optional[str] = Query(None, description="Filter by item type"),
) -> dict:
    """Search registry items by substring match."""
    store = _get_store(request)
    if type is not None:
        if type not in _VALID_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid type '{type}'. Must be one of: {sorted(_VALID_TYPES)}",
            )
        results = store._search(type, q)
        return {"results": results}

    # Search all types
    results: list[dict[str, Any]] = []
    for item_type in sorted(_VALID_TYPES):
        for item in store._search(item_type, q):
            item["item_type"] = item_type
            results.append(item)
    return {"results": results}


@router.post("/import")
async def import_registry(
    request: Request,
    body: dict[str, Any],
) -> dict:
    """Bulk import registry items from a file."""
    store = _get_store(request)
    file_path = body.get("file_path")
    if not file_path:
        raise HTTPException(status_code=400, detail="file_path is required")
    try:
        counts = import_from_file(file_path, store)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"imported": counts}


@router.get("/{item_type}")
async def list_items(
    request: Request,
    item_type: str,
) -> dict:
    """List all items of a given type."""
    registry = _get_registry(request, item_type)
    items = registry.list()
    return {"items": items}


@router.get("/{item_type}/{name}/diff")
async def diff_versions(
    request: Request,
    item_type: str,
    name: str,
    v1: int = Query(..., description="First version"),
    v2: int = Query(..., description="Second version"),
) -> dict:
    """Diff two versions of a registry item."""
    store = _get_store(request)
    if item_type not in _VALID_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid item_type '{item_type}'. Must be one of: {sorted(_VALID_TYPES)}",
        )
    result = store._diff(item_type, name, v1, v2)
    return {"v1_data": result["v1"], "v2_data": result["v2"], "changes": result["changes"]}


@router.get("/{item_type}/{name}")
async def get_item(
    request: Request,
    item_type: str,
    name: str,
    version: Optional[int] = Query(None, description="Version number (latest if omitted)"),
) -> dict:
    """Get a specific registry item by name and optional version."""
    registry = _get_registry(request, item_type)
    item = registry.get(name, version)
    if item is None:
        raise HTTPException(status_code=404, detail=f"{item_type} '{name}' not found")
    return {"item": item}


@router.post("/{item_type}")
async def create_item(
    request: Request,
    item_type: str,
    body: dict[str, Any],
) -> dict:
    """Create/register a new registry item."""
    registry = _get_registry(request, item_type)
    name = body.pop("name", None) or body.pop("tool_name", None)
    if not name:
        raise HTTPException(status_code=400, detail="name (or tool_name) is required")

    try:
        if item_type == "skills":
            result_name, version = registry.register(
                name=name,
                instructions=body.get("instructions", ""),
                examples=body.get("examples"),
                tool_requirements=body.get("tool_requirements"),
                constraints=body.get("constraints"),
                metadata=body.get("metadata"),
            )
        elif item_type == "policies":
            result_name, version = registry.register(
                name=name,
                rules=body.get("rules", []),
                enforcement=body.get("enforcement", "hard"),
                scope=body.get("scope", "global"),
                metadata=body.get("metadata"),
            )
        elif item_type == "tool_contracts":
            result_name, version = registry.register(
                tool_name=name,
                input_schema=body.get("input_schema"),
                output_schema=body.get("output_schema"),
                side_effect_class=body.get("side_effect_class", "pure"),
                replay_mode=body.get("replay_mode", "deterministic_stub"),
                description=body.get("description", ""),
                metadata=body.get("metadata"),
            )
        elif item_type == "handoff_schemas":
            result_name, version = registry.register(
                name=name,
                from_agent=body.get("from_agent", ""),
                to_agent=body.get("to_agent", ""),
                required_fields=body.get("required_fields", []),
                optional_fields=body.get("optional_fields"),
                validation_rules=body.get("validation_rules"),
                metadata=body.get("metadata"),
            )
        else:
            raise HTTPException(status_code=400, detail=f"Unknown item_type: {item_type}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"name": result_name, "version": version}
