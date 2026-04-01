"""Transcript intelligence routes for archive ingestion, analytics, and prompt-to-agent generation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
import yaml

from builder.workspace_config import persist_generated_config, preview_generated_config
from cli.mode import load_runtime_with_builder_live_preference
from optimizer.providers import build_router_from_runtime_config
from optimizer.transcript_intelligence import TranscriptIntelligenceService
from shared.build_artifact_store import BuildArtifactStore
from shared.contracts import BuildArtifact
from shared.transcript_report_store import TranscriptReportStore

router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])


class ArchiveImportRequest(BaseModel):
    archive_name: str = Field(..., min_length=1)
    archive_base64: str = Field(..., min_length=1)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)


class ApplyInsightRequest(BaseModel):
    insight_id: str = Field(..., min_length=1)


class BuildAgentRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    connectors: list[str] = Field(default_factory=list)


class GenerateAgentRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    transcript_report_id: str | None = Field(None)
    instruction_xml: str | None = Field(None)
    requested_model: str | None = Field(None)
    requested_agent_name: str | None = Field(None)
    tool_hints: list[str] = Field(default_factory=list)


class ChatRefineRequest(BaseModel):
    message: str = Field(..., min_length=1)
    config: dict = Field(...)


class SaveGeneratedAgentRequest(BaseModel):
    config: dict = Field(...)
    source: str = Field("prompt")
    prompt_used: str | None = Field(None)
    transcript_report_id: str | None = Field(None)
    builder_session_id: str | None = Field(None)


class PreviewGeneratedAgentRequest(BaseModel):
    message: str = Field(..., min_length=1)
    config: dict = Field(...)


class DeepResearchRequest(BaseModel):
    question: str = Field(..., min_length=1)


class AutonomousLoopRequest(BaseModel):
    auto_ship: bool = Field(False, description="Whether to auto-deploy canary when sandbox validation passes")


def _get_service(request: Request) -> TranscriptIntelligenceService:
    service = getattr(request.app.state, "transcript_intelligence_service", None)
    if service is None:
        proposer = getattr(request.app.state, "proposer", None)
        llm_router = getattr(proposer, "llm_router", None)
        if llm_router is None:
            runtime_config = getattr(request.app.state, "runtime_config", None)
            if runtime_config is not None:
                try:
                    builder_runtime = load_runtime_with_builder_live_preference()
                    llm_router = build_router_from_runtime_config(builder_runtime.optimizer)
                except Exception:
                    llm_router = None
        report_store = getattr(request.app.state, "transcript_report_store", None)
        if report_store is None:
            report_store = TranscriptReportStore()
            request.app.state.transcript_report_store = report_store
        service = TranscriptIntelligenceService(llm_router=llm_router, report_store=report_store)
        request.app.state.transcript_intelligence_service = service
    return service


def _get_build_artifact_store(request: Request) -> BuildArtifactStore:
    store = getattr(request.app.state, "build_artifact_store", None)
    if store is None:
        store = BuildArtifactStore()
        request.app.state.build_artifact_store = store
    return store


def _artifact_title(prompt: str, fallback: str = "Build Artifact") -> str:
    prompt_summary = " ".join(prompt.split())
    if not prompt_summary:
        return fallback
    if len(prompt_summary) <= 72:
        return prompt_summary
    return f"{prompt_summary[:69]}..."


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


@router.post("/archive", status_code=201)
async def import_transcript_archive(body: ArchiveImportRequest, request: Request) -> dict[str, Any]:
    service = _get_service(request)
    try:
        report = service.import_archive(body.archive_name, body.archive_base64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Archive import failed: {exc}")
    return report.to_dict()


@router.get("/reports")
async def list_reports(request: Request) -> dict[str, Any]:
    service = _get_service(request)
    return {"reports": service.list_reports()}


@router.get("/reports/{report_id}")
async def get_report(report_id: str, request: Request) -> dict[str, Any]:
    service = _get_service(request)
    report = service.get_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"Unknown report: {report_id}")
    return report.to_dict()


@router.post("/reports/{report_id}/ask")
async def ask_report(report_id: str, body: AskRequest, request: Request) -> dict[str, Any]:
    service = _get_service(request)
    try:
        return service.ask_report(report_id, body.question)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/reports/{report_id}/apply", status_code=201)
async def apply_insight(report_id: str, body: ApplyInsightRequest, request: Request) -> dict[str, Any]:
    service = _get_service(request)
    deployer = request.app.state.deployer
    eval_runner = request.app.state.eval_runner
    change_card_store = request.app.state.change_card_store
    current_config = deployer.get_active_config() or {}

    try:
        card, drafted_change_prompt, auto_simulation = service.create_change_card_from_insight(
            report_id=report_id,
            insight_id=body.insight_id,
            current_config=current_config,
            eval_runner=eval_runner,
            change_card_store=change_card_store,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {
        "status": "pending_review",
        "drafted_change_prompt": drafted_change_prompt,
        "change_card": card.to_dict(),
        "auto_simulation": auto_simulation,
    }


@router.post("/build")
async def build_agent_from_prompt(body: BuildAgentRequest, request: Request) -> dict[str, Any]:
    service = _get_service(request)
    artifact = service.build_agent_artifact(body.prompt, body.connectors)
    build_artifact_store = _get_build_artifact_store(request)
    now_iso = _now_iso()
    build_artifact_store.save_latest(
        BuildArtifact(
            id=f"build-{uuid.uuid4().hex[:12]}",
            created_at=now_iso,
            updated_at=now_iso,
            source="prompt",
            status="draft",
            config_yaml="",
            prompt_used=body.prompt,
            selector="latest",
            metadata={
                "title": _artifact_title(body.prompt, "Prompt Build"),
                "summary": "Prompt build draft generated in the Build workspace.",
                "connectors": artifact.get("connectors", []),
                "intents": artifact.get("intents", []),
                "tools": artifact.get("tools", []),
                "guardrails": artifact.get("guardrails", []),
                "skills": artifact.get("skills", []),
                "integration_templates": artifact.get("integration_templates", []),
                "legacy_payload": artifact,
            },
        ),
        legacy_payload=artifact,
    )
    return artifact


@router.post("/generate-agent")
async def generate_agent(body: GenerateAgentRequest, request: Request) -> dict[str, Any]:
    service = _get_service(request)
    generated = service.generate_agent_config(
        body.prompt,
        body.transcript_report_id,
        instruction_xml=body.instruction_xml,
        requested_model=body.requested_model,
        requested_agent_name=body.requested_agent_name,
        tool_hints=body.tool_hints,
    )
    config_yaml = yaml.safe_dump(generated, sort_keys=False)
    source = "transcript" if body.transcript_report_id else "prompt"
    build_artifact_store = _get_build_artifact_store(request)
    now_iso = _now_iso()
    build_artifact_store.save_latest(
        BuildArtifact(
            id=f"build-{uuid.uuid4().hex[:12]}",
            created_at=now_iso,
            updated_at=now_iso,
            source=source,
            status="complete",
            config_yaml=config_yaml,
            prompt_used=body.prompt,
            transcript_report_id=body.transcript_report_id,
            selector="latest",
            metadata={
                "title": generated.get("metadata", {}).get("agent_name") or _artifact_title(body.prompt),
                "summary": (
                    "Transcript-informed agent config generated in the Build workspace."
                    if body.transcript_report_id
                    else "Prompt-generated agent config saved from the Build workspace."
                ),
                "generated_config": generated,
            },
        )
    )
    return generated


@router.post("/chat")
async def chat_refine(body: ChatRefineRequest, request: Request) -> dict[str, Any]:
    service = _get_service(request)
    return service.chat_refine(body.message, body.config)


@router.post("/save-agent")
async def save_generated_agent(body: SaveGeneratedAgentRequest, request: Request) -> dict[str, Any]:
    build_artifact_store = _get_build_artifact_store(request)
    try:
        saved = persist_generated_config(
            body.config,
            artifact_store=build_artifact_store,
            source=body.source,
            source_prompt=body.prompt_used,
            transcript_report_id=body.transcript_report_id,
            builder_session_id=body.builder_session_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return saved.to_dict()


@router.post("/preview-agent")
async def preview_generated_agent_route(body: PreviewGeneratedAgentRequest) -> dict[str, Any]:
    try:
        preview = preview_generated_config(body.config, body.message)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return preview.to_dict()


@router.get("/knowledge/{asset_id}")
async def get_knowledge_asset(asset_id: str, request: Request) -> dict[str, Any]:
    service = _get_service(request)
    asset = service.get_knowledge_asset(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Unknown knowledge asset: {asset_id}")
    return asset


@router.post("/reports/{report_id}/deep-research")
async def deep_research_report(
    report_id: str,
    body: DeepResearchRequest,
    request: Request,
) -> dict[str, Any]:
    service = _get_service(request)
    try:
        return service.deep_research(report_id=report_id, question=body.question)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/reports/{report_id}/autonomous-loop")
async def run_autonomous_loop(
    report_id: str,
    body: AutonomousLoopRequest,
    request: Request,
) -> dict[str, Any]:
    service = _get_service(request)
    deployer = getattr(request.app.state, "deployer", None)
    eval_runner = request.app.state.eval_runner
    change_card_store = request.app.state.change_card_store
    current_config = deployer.get_active_config() if deployer is not None else {}
    current_config = current_config or {}

    try:
        return service.run_autonomous_cycle(
            report_id=report_id,
            eval_runner=eval_runner,
            change_card_store=change_card_store,
            current_config=current_config,
            auto_ship=body.auto_ship,
            deployer=deployer,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/build-artifacts")
async def list_build_artifacts(request: Request, limit: int = 50) -> dict[str, Any]:
    store = _get_build_artifact_store(request)
    return {"artifacts": store.list_recent(limit=limit)}


@router.get("/build-artifacts/{artifact_id}")
async def get_build_artifact(artifact_id: str, request: Request) -> dict[str, Any]:
    store = _get_build_artifact_store(request)
    artifact = store.get_by_id(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail=f"Unknown build artifact: {artifact_id}")
    return artifact
