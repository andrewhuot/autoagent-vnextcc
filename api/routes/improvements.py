"""Improvements API — unified view of optimizer proposals and their lineage.

An *improvement* is one optimizer-proposed change, keyed by ``attempt_id``.
This router joins data that already lives in the platform:

* :class:`OptimizationMemory` — the proposal, its config diff, and the
  accepted/rejected verdict.
* :class:`PendingReviewStore` — human-approval items awaiting review.
* :class:`ImprovementLineageStore` — deploy/rollback/measurement events after
  the proposal is accepted.

and exposes them under a single noun. See ``docs/GLOSSARY.md`` for the
terminology rationale — every existing "proposal", "opportunity", and "change
card" surfaces the same record through this API.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field


router = APIRouter(prefix="/api/improvements", tags=["improvements"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


ImprovementStatus = Literal[
    "proposed",
    "pending_review",
    "accepted",
    "rejected",
    "deployed_canary",
    "promoted",
    "rolled_back",
    "measured",
]


class LineageEventOut(BaseModel):
    event_id: str
    event_type: str
    timestamp: float
    version: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ImprovementRecord(BaseModel):
    attempt_id: str
    status: ImprovementStatus
    raw_status: str
    change_description: str
    config_section: str
    timestamp: float
    score_before: float | None = None
    score_after: float | None = None
    score_delta: float | None = None
    significance_p_value: float | None = None
    pending_review: bool = False
    deployed_version: int | None = None
    measurement: dict[str, Any] | None = None
    lineage: list[LineageEventOut] = Field(default_factory=list)
    rejection_reason: str | None = None


class ImprovementsResponse(BaseModel):
    total: int
    filtered: int
    items: list[ImprovementRecord]


class MeasureRequest(BaseModel):
    eval_run_id: str | None = None
    score_before: float | None = None
    score_after: float | None = None
    notes: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _classify(attempt_status: str, has_pending_review: bool, lineage_types: list[str]) -> ImprovementStatus:
    if "promote" in lineage_types:
        if "measurement" in lineage_types:
            return "measured"
        return "promoted"
    if "rollback" in lineage_types:
        return "rolled_back"
    if "deploy_canary" in lineage_types:
        return "deployed_canary"
    if has_pending_review:
        return "pending_review"
    if attempt_status.startswith("rejected"):
        return "rejected"
    if attempt_status == "accepted":
        return "accepted"
    return "proposed"


def _rejection_reason(status: str) -> str | None:
    if not status.startswith("rejected"):
        return None
    return status.replace("rejected_", "").replace("_", " ") or None


def _record_from(attempt: Any, lineage: list[Any], pending_ids: set[str]) -> ImprovementRecord:
    lineage_out = [
        LineageEventOut(
            event_id=ev.event_id,
            event_type=ev.event_type,
            timestamp=ev.timestamp,
            version=ev.version,
            payload=ev.payload,
        )
        for ev in lineage
    ]
    lineage_types = [ev.event_type for ev in lineage_out]
    status = _classify(attempt.status, attempt.attempt_id in pending_ids, lineage_types)

    deployed_version: int | None = None
    for ev in reversed(lineage_out):
        if ev.event_type in ("promote", "deploy_canary") and ev.version is not None:
            deployed_version = ev.version
            break

    measurement: dict[str, Any] | None = None
    for ev in reversed(lineage_out):
        if ev.event_type == "measurement":
            measurement = ev.payload
            break

    score_before = float(attempt.score_before) if attempt.score_before is not None else None
    score_after = float(attempt.score_after) if attempt.score_after is not None else None
    delta: float | None
    if score_before is not None and score_after is not None:
        delta = round(score_after - score_before, 4)
    else:
        delta = None

    return ImprovementRecord(
        attempt_id=attempt.attempt_id,
        status=status,
        raw_status=attempt.status,
        change_description=attempt.change_description or "",
        config_section=attempt.config_section or "",
        timestamp=float(attempt.timestamp),
        score_before=score_before,
        score_after=score_after,
        score_delta=delta,
        significance_p_value=(
            float(attempt.significance_p_value)
            if attempt.significance_p_value is not None
            else None
        ),
        pending_review=attempt.attempt_id in pending_ids,
        deployed_version=deployed_version,
        measurement=measurement,
        lineage=lineage_out,
        rejection_reason=_rejection_reason(attempt.status),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=ImprovementsResponse)
async def list_improvements(
    request: Request,
    status: ImprovementStatus | None = None,
    limit: int = 50,
) -> ImprovementsResponse:
    """List improvements, newest first. Filter by classified status when given."""
    memory = request.app.state.optimization_memory
    lineage = getattr(request.app.state, "improvement_lineage", None)
    pending_store = getattr(request.app.state, "pending_review_store", None)

    attempts = list(memory.get_all())
    attempts.sort(key=lambda a: a.timestamp, reverse=True)

    pending_ids: set[str] = set()
    if pending_store is not None:
        try:
            pending_ids = {r.attempt_id for r in pending_store.list_pending(limit=500)}
        except Exception:
            pending_ids = set()

    records: list[ImprovementRecord] = []
    for attempt in attempts:
        events = lineage.events_for(attempt.attempt_id) if lineage is not None else []
        records.append(_record_from(attempt, events, pending_ids))

    filtered = [r for r in records if status is None or r.status == status]
    return ImprovementsResponse(
        total=len(records),
        filtered=len(filtered),
        items=filtered[:limit],
    )


@router.get("/{attempt_id}", response_model=ImprovementRecord)
async def get_improvement(attempt_id: str, request: Request) -> ImprovementRecord:
    memory = request.app.state.optimization_memory
    lineage = getattr(request.app.state, "improvement_lineage", None)
    pending_store = getattr(request.app.state, "pending_review_store", None)

    for attempt in memory.get_all():
        if attempt.attempt_id == attempt_id:
            events = lineage.events_for(attempt_id) if lineage is not None else []
            pending_ids: set[str] = set()
            if pending_store is not None:
                try:
                    pending_ids = {
                        r.attempt_id for r in pending_store.list_pending(limit=500)
                    }
                except Exception:
                    pending_ids = set()
            return _record_from(attempt, events, pending_ids)
    raise HTTPException(status_code=404, detail=f"No improvement with attempt_id={attempt_id}")


@router.post("/{attempt_id}/measure", response_model=ImprovementRecord)
async def measure_improvement(
    attempt_id: str,
    body: MeasureRequest,
    request: Request,
) -> ImprovementRecord:
    """Record a post-deploy measurement against an improvement."""
    memory = request.app.state.optimization_memory
    lineage = getattr(request.app.state, "improvement_lineage", None)
    if lineage is None:
        raise HTTPException(status_code=500, detail="improvement_lineage not configured")

    # Verify attempt exists
    if not any(a.attempt_id == attempt_id for a in memory.get_all()):
        raise HTTPException(status_code=404, detail=f"No improvement with attempt_id={attempt_id}")

    delta: float | None
    if body.score_before is not None and body.score_after is not None:
        delta = body.score_after - body.score_before
    else:
        delta = None

    lineage.record(
        attempt_id,
        "measurement",
        payload={
            "eval_run_id": body.eval_run_id,
            "score_before": body.score_before,
            "score_after": body.score_after,
            "delta": delta,
            "notes": body.notes,
        },
    )
    return await get_improvement(attempt_id, request)
