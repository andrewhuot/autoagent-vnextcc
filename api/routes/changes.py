"""Change card review API endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/changes", tags=["changes"])


def _get_store(request: Request):
    store = getattr(request.app.state, "change_card_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Change card store not configured")
    return store


def _sync_linked_experiment(
    request: Request,
    *,
    experiment_id: str,
    status: str,
    result_summary: str,
) -> bool:
    """Mirror review decisions so web and CLI experiment history stay consistent."""
    if not experiment_id:
        return False

    experiment_store = getattr(request.app.state, "experiment_store", None)
    if experiment_store is None or not hasattr(experiment_store, "update_status"):
        return False

    experiment_store.update_status(experiment_id, status, result_summary=result_summary)
    return True


def _promote_candidate_config(request: Request, candidate_version: int | None) -> bool:
    """Promote reviewable candidate configs when the API has version state available."""
    if candidate_version is None:
        return False

    version_manager = getattr(request.app.state, "version_manager", None)
    if version_manager is None or not hasattr(version_manager, "promote"):
        return False

    try:
        version_manager.promote(candidate_version)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return True


@router.get("")
@router.get("/")
async def list_change_cards(
    request: Request,
    status: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """List pending change cards (or all if status is specified)."""
    store = _get_store(request)
    normalized_status = (status or "").strip().lower()
    if normalized_status in {"", "pending"}:
        cards = store.list_pending(limit=limit)
    elif normalized_status == "all":
        cards = store.list_all(limit=limit)
    else:
        cards = [c for c in store.list_all(limit=limit) if c.status == normalized_status]
    return {
        "cards": [c.to_dict() for c in cards],
        "count": len(cards),
    }


@router.get("/audit-summary")
async def get_audit_summary(request: Request, limit: int = 100) -> dict[str, Any]:
    """Get aggregated accept/reject statistics.

    Returns:
        {
            "total_changes": int,
            "accepted": int,
            "rejected": int,
            "pending": int,
            "accept_rate": float,
            "top_rejection_reasons": [
                {"reason": "safety_regression", "count": 5},
                {"reason": "insufficient_significance", "count": 3},
                ...
            ],
            "avg_improvement_accepted": float,
            "gates_failure_breakdown": {
                "significance": 3,
                "safety": 2,
                "adversarial": 1
            }
        }
    """
    store = _get_store(request)
    all_cards = store.list_all(limit=limit)

    total = len(all_cards)
    accepted = len([c for c in all_cards if c.status == "applied"])
    rejected = len([c for c in all_cards if c.status == "rejected"])
    pending = len([c for c in all_cards if c.status == "pending"])

    accept_rate = accepted / total if total > 0 else 0.0

    # Analyze rejection reasons
    rejection_reasons: dict[str, int] = {}
    for card in all_cards:
        if card.status == "rejected" and card.rejection_reason:
            reason = card.rejection_reason
            rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1

    top_rejection_reasons = [
        {"reason": reason, "count": count}
        for reason, count in sorted(rejection_reasons.items(), key=lambda x: x[1], reverse=True)[:5]
    ]

    # Calculate average improvement for accepted changes
    accepted_cards = [c for c in all_cards if c.status == "applied"]
    avg_improvement = 0.0
    if accepted_cards:
        improvements = []
        for card in accepted_cards:
            # Try to get composite score delta
            if card.composite_breakdown:
                composite_before = sum(card.composite_breakdown.get("components", {}).values())
                composite_after = composite_before + sum(
                    card.dimension_breakdown.get(dim, {}).get("delta", 0)
                    for dim in card.dimension_breakdown
                )
                improvements.append(composite_after - composite_before)
        if improvements:
            avg_improvement = sum(improvements) / len(improvements)

    # Analyze gate failures
    gates_failure_breakdown: dict[str, int] = {}
    for card in all_cards:
        if card.status == "rejected":
            for gate_result in card.gate_results:
                if not gate_result.get("passed", True):
                    gate_name = gate_result.get("gate", "unknown")
                    gates_failure_breakdown[gate_name] = gates_failure_breakdown.get(gate_name, 0) + 1

    return {
        "total_changes": total,
        "accepted": accepted,
        "rejected": rejected,
        "pending": pending,
        "accept_rate": accept_rate,
        "top_rejection_reasons": top_rejection_reasons,
        "avg_improvement_accepted": avg_improvement,
        "gates_failure_breakdown": gates_failure_breakdown,
    }


@router.get("/{card_id}")
async def get_change_card(card_id: str, request: Request) -> dict[str, Any]:
    """Get a specific change card by ID."""
    store = _get_store(request)
    card = store.get(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail=f"Change card not found: {card_id}")
    return {"card": card.to_dict()}


@router.post("/{card_id}/apply")
async def apply_change_card(card_id: str, request: Request) -> dict[str, Any]:
    """Apply (accept) a change card."""
    store = _get_store(request)
    card = store.get(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail=f"Change card not found: {card_id}")
    if card.status != "pending":
        raise HTTPException(status_code=400, detail=f"Card is not pending (status={card.status})")
    candidate_promoted = _promote_candidate_config(request, card.candidate_config_version)
    ok = store.update_status(card_id, "applied")
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to update card status")
    experiment_synced = _sync_linked_experiment(
        request,
        experiment_id=card.experiment_card_id,
        status="accepted",
        result_summary=f"Accepted from change card {card_id}",
    )
    return {
        "card_id": card_id,
        "status": "applied",
        "message": "Change card applied",
        "experiment_synced": experiment_synced,
        "candidate_promoted": candidate_promoted,
    }


@router.post("/{card_id}/reject")
async def reject_change_card(card_id: str, request: Request) -> dict[str, Any]:
    """Reject a change card with an optional reason."""
    store = _get_store(request)
    card = store.get(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail=f"Change card not found: {card_id}")
    if card.status != "pending":
        raise HTTPException(status_code=400, detail=f"Card is not pending (status={card.status})")

    body = await request.json() if request.headers.get("content-length", "0") != "0" else {}
    reason = body.get("reason", "")

    ok = store.update_status(card_id, "rejected", reason=reason)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to update card status")
    experiment_synced = _sync_linked_experiment(
        request,
        experiment_id=card.experiment_card_id,
        status="rejected",
        result_summary=f"Rejected from change card {card_id}: {reason}".strip(),
    )
    return {
        "card_id": card_id,
        "status": "rejected",
        "message": "Change card rejected",
        "reason": reason,
        "experiment_synced": experiment_synced,
    }


@router.patch("/{card_id}/hunks")
async def update_hunk_status(card_id: str, request: Request) -> dict[str, Any]:
    """Accept or reject individual diff hunks within a change card."""
    store = _get_store(request)
    card = store.get(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail=f"Change card not found: {card_id}")

    body = await request.json()
    updates = body.get("updates", [])
    results = []
    for update in updates:
        hunk_id = update.get("hunk_id")
        hunk_status = update.get("status")
        if not hunk_id or not hunk_status:
            results.append({"hunk_id": hunk_id, "ok": False, "error": "hunk_id and status required"})
            continue
        ok = store.update_hunk_status(card_id, hunk_id, hunk_status)
        results.append({"hunk_id": hunk_id, "ok": ok})
    return {"card_id": card_id, "results": results}


@router.get("/{card_id}/export")
async def export_change_card(card_id: str, request: Request) -> dict[str, Any]:
    """Export a change card as markdown."""
    store = _get_store(request)
    card = store.get(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail=f"Change card not found: {card_id}")
    return {"card_id": card_id, "markdown": card.to_markdown()}


# ---------------------------------------------------------------------------
# Audit trail endpoints (Feature 3)
# ---------------------------------------------------------------------------

@router.get("/{card_id}/audit")
async def get_change_audit(card_id: str, request: Request) -> dict[str, Any]:
    """Get full audit trail for a change card.

    Returns comprehensive accept/reject decision details:
    - Per-dimension score deltas (safety: +0.05, quality: +0.12, latency: -0.3s)
    - Gate decisions with reasons (which gates passed/failed and why)
    - Adversarial simulation results (if run)
    - Composite score breakdown (weighted contributions)
    - Timeline of the optimization attempt

    Returns:
        {
            "card_id": str,
            "status": str,  # "pending", "applied", "rejected"
            "dimension_breakdown": {
                "safety": {"before": 0.85, "after": 0.90, "delta": +0.05},
                "quality": {"before": 0.75, "after": 0.87, "delta": +0.12},
                ...
            },
            "gate_results": [
                {"gate": "significance", "passed": true, "reason": "p=0.01 < 0.05"},
                {"gate": "safety", "passed": true, "reason": "No safety regression"},
                ...
            ],
            "adversarial_results": {
                "passed": true,
                "score_drop": 0.02,
                "num_cases": 20
            },
            "composite_breakdown": {
                "weights": {"safety": 0.4, "quality": 0.4, "latency": 0.2},
                "components": {"safety": 0.90, "quality": 0.87, "latency": 0.75},
                "contributions": {"safety": 0.36, "quality": 0.348, "latency": 0.15}
            },
            "timeline": [
                {"phase": "proposed", "timestamp": 123456.0, "status": "pending"},
                {"phase": "evaluated", "timestamp": 123457.0, "status": "in_progress"},
                {"phase": "gated", "timestamp": 123458.0, "status": "passed"},
                {"phase": "accepted", "timestamp": 123459.0, "status": "applied"}
            ]
        }
    """
    store = _get_store(request)
    card = store.get(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail=f"Change card not found: {card_id}")

    return {
        "card_id": card_id,
        "status": card.status,
        "dimension_breakdown": card.dimension_breakdown,
        "gate_results": card.gate_results,
        "adversarial_results": card.adversarial_results,
        "composite_breakdown": card.composite_breakdown,
        "timeline": card.timeline,
        "rejection_reason": card.rejection_reason if card.status == "rejected" else None,
    }
