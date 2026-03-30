"""Experiment card API endpoints."""

from __future__ import annotations

import dataclasses
from collections import Counter
from typing import Any, Optional

from fastapi import APIRouter, Query, Request, HTTPException

from shared.experiment_store_adapter import experiment_card_to_record


router = APIRouter(prefix="/api/experiments", tags=["experiments"])


def _card_to_record_dict(card) -> dict:
    """Serialize an experiment card into the shared record payload."""
    return experiment_card_to_record(card).to_dict()


@router.get("/stats")
async def get_experiment_stats(request: Request) -> dict:
    """Return experiment counts grouped by status."""
    store = getattr(request.app.state, "experiment_store", None)
    if store is None:
        return {"counts": {}, "message": "Experiment store not configured"}
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
        return {"experiments": [], "message": "Experiment store not configured"}
    if status:
        cards = store.list_by_status(status=status, limit=limit)
    else:
        cards = store.list_recent(limit=limit)
    return {"experiments": [_card_to_record_dict(c) for c in cards]}


@router.get("/archive")
async def get_archive(request: Request) -> dict:
    """Return elite Pareto archive entries.

    Returns real archive data when configured.
    """
    archive_store = getattr(request.app.state, "archive_store", None)
    if archive_store is None:
        return {"entries": [], "message": "Archive store not configured"}
    entries = archive_store.get_all()
    return {"entries": [dataclasses.asdict(e) for e in entries]}


@router.get("/pareto")
async def get_pareto_frontier(request: Request) -> dict[str, Any]:
    """Return a UI-friendly Pareto frontier payload.

    WHY: The web UI consumes `ParetoFrontier` with `candidates`, `recommended`,
    `frontier_size`, and `infeasible_count`. The optimizer snapshot endpoint uses a
    different shape, so we normalize it here for `/api/experiments/pareto`.
    """
    optimizer = getattr(request.app.state, "optimizer", None)
    if optimizer is None:
        return {
            "candidates": [],
            "recommended": None,
            "frontier_size": 0,
            "infeasible_count": 0,
        }

    snapshot = optimizer.get_pareto_snapshot()
    objective_keys = list((snapshot.get("objective_directions") or {}).keys()) or [
        "quality",
        "safety",
        "latency",
        "cost",
    ]
    recommended_id = snapshot.get("recommended_candidate_id")

    def _to_candidate(item: dict[str, Any], constraints_passed: bool) -> dict[str, Any]:
        objectives = item.get("objectives", {})
        return {
            "candidate_id": item.get("candidate_id"),
            "objective_vector": [float(objectives.get(key, 0.0)) for key in objective_keys],
            "constraints_passed": constraints_passed,
            "constraint_violations": item.get("constraint_violations", []),
            "config_hash": item.get("config_hash"),
            "experiment_id": item.get("experiment_id"),
            "created_at": float(item.get("created_at", 0.0)),
            "dominated": bool(item.get("dominated", False)),
            "is_recommended": item.get("candidate_id") == recommended_id,
        }

    frontier_items = snapshot.get("frontier", [])
    infeasible_items = snapshot.get("infeasible", [])

    candidates = [
        *[_to_candidate(item, constraints_passed=True) for item in frontier_items],
        *[_to_candidate(item, constraints_passed=False) for item in infeasible_items],
    ]
    recommended = next((candidate for candidate in candidates if candidate["is_recommended"]), None)

    return {
        "candidates": candidates,
        "recommended": recommended,
        "frontier_size": len(frontier_items),
        "infeasible_count": len(infeasible_items),
    }


@router.get("/judge-calibration")
async def get_judge_calibration(request: Request) -> dict:
    """Return judge calibration metrics.

    Returns real calibration data when configured.
    """
    calibration_store = getattr(request.app.state, "judge_calibration", None)
    if calibration_store is None:
        return {
            "agreement_rate": 0.0,
            "drift": 0.0,
            "position_bias": 0.0,
            "verbosity_bias": 0.0,
            "disagreement_rate": 0.0,
            "message": "Judge calibration store not configured",
        }
    return dataclasses.asdict(calibration_store.get_latest())


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
    return _card_to_record_dict(card)
