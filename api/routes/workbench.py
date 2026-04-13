"""Agent Builder Workbench API routes."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from builder.workbench import WorkbenchService, WorkbenchStore
from shared.build_artifact_store import BuildArtifactStore

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
    """Request body for a streaming agent build run.

    Multi-turn fields:
        auto_iterate    — when True the service autonomously drives a
                          validation + correction loop after the main
                          plan finishes, up to ``max_iterations`` passes.
        max_iterations  — hard cap on how many plan passes a single turn
                          may run (initial pass + optional corrections).
    """

    project_id: str | None = Field(default=None)
    brief: str = Field(min_length=1)
    target: str = Field(default="portable", pattern="^(portable|adk|cx)$")
    environment: str = Field(default="draft")
    mock: bool = Field(default=False, description="Force mock mode for tests.")
    auto_iterate: bool = Field(
        default=True,
        description="Let the service run corrective iterations after validation.",
    )
    max_iterations: int = Field(
        default=3,
        ge=1,
        le=6,
        description="Cap on plan passes per user turn (initial + corrections).",
    )
    max_seconds: int | None = Field(
        default=None,
        ge=1,
        description="Optional wall-clock budget in seconds.",
    )
    max_tokens: int | None = Field(
        default=None,
        ge=1,
        description="Optional estimated-token budget.",
    )
    max_cost_usd: float | None = Field(
        default=None,
        gt=0,
        description="Optional estimated cost budget in USD.",
    )


class WorkbenchIterateRequest(BaseModel):
    """Follow-up iteration on an existing build."""

    project_id: str
    follow_up: str = Field(min_length=1)
    target: str = Field(default="portable", pattern="^(portable|adk|cx)$")
    environment: str = Field(default="draft")
    mock: bool = Field(default=False, description="Force mock mode for tests.")
    max_iterations: int = Field(default=3, ge=1, le=6)
    max_seconds: int | None = Field(default=None, ge=1)
    max_tokens: int | None = Field(default=None, ge=1)
    max_cost_usd: float | None = Field(default=None, gt=0)


class WorkbenchCancelRunRequest(BaseModel):
    """Request body for cancelling an active Workbench run."""

    project_id: str | None = None
    reason: str = Field(default="Cancelled by operator.")


class WorkbenchEvalBridgeRequest(BaseModel):
    """Request body for materializing a Workbench candidate for Eval."""

    category: str | None = None
    dataset_path: str | None = None
    generated_suite_id: str | None = None
    split: str = Field(default="all", pattern="^(train|test|all)$")


def _build_artifact_store(request: Request) -> BuildArtifactStore:
    """Return the shared build artifact store used by Agent Library saves."""
    store = getattr(request.app.state, "build_artifact_store", None)
    if store is None:
        store = BuildArtifactStore()
        request.app.state.build_artifact_store = store
    return store


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


@router.post("/projects/{project_id}/bridge/eval", status_code=201)
async def create_eval_bridge(
    project_id: str,
    request: Request,
    body: WorkbenchEvalBridgeRequest,
) -> dict[str, Any]:
    """Materialize a Workbench candidate and return typed Eval/Optimize payloads.

    This endpoint saves the generated Workbench config into the real AgentLab
    workspace, then returns request shapes for `/api/eval/run` and
    `/api/optimize/run`. It does not start Eval, does not start Optimize, and
    does not call AutoFix.
    """
    service = _service(request)
    try:
        generated_config = service.generated_config_for_bridge(project_id=project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workbench project not found") from exc

    try:
        from builder.workspace_config import persist_generated_config

        saved = persist_generated_config(
            generated_config,
            artifact_store=_build_artifact_store(request),
            source="builder_chat",
            source_prompt=service.materialization_source_prompt(project_id=project_id),
            builder_session_id=project_id,
        )
        service.record_materialized_candidate(
            project_id=project_id,
            config_path=saved.config_path,
            eval_cases_path=saved.eval_cases_path,
            category=body.category,
            dataset_path=body.dataset_path,
            generated_suite_id=body.generated_suite_id,
            split=body.split,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        bridge = service.build_improvement_bridge_payload(
            project_id=project_id,
            config_path=saved.config_path,
            eval_cases_path=saved.eval_cases_path,
            category=body.category,
            dataset_path=body.dataset_path,
            generated_suite_id=body.generated_suite_id,
            split=body.split,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workbench run not found") from exc

    eval_request = (bridge.get("evaluation") or {}).get("request")
    optimize_template = (bridge.get("optimization") or {}).get("request_template")
    return {
        "bridge": bridge,
        "save_result": saved.to_dict(),
        "eval_request": eval_request,
        "optimize_request_template": optimize_template,
        "next": {
            "start_eval_endpoint": "/api/eval/run",
            "start_optimize_endpoint": "/api/optimize/run",
            "optimize_requires_eval_run": True,
        },
    }


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, request: Request, body: WorkbenchCancelRunRequest) -> dict[str, Any]:
    """Cancel an active Workbench run on the server side."""
    try:
        return _service(request).cancel_run(
            project_id=body.project_id,
            run_id=run_id,
            reason=body.reason,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workbench run not found") from exc


@router.post("/projects/{project_id}/runs/{run_id}/cancel")
async def cancel_project_run(
    project_id: str,
    run_id: str,
    request: Request,
    body: WorkbenchCancelRunRequest,
) -> dict[str, Any]:
    """Cancel an active Workbench run when the project id is already known."""
    try:
        return _service(request).cancel_run(
            project_id=project_id,
            run_id=run_id,
            reason=body.reason,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workbench run not found") from exc


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
    from builder.workbench_agent import build_default_agent_with_readiness

    service = _service(request)
    agent, execution = build_default_agent_with_readiness(force_mock=body.mock)

    async def event_generator() -> AsyncIterator[bytes]:
        try:
            stream = await service.run_build_stream(
                project_id=body.project_id,
                brief=body.brief,
                target=body.target,
                environment=body.environment,
                agent=agent,
                auto_iterate=body.auto_iterate,
                max_iterations=body.max_iterations,
                max_seconds=body.max_seconds,
                max_tokens=body.max_tokens,
                max_cost_usd=body.max_cost_usd,
                execution=execution,
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


@router.post("/build/iterate")
async def iterate_build(request: Request, body: WorkbenchIterateRequest) -> StreamingResponse:
    """Stream a follow-up iteration on an existing build as SSE.

    Delegates to ``WorkbenchService.run_iteration_stream()`` which reuses the
    current canonical model and generates delta artifacts.
    """
    from builder.workbench_agent import build_default_agent_with_readiness

    service = _service(request)
    agent, execution = build_default_agent_with_readiness(force_mock=body.mock)

    async def event_generator() -> AsyncIterator[bytes]:
        try:
            stream = await service.run_iteration_stream(
                project_id=body.project_id,
                follow_up=body.follow_up,
                target=body.target,
                environment=body.environment,
                agent=agent,
                max_iterations=body.max_iterations,
                max_seconds=body.max_seconds,
                max_tokens=body.max_tokens,
                max_cost_usd=body.max_cost_usd,
                execution=execution,
            )
            async for event in stream:
                yield _format_sse(
                    str(event.get("event") or "message"),
                    event.get("data") or {},
                )
        except KeyError:
            yield _format_sse("error", {"message": f"Project {body.project_id} not found"})
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
