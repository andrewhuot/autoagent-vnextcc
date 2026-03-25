"""Project memory (AUTOAGENT.md) API endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from core.project_memory import ProjectMemory

router = APIRouter(prefix="/api/memory", tags=["memory"])


def _get_memory(request: Request) -> ProjectMemory:
    memory = getattr(request.app.state, "project_memory", None)
    if memory is None:
        raise HTTPException(status_code=503, detail="Project memory not configured")
    return memory


@router.get("/")
async def get_project_memory(request: Request) -> dict[str, Any]:
    """Get the current project memory."""
    memory = _get_memory(request)
    return {"memory": memory.to_dict(), "raw": memory.raw_content}


@router.put("/")
async def update_project_memory(request: Request) -> dict[str, Any]:
    """Update the full project memory from structured data."""
    memory = _get_memory(request)
    body = await request.json()

    if "agent_name" in body:
        memory.agent_name = body["agent_name"]
    if "platform" in body:
        memory.platform = body["platform"]
    if "use_case" in body:
        memory.use_case = body["use_case"]
    if "business_constraints" in body:
        memory.business_constraints = body["business_constraints"]
    if "known_good_patterns" in body:
        memory.known_good_patterns = body["known_good_patterns"]
    if "known_bad_patterns" in body:
        memory.known_bad_patterns = body["known_bad_patterns"]
    if "team_preferences" in body:
        memory.team_preferences = body["team_preferences"]

    try:
        path = memory.save()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save memory: {exc}")

    return {"status": "updated", "path": path, "memory": memory.to_dict()}


@router.post("/note")
async def add_note(request: Request) -> dict[str, Any]:
    """Add a note to a specific section of project memory."""
    memory = _get_memory(request)
    body = await request.json()

    note = body.get("note")
    section = body.get("section")
    if not note or not section:
        raise HTTPException(status_code=400, detail="Both 'note' and 'section' are required")

    valid_sections = {"good", "bad", "preference", "constraint"}
    if section not in valid_sections:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid section '{section}'. Must be one of: {sorted(valid_sections)}",
        )

    memory.add_note(section, note)
    try:
        path = memory.save()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save memory: {exc}")

    return {"status": "added", "section": section, "note": note, "path": path}


@router.get("/context")
async def get_optimizer_context(request: Request) -> dict[str, Any]:
    """Get the optimizer-relevant context from project memory."""
    memory = _get_memory(request)
    return {"context": memory.get_optimizer_context()}
