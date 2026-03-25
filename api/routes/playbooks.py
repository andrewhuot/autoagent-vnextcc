"""Playbook registry API endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from registry.playbooks import Playbook

router = APIRouter(prefix="/api/playbooks", tags=["playbooks"])


def _get_store(request: Request):
    store = getattr(request.app.state, "playbook_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Playbook store not configured")
    return store


@router.get("/search")
async def search_playbooks(
    request: Request,
    q: str = Query(..., description="Search query"),
) -> dict[str, Any]:
    """Search playbooks by name or content."""
    store = _get_store(request)
    results = store.search(q)
    return {"playbooks": [p.to_dict() for p in results], "count": len(results)}


@router.get("/")
async def list_playbooks(
    request: Request,
    include_deprecated: bool = False,
) -> dict[str, Any]:
    """List all playbooks."""
    store = _get_store(request)
    playbooks = store.list(include_deprecated=include_deprecated)
    return {"playbooks": [p.to_dict() for p in playbooks], "count": len(playbooks)}


@router.get("/{name}")
async def get_playbook(
    name: str,
    request: Request,
    version: int | None = Query(None, description="Version number (latest if omitted)"),
) -> dict[str, Any]:
    """Get a specific playbook by name."""
    store = _get_store(request)
    playbook = store.get(name, version)
    if playbook is None:
        raise HTTPException(status_code=404, detail=f"Playbook not found: {name}")
    return {"playbook": playbook.to_dict()}


@router.post("/")
async def create_playbook(request: Request) -> dict[str, Any]:
    """Create a new playbook."""
    store = _get_store(request)
    body = await request.json()
    name = body.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    playbook = Playbook.from_dict(body)
    result_name, version = store.register(playbook)
    return {"name": result_name, "version": version}


@router.post("/{name}/apply")
async def apply_playbook(name: str, request: Request) -> dict[str, Any]:
    """Apply a playbook — registers its skills, policies, and tool contracts."""
    store = _get_store(request)
    playbook = store.get(name)
    if playbook is None:
        raise HTTPException(status_code=404, detail=f"Playbook not found: {name}")

    applied = {
        "skills": playbook.skills,
        "policies": playbook.policies,
        "tool_contracts": playbook.tool_contracts,
        "surfaces": playbook.surfaces,
    }
    return {
        "name": name,
        "status": "applied",
        "registered": applied,
    }
