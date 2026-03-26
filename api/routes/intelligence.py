"""Transcript intelligence routes for archive ingestion, analytics, and prompt-to-agent generation."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from optimizer.transcript_intelligence import TranscriptIntelligenceService

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


def _get_service(request: Request) -> TranscriptIntelligenceService:
    service = getattr(request.app.state, "transcript_intelligence_service", None)
    if service is None:
        service = TranscriptIntelligenceService()
        request.app.state.transcript_intelligence_service = service
    return service


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
        card, drafted_change_prompt = service.create_change_card_from_insight(
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
    }


@router.post("/build")
async def build_agent_from_prompt(body: BuildAgentRequest, request: Request) -> dict[str, Any]:
    service = _get_service(request)
    return service.build_agent_artifact(body.prompt, body.connectors)
