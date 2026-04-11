"""Agent Builder Workbench API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from builder.workbench import WorkbenchService, WorkbenchStore

router = APIRouter(prefix="/api/workbench", tags=["workbench"])


class CreateWorkbenchProjectRequest(BaseModel):
    """Request body for creating a canonical Workbench project."""

    brief: str = Field(default="", description="Plain-English agent brief.")
    target: str = Field(default="portable", pattern="^(portable|adk|cx)$")
    environment: str = Field(default="draft")


class WorkbenchPlanRequest(BaseModel):
    """Request body for generating a structured change plan."""

    project_id: str
    message: str = Field(min_length=1)
    target: str | None = Field(default=None, pattern="^(portable|adk|cx)$")
    mode: str = Field(default="plan", pattern="^(plan|apply|ask)$")


class WorkbenchApplyRequest(BaseModel):
    """Request body for applying a previously generated plan."""

    project_id: str
    plan_id: str


class WorkbenchTestRequest(BaseModel):
    """Request body for running a manual Workbench test."""

    project_id: str
    message: str = ""


class WorkbenchRollbackRequest(BaseModel):
    """Request body for rollback to an earlier canonical version."""

    project_id: str
    version: int = Field(ge=1)


def _service(request: Request) -> WorkbenchService:
    """Return the Workbench service, creating the JSON store on demand."""
    store = getattr(request.app.state, "workbench_store", None)
    if store is None:
        store = WorkbenchStore()
        request.app.state.workbench_store = store
    return WorkbenchService(store)


@router.post("/projects", status_code=201)
async def create_project(request: Request, body: CreateWorkbenchProjectRequest) -> dict[str, Any]:
    """Create a new canonical Workbench project."""
    return _service(request).create_project(
        brief=body.brief,
        target=body.target,
        environment=body.environment,
    )


@router.get("/projects/default")
async def get_default_project(request: Request) -> dict[str, Any]:
    """Return the newest Workbench project or create a starter draft."""
    return _service(request).get_default_project()


@router.get("/projects/{project_id}")
async def get_project(project_id: str, request: Request) -> dict[str, Any]:
    """Return one Workbench project by ID."""
    try:
        return _service(request).get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workbench project not found") from exc


@router.post("/plan")
async def plan_change(request: Request, body: WorkbenchPlanRequest) -> dict[str, Any]:
    """Plan natural-language changes without mutating canonical state."""
    try:
        return _service(request).plan_change(
            project_id=body.project_id,
            message=body.message,
            target=body.target,
            mode=body.mode,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workbench project not found") from exc


@router.post("/apply")
async def apply_plan(request: Request, body: WorkbenchApplyRequest) -> dict[str, Any]:
    """Apply a planned change and automatically validate the result."""
    try:
        return _service(request).apply_plan(project_id=body.project_id, plan_id=body.plan_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workbench project or plan not found") from exc


@router.post("/test")
async def run_test(request: Request, body: WorkbenchTestRequest) -> dict[str, Any]:
    """Run a deterministic Workbench validation/test pass."""
    try:
        return _service(request).run_test(project_id=body.project_id, message=body.message)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workbench project not found") from exc


@router.post("/rollback")
async def rollback(request: Request, body: WorkbenchRollbackRequest) -> dict[str, Any]:
    """Rollback by creating a new version from a prior canonical snapshot."""
    try:
        return _service(request).rollback(project_id=body.project_id, version=body.version)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workbench project version not found") from exc
