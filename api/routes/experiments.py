"""Experiment card API endpoints."""

from __future__ import annotations

import dataclasses
from collections import Counter
from typing import Optional

from fastapi import APIRouter, Query, Request, HTTPException

from api.models import ArchiveEntryResponse, JudgeCalibrationResponse

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


@router.get("/archive")
async def get_archive(request: Request) -> dict:
    """Return elite Pareto archive entries.

    Returns real archive data if an archive store is available, otherwise
    returns mock entries for frontend development.
    """
    archive_store = getattr(request.app.state, "archive_store", None)
    if archive_store is not None:
        entries = archive_store.get_all()
        return {"entries": [dataclasses.asdict(e) for e in entries]}

    # Mock data for development
    mock_entries: list[dict] = [
        {
            "entry_id": "arc_001",
            "role": "incumbent",
            "candidate_id": "cand_baseline_v12",
            "experiment_id": "exp_000",
            "objective_vector": [0.87, 0.95, 0.72, 0.81],
            "config_hash": "a1b2c3d4",
            "scores": {"quality": 0.87, "safety": 0.95, "latency": 0.72, "cost": 0.81},
            "created_at": "2026-03-20T10:00:00Z",
        },
        {
            "entry_id": "arc_002",
            "role": "quality_leader",
            "candidate_id": "cand_ql_v3",
            "experiment_id": "exp_042",
            "objective_vector": [0.94, 0.93, 0.65, 0.74],
            "config_hash": "e5f6g7h8",
            "scores": {"quality": 0.94, "safety": 0.93, "latency": 0.65, "cost": 0.74},
            "created_at": "2026-03-21T14:30:00Z",
        },
        {
            "entry_id": "arc_003",
            "role": "cost_leader",
            "candidate_id": "cand_cl_v2",
            "experiment_id": "exp_038",
            "objective_vector": [0.79, 0.91, 0.80, 0.93],
            "config_hash": "i9j0k1l2",
            "scores": {"quality": 0.79, "safety": 0.91, "latency": 0.80, "cost": 0.93},
            "created_at": "2026-03-22T09:15:00Z",
        },
        {
            "entry_id": "arc_004",
            "role": "latency_leader",
            "candidate_id": "cand_ll_v1",
            "experiment_id": "exp_045",
            "objective_vector": [0.82, 0.90, 0.95, 0.70],
            "config_hash": "m3n4o5p6",
            "scores": {"quality": 0.82, "safety": 0.90, "latency": 0.95, "cost": 0.70},
            "created_at": "2026-03-23T11:45:00Z",
        },
        {
            "entry_id": "arc_005",
            "role": "safety_leader",
            "candidate_id": "cand_sl_v2",
            "experiment_id": "exp_041",
            "objective_vector": [0.83, 0.99, 0.68, 0.77],
            "config_hash": "q7r8s9t0",
            "scores": {"quality": 0.83, "safety": 0.99, "latency": 0.68, "cost": 0.77},
            "created_at": "2026-03-23T16:00:00Z",
        },
    ]
    return {"entries": mock_entries}


@router.get("/judge-calibration")
async def get_judge_calibration(request: Request) -> dict:
    """Return judge calibration metrics.

    Returns real calibration data if available, otherwise returns mock data
    for frontend development.
    """
    calibration_store = getattr(request.app.state, "judge_calibration", None)
    if calibration_store is not None:
        return dataclasses.asdict(calibration_store.get_latest())

    # Mock data for development
    return {
        "agreement_rate": 0.82,
        "drift": 0.04,
        "position_bias": 0.03,
        "verbosity_bias": 0.06,
        "disagreement_rate": 0.18,
    }


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
