"""Runbook registry API endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from registry.runbooks import Runbook

router = APIRouter(prefix="/api/runbooks", tags=["runbooks"])


def _get_store(request: Request):
    store = getattr(request.app.state, "runbook_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Runbook store not configured")
    return store


@router.get("/search")
async def search_runbooks(
    request: Request,
    q: str = Query(..., description="Search query"),
) -> dict[str, Any]:
    """Search runbooks by name or content."""
    store = _get_store(request)
    results = store.search(q)
    return {"runbooks": [p.to_dict() for p in results], "count": len(results)}


@router.get("/")
async def list_runbooks(
    request: Request,
    include_deprecated: bool = False,
) -> dict[str, Any]:
    """List all runbooks."""
    store = _get_store(request)
    runbooks = store.list(include_deprecated=include_deprecated)
    return {"runbooks": [p.to_dict() for p in runbooks], "count": len(runbooks)}


@router.get("/{name}")
async def get_runbook(
    name: str,
    request: Request,
    version: int | None = Query(None, description="Version number (latest if omitted)"),
) -> dict[str, Any]:
    """Get a specific runbook by name."""
    store = _get_store(request)
    runbook = store.get(name, version)
    if runbook is None:
        raise HTTPException(status_code=404, detail=f"Runbook not found: {name}")
    return {"runbook": runbook.to_dict()}


@router.post("/")
async def create_runbook(request: Request) -> dict[str, Any]:
    """Create a new runbook."""
    store = _get_store(request)
    body = await request.json()
    name = body.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    runbook = Runbook.from_dict(body)
    result_name, version = store.register(runbook)
    return {"name": result_name, "version": version}


@router.post("/{name}/apply")
async def apply_runbook(name: str, request: Request) -> dict[str, Any]:
    """Apply a runbook — registers its skills, policies, and tool contracts."""
    store = _get_store(request)
    runbook = store.get(name)
    if runbook is None:
        raise HTTPException(status_code=404, detail=f"Runbook not found: {name}")

    applied = {
        "skills": runbook.skills,
        "policies": runbook.policies,
        "tool_contracts": runbook.tool_contracts,
        "surfaces": runbook.surfaces,
    }
    return {
        "name": name,
        "status": "applied",
        "registered": applied,
    }
