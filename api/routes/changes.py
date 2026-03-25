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


@router.get("/")
async def list_change_cards(
    request: Request,
    status: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """List pending change cards (or all if status is specified)."""
    store = _get_store(request)
    if status == "pending":
        cards = store.list_pending(limit=limit)
    elif status is not None:
        cards = [c for c in store.list_all(limit=limit) if c.status == status]
    else:
        cards = store.list_pending(limit=limit)
    return {
        "cards": [c.to_dict() for c in cards],
        "count": len(cards),
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
    ok = store.update_status(card_id, "applied")
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to update card status")
    return {"card_id": card_id, "status": "applied"}


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
    return {"card_id": card_id, "status": "rejected", "reason": reason}


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
