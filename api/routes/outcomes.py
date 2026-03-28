"""Business-Outcome Joins API endpoints — P0-9."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request, UploadFile, File

router = APIRouter(prefix="/api/outcomes", tags=["outcomes"])


def _get_service(request: Request):
    """Retrieve the shared OutcomeService from app state."""
    service = getattr(request.app.state, "outcome_service", None)
    if service is None:
        from data.outcomes import OutcomeService
        service = OutcomeService()
        request.app.state.outcome_service = service
    return service


# ---------------------------------------------------------------------------
# Ingest single outcome
# ---------------------------------------------------------------------------

@router.post("")
async def ingest_outcome(
    request: Request,
    body: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Ingest a single business outcome and return the stored record."""
    service = _get_service(request)

    required = {"trace_id", "outcome_type", "outcome_value"}
    missing = required - set(body.keys())
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing required fields: {sorted(missing)}")

    try:
        outcome = service.ingest_outcome(
            trace_id=body["trace_id"],
            outcome_type=body["outcome_type"],
            value=float(body["outcome_value"]),
            source=body.get("source", ""),
            delay_hours=float(body.get("delay_hours", 0.0)),
            confidence=float(body.get("confidence", 1.0)),
            metadata=body.get("metadata", {}),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "outcome": outcome.to_dict()}


# ---------------------------------------------------------------------------
# Ingest batch
# ---------------------------------------------------------------------------

@router.post("/batch")
async def ingest_batch(
    request: Request,
    body: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Ingest a batch of outcome records. Body: {outcomes: [...]}"""
    service = _get_service(request)
    items = body.get("outcomes", [])
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="'outcomes' must be a list")
    count = service.ingest_batch(items)
    return {"ok": True, "ingested": count, "submitted": len(items)}


# ---------------------------------------------------------------------------
# Get outcomes for trace
# ---------------------------------------------------------------------------

@router.get("")
async def get_outcomes(
    request: Request,
    trace_id: str | None = Query(default=None),
    outcome_type: str | None = Query(default=None),
    since: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    """Query outcomes. If trace_id is provided, return outcomes for that trace."""
    service = _get_service(request)
    if trace_id:
        outcomes = service.store.get_outcomes_for_trace(trace_id)
    else:
        outcomes = service.store.query_outcomes(
            outcome_type=outcome_type, since=since, limit=limit
        )
    return {"outcomes": [o.to_dict() for o in outcomes], "count": len(outcomes)}


# ---------------------------------------------------------------------------
# Dashboard stats
# ---------------------------------------------------------------------------

@router.get("/stats")
async def get_stats(request: Request) -> dict[str, Any]:
    """Return aggregated outcome statistics for the dashboard."""
    service = _get_service(request)
    return service.dashboard_data()


# ---------------------------------------------------------------------------
# Webhook receiver
# ---------------------------------------------------------------------------

@router.post("/webhook")
async def webhook_receiver(
    request: Request,
    body: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Receive a business outcome via webhook and persist it."""
    service = _get_service(request)
    try:
        outcome = service.import_from_webhook(body)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "outcome_id": outcome.outcome_id}


# ---------------------------------------------------------------------------
# Import from CSV (file upload)
# ---------------------------------------------------------------------------

@router.post("/import/csv")
async def import_csv(
    request: Request,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Import outcomes from an uploaded CSV file."""
    service = _get_service(request)
    try:
        content = (await file.read()).decode("utf-8")
        count = service.import_from_csv_string(content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "imported": count}


# ---------------------------------------------------------------------------
# Recalibration triggers
# ---------------------------------------------------------------------------

@router.post("/recalibrate/judges")
async def recalibrate_judges(
    request: Request,
    body: dict[str, Any] = Body(default={}),
) -> dict[str, Any]:
    """Trigger judge recalibration and return calibration signals."""
    service = _get_service(request)
    judge_id = body.get("judge_id") if body else None
    signals = service.recalibrate_judges(judge_id=judge_id)
    return {
        "ok": True,
        "signals": [s.to_dict() for s in signals],
        "count": len(signals),
        "drifted": sum(1 for s in signals if s.drift_detected),
    }


@router.post("/recalibrate/skills")
async def recalibrate_skills(
    request: Request,
    body: dict[str, Any] = Body(default={}),
) -> dict[str, Any]:
    """Trigger skill calibration and return calibration signals."""
    service = _get_service(request)
    skill_name = body.get("skill_name") if body else None
    signals = service.recalibrate_skills(skill_name=skill_name)
    return {
        "ok": True,
        "signals": [s.to_dict() for s in signals],
        "count": len(signals),
        "misaligned": sum(1 for s in signals if s.misaligned),
    }


# ---------------------------------------------------------------------------
# Calibration signal reads
# ---------------------------------------------------------------------------

@router.get("/calibration/judges")
async def get_judge_calibration(
    request: Request,
    judge_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Return judge calibration signals, optionally filtered by judge_id."""
    service = _get_service(request)
    signals = service.store.get_judge_calibration_signals(judge_id=judge_id)
    return {
        "signals": [s.to_dict() for s in signals],
        "count": len(signals),
        "drifted": sum(1 for s in signals if s.drift_detected),
    }


@router.get("/calibration/skills")
async def get_skill_calibration(
    request: Request,
    skill_name: str | None = Query(default=None),
) -> dict[str, Any]:
    """Return skill calibration signals, optionally filtered by skill_name."""
    service = _get_service(request)
    signals = service.store.get_skill_calibration_signals(skill_name=skill_name)
    return {
        "signals": [s.to_dict() for s in signals],
        "count": len(signals),
        "misaligned": sum(1 for s in signals if s.misaligned),
    }
