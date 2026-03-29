"""Builder Workspace API routes."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from builder.chat_service import BuilderChatService
from builder.events import BuilderEventType, event_to_dict, serialize_sse_event
from builder.specialists import list_specialists
from builder.types import (
    ApprovalScope,
    ArtifactType,
    BuilderSession,
    ExecutionMode,
    PrivilegedAction,
    SpecialistRole,
    TaskStatus,
    now_ts,
)

router = APIRouter(prefix="/api/builder", tags=["builder"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class CreateProjectRequest(BaseModel):
    name: str
    description: str = ""
    root_path: str = "."
    master_instruction: str = ""


class UpdateProjectRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    root_path: str | None = None
    master_instruction: str | None = None
    knowledge_files: list[str] | None = None
    buildtime_skills: list[str] | None = None
    runtime_skills: list[str] | None = None
    deployment_targets: list[str] | None = None


class CreateSessionRequest(BaseModel):
    project_id: str
    title: str = ""
    mode: ExecutionMode = ExecutionMode.ASK


class CreateTaskRequest(BaseModel):
    session_id: str
    project_id: str
    title: str
    description: str
    mode: ExecutionMode = ExecutionMode.ASK


class TaskProgressRequest(BaseModel):
    progress: int = Field(ge=0, le=100)
    current_step: str
    tool_in_use: str = ""
    specialist_message: str | None = None


class ProposalRevisionRequest(BaseModel):
    comment: str


class ArtifactCommentRequest(BaseModel):
    author: str = "user"
    body: str


class ApprovalResponseRequest(BaseModel):
    approved: bool
    responder: str = "user"
    note: str = ""


class PermissionGrantRequest(BaseModel):
    project_id: str
    task_id: str | None = None
    action: PrivilegedAction
    scope: ApprovalScope


class SpecialistInvokeRequest(BaseModel):
    task_id: str
    message: str
    extra_context: dict[str, Any] | None = None


class BuilderChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None


class BuilderExportRequest(BaseModel):
    session_id: str
    format: str = "yaml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {key: _jsonable(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    return value


def _state(request: Request, name: str) -> Any:
    value = getattr(request.app.state, name, None)
    if value is None:
        raise HTTPException(status_code=500, detail=f"Builder service '{name}' is not configured")
    return value


def _chat_service(request: Request) -> BuilderChatService:
    service = getattr(request.app.state, "builder_chat_service", None)
    if service is None:
        service = BuilderChatService()
        request.app.state.builder_chat_service = service
    return service


# ---------------------------------------------------------------------------
# Conversational builder
# ---------------------------------------------------------------------------


@router.post("/chat")
async def builder_chat(request: Request, body: BuilderChatRequest) -> dict[str, Any]:
    service = _chat_service(request)
    return service.handle_message(message=body.message, session_id=body.session_id)


@router.get("/session/{session_id}")
async def get_builder_chat_session(request: Request, session_id: str) -> dict[str, Any]:
    service = _chat_service(request)
    session = service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Builder session not found")
    return session


@router.post("/export")
async def export_builder_chat_session(request: Request, body: BuilderExportRequest) -> dict[str, str]:
    service = _chat_service(request)
    export = service.export_session(session_id=body.session_id, format_name=body.format)
    if export is None:
        raise HTTPException(status_code=404, detail="Builder session not found")
    return export


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


@router.get("/projects")
async def list_projects(request: Request, archived: bool = False) -> list[dict[str, Any]]:
    manager = _state(request, "builder_project_manager")
    return [_jsonable(project) for project in manager.list_projects(archived=archived)]


@router.post("/projects")
async def create_project(request: Request, body: CreateProjectRequest) -> dict[str, Any]:
    manager = _state(request, "builder_project_manager")
    project = manager.create_project(
        name=body.name,
        description=body.description,
        root_path=body.root_path,
        master_instruction=body.master_instruction,
    )
    return _jsonable(project)


@router.get("/projects/{project_id}")
async def get_project(request: Request, project_id: str) -> dict[str, Any]:
    manager = _state(request, "builder_project_manager")
    project = manager.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return _jsonable(project)


@router.patch("/projects/{project_id}")
async def update_project(request: Request, project_id: str, body: UpdateProjectRequest) -> dict[str, Any]:
    manager = _state(request, "builder_project_manager")
    updates = body.model_dump(exclude_none=True)
    project = manager.update_project(project_id, **updates)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return _jsonable(project)


@router.delete("/projects/{project_id}")
async def delete_project(request: Request, project_id: str) -> dict[str, bool]:
    manager = _state(request, "builder_project_manager")
    return {"deleted": manager.delete_project(project_id)}


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


@router.get("/sessions")
async def list_sessions(request: Request, project_id: str | None = None) -> list[dict[str, Any]]:
    store = _state(request, "builder_store")
    sessions = store.list_sessions(project_id=project_id, limit=1000)
    return [_jsonable(session) for session in sessions]


@router.post("/sessions")
async def create_session(request: Request, body: CreateSessionRequest) -> dict[str, Any]:
    store = _state(request, "builder_store")
    orchestrator = _state(request, "builder_orchestrator")

    session = BuilderSession(
        project_id=body.project_id,
        title=body.title,
        mode=body.mode,
    )
    store.save_session(session)
    orchestrator.start_session(session)
    return _jsonable(session)


@router.get("/sessions/{session_id}")
async def get_session(request: Request, session_id: str) -> dict[str, Any]:
    store = _state(request, "builder_store")
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return _jsonable(session)


@router.post("/sessions/{session_id}/close")
async def close_session(request: Request, session_id: str) -> dict[str, Any]:
    store = _state(request, "builder_store")
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    session.status = "closed"
    session.closed_at = session.closed_at or now_ts()
    session.updated_at = now_ts()
    store.save_session(session)
    return _jsonable(session)


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@router.get("/tasks")
async def list_tasks(
    request: Request,
    session_id: str | None = None,
    project_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    store = _state(request, "builder_store")
    try:
        parsed_status = TaskStatus(status) if status else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid task status: {status}") from exc
    tasks = store.list_tasks(session_id=session_id, project_id=project_id, status=parsed_status, limit=1000)
    return [_jsonable(task) for task in tasks]


@router.post("/tasks")
async def create_task(request: Request, body: CreateTaskRequest) -> dict[str, Any]:
    engine = _state(request, "builder_execution")
    task = engine.create_task(
        session_id=body.session_id,
        project_id=body.project_id,
        title=body.title,
        description=body.description,
        mode=body.mode,
    )
    return _jsonable(task)


@router.get("/tasks/{task_id}")
async def get_task(request: Request, task_id: str) -> dict[str, Any]:
    store = _state(request, "builder_store")
    task = store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return _jsonable(task)


@router.post("/tasks/{task_id}/pause")
async def pause_task(request: Request, task_id: str) -> dict[str, Any]:
    engine = _state(request, "builder_execution")
    task = engine.pause_task(task_id, reason="paused_by_user")
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return _jsonable(task)


@router.post("/tasks/{task_id}/resume")
async def resume_task(request: Request, task_id: str) -> dict[str, Any]:
    engine = _state(request, "builder_execution")
    task = engine.resume_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return _jsonable(task)


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(request: Request, task_id: str) -> dict[str, Any]:
    engine = _state(request, "builder_execution")
    task = engine.cancel_task(task_id, reason="cancelled_by_user")
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return _jsonable(task)


@router.post("/tasks/{task_id}/duplicate")
async def duplicate_task(request: Request, task_id: str) -> dict[str, Any]:
    engine = _state(request, "builder_execution")
    task = engine.duplicate_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return _jsonable(task)


@router.post("/tasks/{task_id}/fork")
async def fork_task(request: Request, task_id: str, mode: ExecutionMode | None = None) -> dict[str, Any]:
    engine = _state(request, "builder_execution")
    task = engine.fork_task(task_id, mode=mode)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return _jsonable(task)


@router.post("/tasks/{task_id}/progress")
async def progress_task(request: Request, task_id: str, body: TaskProgressRequest) -> dict[str, Any]:
    engine = _state(request, "builder_execution")
    task = engine.progress_task(
        task_id,
        progress=body.progress,
        current_step=body.current_step,
        tool_in_use=body.tool_in_use,
        specialist_message=body.specialist_message,
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return _jsonable(task)


# ---------------------------------------------------------------------------
# Proposals
# ---------------------------------------------------------------------------


@router.get("/proposals")
async def list_proposals(request: Request, task_id: str | None = None) -> list[dict[str, Any]]:
    store = _state(request, "builder_store")
    proposals = store.list_proposals(task_id=task_id, limit=1000)
    return [_jsonable(proposal) for proposal in proposals]


@router.get("/proposals/{proposal_id}")
async def get_proposal(request: Request, proposal_id: str) -> dict[str, Any]:
    store = _state(request, "builder_store")
    proposal = store.get_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return _jsonable(proposal)


@router.post("/proposals/{proposal_id}/approve")
async def approve_proposal(request: Request, proposal_id: str) -> dict[str, Any]:
    store = _state(request, "builder_store")
    proposal = store.get_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    proposal.status = "approved"
    proposal.accepted = True
    proposal.rejected = False
    store.save_proposal(proposal)
    return _jsonable(proposal)


@router.post("/proposals/{proposal_id}/reject")
async def reject_proposal(request: Request, proposal_id: str) -> dict[str, Any]:
    store = _state(request, "builder_store")
    proposal = store.get_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    proposal.status = "rejected"
    proposal.accepted = False
    proposal.rejected = True
    store.save_proposal(proposal)
    return _jsonable(proposal)


@router.post("/proposals/{proposal_id}/revise")
async def revise_proposal(
    request: Request,
    proposal_id: str,
    body: ProposalRevisionRequest,
) -> dict[str, Any]:
    store = _state(request, "builder_store")
    proposal = store.get_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    proposal.status = "revision_requested"
    proposal.revision_count += 1
    proposal.revision_comments.append(body.comment)
    store.save_proposal(proposal)
    return _jsonable(proposal)


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------


@router.get("/artifacts")
async def list_artifacts(
    request: Request,
    task_id: str | None = None,
    session_id: str | None = None,
    artifact_type: ArtifactType | None = None,
) -> list[dict[str, Any]]:
    store = _state(request, "builder_store")
    artifacts = store.list_artifacts(task_id=task_id, session_id=session_id, artifact_type=artifact_type, limit=1000)
    return [_jsonable(artifact) for artifact in artifacts]


@router.get("/artifacts/{artifact_id}")
async def get_artifact(request: Request, artifact_id: str) -> dict[str, Any]:
    store = _state(request, "builder_store")
    artifact = store.get_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return _jsonable(artifact)


@router.post("/artifacts/{artifact_id}/comment")
async def comment_artifact(
    request: Request,
    artifact_id: str,
    body: ArtifactCommentRequest,
) -> dict[str, Any]:
    store = _state(request, "builder_store")
    artifact = store.get_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    artifact.comments.append({"author": body.author, "body": body.body})
    store.save_artifact(artifact)
    return _jsonable(artifact)


# ---------------------------------------------------------------------------
# Approvals and permissions
# ---------------------------------------------------------------------------


@router.get("/approvals")
async def list_approvals(
    request: Request,
    task_id: str | None = None,
    session_id: str | None = None,
) -> list[dict[str, Any]]:
    store = _state(request, "builder_store")
    approvals = store.list_approvals(task_id=task_id, session_id=session_id, limit=1000)
    return [_jsonable(approval) for approval in approvals]


@router.post("/approvals/{approval_id}/respond")
async def respond_approval(
    request: Request,
    approval_id: str,
    body: ApprovalResponseRequest,
) -> dict[str, Any]:
    permissions = _state(request, "builder_permissions")
    approval = permissions.respond(
        approval_id=approval_id,
        approved=body.approved,
        responder=body.responder,
        note=body.note,
    )
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    return _jsonable(approval)


@router.get("/permissions/grants")
async def list_permission_grants(
    request: Request,
    project_id: str | None = None,
    task_id: str | None = None,
) -> list[dict[str, Any]]:
    permissions = _state(request, "builder_permissions")
    grants = permissions.list_grants(project_id=project_id, task_id=task_id)
    return [_jsonable(grant) for grant in grants]


@router.post("/permissions/grants")
async def create_permission_grant(request: Request, body: PermissionGrantRequest) -> dict[str, Any]:
    permissions = _state(request, "builder_permissions")
    grant = permissions.create_grant(
        project_id=body.project_id,
        task_id=body.task_id,
        action=body.action,
        scope=body.scope,
    )
    return _jsonable(grant)


@router.delete("/permissions/grants/{grant_id}")
async def revoke_permission_grant(request: Request, grant_id: str) -> dict[str, bool]:
    permissions = _state(request, "builder_permissions")
    return {"revoked": permissions.revoke_grant(grant_id)}


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


@router.get("/events")
async def list_events(
    request: Request,
    session_id: str | None = None,
    task_id: str | None = None,
) -> list[dict[str, Any]]:
    broker = _state(request, "builder_events")
    return [event_to_dict(event) for event in broker.list_events(session_id=session_id, task_id=task_id)]


@router.get("/events/stream")
async def stream_events(
    request: Request,
    session_id: str | None = None,
    task_id: str | None = None,
    since: float | None = None,
) -> StreamingResponse:
    broker = _state(request, "builder_events")

    def event_stream() -> Any:
        emitted = False
        for event in broker.iter_events(session_id=session_id, task_id=task_id, since_timestamp=since):
            emitted = True
            yield serialize_sse_event(event)
        if not emitted:
            heartbeat = {
                "id": "heartbeat",
                "type": BuilderEventType.MESSAGE_DELTA.value,
                "session_id": session_id,
                "task_id": task_id,
                "timestamp": since,
                "payload": {"heartbeat": True},
            }
            yield f"event: heartbeat\ndata: {json.dumps(_jsonable(heartbeat))}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


@router.get("/metrics")
async def get_metrics(request: Request, project_id: str | None = None) -> dict[str, Any]:
    metrics = _state(request, "builder_metrics")
    return metrics.compute_dict(project_id=project_id)


# ---------------------------------------------------------------------------
# Specialists
# ---------------------------------------------------------------------------


@router.get("/specialists")
async def get_specialists() -> list[dict[str, Any]]:
    return [_jsonable(specialist) for specialist in list_specialists()]


@router.post("/specialists/{role}/invoke")
async def invoke_specialist(
    request: Request,
    role: SpecialistRole,
    body: SpecialistInvokeRequest,
) -> dict[str, Any]:
    store = _state(request, "builder_store")
    orchestrator = _state(request, "builder_orchestrator")
    task = store.get_task(body.task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    payload = orchestrator.invoke_specialist(
        task=task,
        message=body.message,
        explicit_role=role,
        extra_context=body.extra_context,
    )
    return _jsonable(payload)
