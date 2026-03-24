"""Experiment card API endpoints."""

from __future__ import annotations

import dataclasses
from collections import Counter
from typing import Optional

from fastapi import APIRouter, Query, Request, HTTPException

router = APIRouter(prefix="/api/experiments", tags=["experiments"])


def _card_to_dict(card) -> dict:
    """Serialize an ExperimentCard dataclass to a JSON-safe dict."""
    return dataclasses.asdict(card)


@router.get("/stats")
async def get_experiment_stats(request: Request) -> dict:
    """Return experiment counts grouped by status."""
    store = getattr(request.app.state, "experiment_store", None)
    if store is None:
        return {"counts": {}}
    all_cards = store.get_all()
    counts = Counter(card.status for card in all_cards)
    return {"counts": dict(counts)}


@router.get("")
async def list_experiments(
    request: Request,
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=1000, description="Maximum results"),
) -> dict:
    """List recent experiments, optionally filtered by status."""
    store = getattr(request.app.state, "experiment_store", None)
    if store is None:
        return {"experiments": []}
    if status:
        cards = store.list_by_status(status=status, limit=limit)
    else:
        cards = store.list_recent(limit=limit)
    return {"experiments": [_card_to_dict(c) for c in cards]}


@router.get("/{experiment_id}")
async def get_experiment(
    experiment_id: str,
    request: Request,
) -> dict:
    """Get a single experiment card by ID."""
    store = getattr(request.app.state, "experiment_store", None)
    if store is None:
        raise HTTPException(status_code=404, detail="Experiment store not configured")
    card = store.get(experiment_id)
    if card is None:
        raise HTTPException(status_code=404, detail=f"Experiment not found: {experiment_id}")
    return _card_to_dict(card)
