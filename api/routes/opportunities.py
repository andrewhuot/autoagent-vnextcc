"""Opportunity queue API endpoints."""

from __future__ import annotations

import dataclasses

from fastapi import APIRouter, Query, Request, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

router = APIRouter(prefix="/api/opportunities", tags=["opportunities"])


def _opportunity_to_dict(opp) -> dict:
    """Serialize an OptimizationOpportunity dataclass to a JSON-safe dict."""
    return dataclasses.asdict(opp)


class UpdateStatusBody(BaseModel):
    """Request body for updating opportunity status."""
    status: str = Field(..., description="New status: open, in_progress, resolved, wont_fix")
    resolution_experiment_id: Optional[str] = Field(None, description="Linked experiment ID")


@router.get("/count")
async def get_opportunity_count(request: Request) -> dict:
    """Return the count of open opportunities."""
    queue = getattr(request.app.state, "opportunity_queue", None)
    if queue is None:
        return {"open": 0}
    return {"open": queue.count_open()}


@router.get("")
async def list_opportunities(
    request: Request,
    status: str = Query("open", description="Filter by status"),
    limit: int = Query(50, ge=1, le=1000, description="Maximum results"),
) -> dict:
    """List opportunities sorted by priority."""
    queue = getattr(request.app.state, "opportunity_queue", None)
    if queue is None:
        return {"opportunities": []}
    if status == "open":
        opportunities = queue.list_open(limit=limit)
    else:
        # list_all and filter by status
        all_opps = queue.list_all(limit=limit * 2)
        opportunities = [o for o in all_opps if o.status == status][:limit]
    return {"opportunities": [_opportunity_to_dict(o) for o in opportunities]}


@router.get("/{opportunity_id}")
async def get_opportunity(
    opportunity_id: str,
    request: Request,
) -> dict:
    """Get a single opportunity by ID."""
    queue = getattr(request.app.state, "opportunity_queue", None)
    if queue is None:
        raise HTTPException(status_code=404, detail="Opportunity queue not configured")
    opp = queue.get(opportunity_id)
    if opp is None:
        raise HTTPException(status_code=404, detail=f"Opportunity not found: {opportunity_id}")
    return _opportunity_to_dict(opp)


@router.post("/{opportunity_id}/status")
async def update_opportunity_status(
    opportunity_id: str,
    body: UpdateStatusBody,
    request: Request,
) -> dict:
    """Update the status of an opportunity."""
    queue = getattr(request.app.state, "opportunity_queue", None)
    if queue is None:
        raise HTTPException(status_code=404, detail="Opportunity queue not configured")
    opp = queue.get(opportunity_id)
    if opp is None:
        raise HTTPException(status_code=404, detail=f"Opportunity not found: {opportunity_id}")
    try:
        queue.update_status(
            opportunity_id=opportunity_id,
            status=body.status,
            resolution_experiment_id=body.resolution_experiment_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"opportunity_id": opportunity_id, "status": body.status}
