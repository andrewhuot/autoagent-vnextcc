"""Agent Builder Workbench API routes."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
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


class WorkbenchBuildStreamRequest(BaseModel):
    """Request body for a streaming agent build run."""

    project_id: str | None = Field(default=None)
    brief: str = Field(min_length=1)
    target: str = Field(default="portable", pattern="^(portable|adk|cx)$")
    environment: str = Field(default="draft")
    mock: bool = Field(default=False, description="Force mock mode for tests.")


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


@router.get("/projects/{project_id}/plan")
async def get_plan_snapshot(project_id: str, request: Request) -> dict[str, Any]:
    """Return the current plan tree and artifacts for page hydration."""
    try:
        return _service(request).get_plan_snapshot(project_id=project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workbench project not found") from exc


def _format_sse(event_name: str, data: dict[str, Any]) -> bytes:
    """Encode one event as a Server-Sent-Events frame."""
    payload = json.dumps(data, default=str)
    return f"event: {event_name}\ndata: {payload}\n\n".encode("utf-8")


@router.post("/build/stream")
async def stream_build(request: Request, body: WorkbenchBuildStreamRequest) -> StreamingResponse:
    """Stream a full agent build (plan tree + per-task artifacts) as SSE.

    WHY: The Workbench UI mirrors Manus — a live plan tree on the left with
    running spinners, artifact cards inline, and a source-code preview on the
    right. That needs low-latency incremental updates, not one JSON blob.
    """
    from builder.workbench_agent import build_default_agent

    service = _service(request)
    agent = build_default_agent(force_mock=body.mock)

    async def event_generator() -> AsyncIterator[bytes]:
        try:
            stream = await service.run_build_stream(
                project_id=body.project_id,
                brief=body.brief,
                target=body.target,
                environment=body.environment,
                agent=agent,
            )
            async for event in stream:
                yield _format_sse(
                    str(event.get("event") or "message"),
                    event.get("data") or {},
                )
        except Exception as exc:  # noqa: BLE001 — surface as an error event
            yield _format_sse("error", {"message": str(exc)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
