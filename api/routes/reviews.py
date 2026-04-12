"""Unified review surface — aggregates PendingReviewStore and ChangeCardStore.

This module provides a single API for operators to see and act on all pending
review items regardless of which pipeline produced them.  The underlying stores
are not merged — this is a read-through aggregation layer that normalizes both
sources into ``UnifiedReviewItem`` records.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from api.models import (
    UnifiedReviewActionRequest,
    UnifiedReviewActionResponse,
    UnifiedReviewItem,
    UnifiedReviewStats,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


# ---------------------------------------------------------------------------
# Helpers — translate store-specific records to the unified shape
# ---------------------------------------------------------------------------


def _pending_review_to_unified(review: Any) -> UnifiedReviewItem:
    """Map a PendingReview (from the optimizer pipeline) to UnifiedReviewItem."""

    # Handle both Pydantic models and plain dicts
    if hasattr(review, "model_dump"):
        data = review.model_dump(mode="python")
    elif isinstance(review, dict):
        data = review
    else:
        data = vars(review)

    created_at = data.get("created_at")
    if isinstance(created_at, str):
        try:
            created_at = datetime.fromisoformat(created_at)
        except (ValueError, TypeError):
            created_at = datetime.now(timezone.utc)
    elif not isinstance(created_at, datetime):
        created_at = datetime.now(timezone.utc)

    score_before = float(data.get("score_before", 0.0))
    score_after = float(data.get("score_after", 0.0))

    return UnifiedReviewItem(
        id=data.get("attempt_id", ""),
        source="optimizer",
        status="pending",
        title=data.get("change_description", "Optimizer proposal"),
        description=data.get("reasoning", ""),
        score_before=score_before,
        score_after=score_after,
        score_delta=round(score_after - score_before, 6),
        risk_class="medium",
        diff_summary=data.get("config_diff", ""),
        created_at=created_at,
        strategy=data.get("strategy"),
        operator_family=data.get("selected_operator_family"),
        has_detailed_audit=False,
        patch_bundle=data.get("patch_bundle"),
    )


def _render_hunks_as_diff(hunks: list[dict[str, Any]]) -> str:
    """Render change card diff hunks as a readable summary."""

    lines: list[str] = []
    for hunk in hunks:
        surface = hunk.get("surface", "unknown")
        old_val = hunk.get("old_value", "")
        new_val = hunk.get("new_value", "")
        lines.append(f"--- {surface}")
        lines.append(f"+++ {surface}")
        if old_val:
            for line in old_val.splitlines():
                lines.append(f"-{line}")
        if new_val:
            for line in new_val.splitlines():
                lines.append(f"+{line}")
    return "\n".join(lines)


def _change_card_to_unified(card: Any) -> UnifiedReviewItem:
    """Map a ProposedChangeCard (from the intelligence/experiment pipeline) to UnifiedReviewItem."""

    if hasattr(card, "to_dict"):
        data = card.to_dict()
    elif isinstance(card, dict):
        data = card
    else:
        data = vars(card)

    # Compute a composite score from metrics_before / metrics_after
    metrics_before = data.get("metrics_before", {})
    metrics_after = data.get("metrics_after", {})

    score_before = 0.0
    score_after = 0.0
    if metrics_before:
        score_before = sum(metrics_before.values()) / len(metrics_before)
    if metrics_after:
        score_after = sum(metrics_after.values()) / len(metrics_after)

    # Map status: change cards use "applied" instead of "approved"
    raw_status = data.get("status", "pending")
    status = raw_status if raw_status != "applied" else "approved"

    # Parse created_at from epoch float
    created_at_raw = data.get("created_at", 0)
    if isinstance(created_at_raw, (int, float)) and created_at_raw > 0:
        created_at = datetime.fromtimestamp(created_at_raw, tz=timezone.utc)
    elif isinstance(created_at_raw, str):
        try:
            created_at = datetime.fromisoformat(created_at_raw)
        except (ValueError, TypeError):
            created_at = datetime.now(timezone.utc)
    else:
        created_at = datetime.now(timezone.utc)

    # Render diff from hunks
    hunks = data.get("diff_hunks", [])
    diff_summary = _render_hunks_as_diff(hunks) if hunks else ""

    return UnifiedReviewItem(
        id=data.get("card_id", ""),
        source="change_card",
        status=status,
        title=data.get("title", "Change card"),
        description=data.get("why", ""),
        score_before=round(score_before, 6),
        score_after=round(score_after, 6),
        score_delta=round(score_after - score_before, 6),
        risk_class=data.get("risk_class", "low"),
        diff_summary=diff_summary,
        created_at=created_at,
        strategy=None,
        operator_family=None,
        has_detailed_audit=True,
        patch_bundle=data.get("patch_bundle"),
    )


# ---------------------------------------------------------------------------
# Store accessors (safe against missing stores)
# ---------------------------------------------------------------------------


def _get_pending_review_store(request: Request):
    return getattr(request.app.state, "pending_review_store", None)


def _get_change_card_store(request: Request):
    return getattr(request.app.state, "change_card_store", None)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/pending")
async def list_pending_reviews(request: Request, limit: int = 50) -> list[UnifiedReviewItem]:
    """Return all pending review items from both stores, sorted newest first."""

    items: list[UnifiedReviewItem] = []

    # Optimizer pending reviews
    pr_store = _get_pending_review_store(request)
    if pr_store is not None:
        try:
            for review in pr_store.list_pending(limit=limit):
                items.append(_pending_review_to_unified(review))
        except Exception as e:
            logger.error("Failed to read from PendingReviewStore: %s", e)

    # Change card pending reviews
    cc_store = _get_change_card_store(request)
    if cc_store is not None:
        try:
            for card in cc_store.list_pending(limit=limit):
                items.append(_change_card_to_unified(card))
        except Exception as e:
            logger.error("Failed to read from ChangeCardStore: %s", e)

    # Sort by created_at descending (newest first)
    items.sort(key=lambda item: item.created_at, reverse=True)
    return items[:limit]


@router.get("/all")
async def list_all_reviews(
    request: Request,
    status: str | None = None,
    limit: int = 100,
) -> list[UnifiedReviewItem]:
    """Return all review items from both stores, optionally filtered by status."""

    items: list[UnifiedReviewItem] = []

    # Optimizer pending reviews (PendingReviewStore only holds pending items)
    pr_store = _get_pending_review_store(request)
    if pr_store is not None:
        try:
            for review in pr_store.list_pending(limit=limit):
                items.append(_pending_review_to_unified(review))
        except Exception as e:
            logger.error("Failed to read from PendingReviewStore: %s", e)

    # Change card reviews (all statuses)
    cc_store = _get_change_card_store(request)
    if cc_store is not None:
        try:
            for card in cc_store.list_all(limit=limit):
                items.append(_change_card_to_unified(card))
        except Exception as e:
            logger.error("Failed to read from ChangeCardStore: %s", e)

    # Filter by status if requested
    if status:
        normalized = status.strip().lower()
        if normalized != "all":
            items = [item for item in items if item.status == normalized]

    items.sort(key=lambda item: item.created_at, reverse=True)
    return items[:limit]


@router.get("/stats")
async def get_review_stats(request: Request) -> UnifiedReviewStats:
    """Return aggregate counts across both review stores."""

    optimizer_pending = 0
    change_card_pending = 0
    total_approved = 0
    total_rejected = 0

    pr_store = _get_pending_review_store(request)
    if pr_store is not None:
        try:
            optimizer_pending = len(pr_store.list_pending(limit=500))
        except Exception as e:
            logger.error("Failed to count optimizer pending reviews: %s", e)

    cc_store = _get_change_card_store(request)
    if cc_store is not None:
        try:
            all_cards = cc_store.list_all(limit=500)
            for card in all_cards:
                card_status = card.status if hasattr(card, "status") else card.get("status", "")
                if card_status == "pending":
                    change_card_pending += 1
                elif card_status == "applied":
                    total_approved += 1
                elif card_status == "rejected":
                    total_rejected += 1
        except Exception as e:
            logger.error("Failed to count change card reviews: %s", e)

    return UnifiedReviewStats(
        total_pending=optimizer_pending + change_card_pending,
        optimizer_pending=optimizer_pending,
        change_card_pending=change_card_pending,
        total_approved=total_approved,
        total_rejected=total_rejected,
    )


@router.post("/{item_id}/approve")
async def approve_review(
    item_id: str,
    request: Request,
    body: UnifiedReviewActionRequest | None = None,
) -> UnifiedReviewActionResponse:
    """Approve a review item, dispatching to the correct underlying store."""

    if body is None:
        raise HTTPException(status_code=400, detail="Request body with 'source' field is required")

    source = body.source.strip().lower()

    if source == "optimizer":
        pr_store = _get_pending_review_store(request)
        if pr_store is None:
            raise HTTPException(status_code=503, detail="Pending review store not configured")

        raw_review = pr_store.get_review(item_id)
        if raw_review is None:
            raise HTTPException(status_code=404, detail=f"Pending review not found: {item_id}")

        # Deploy the approved config — only remove from store after successful deploy
        deployer = getattr(request.app.state, "deployer", None)
        memory = getattr(request.app.state, "optimization_memory", None)

        deploy_message = None
        if deployer is not None:
            data = raw_review.model_dump(mode="python") if hasattr(raw_review, "model_dump") else raw_review
            proposed = data.get("proposed_config", {})
            scores = data.get("deploy_scores", {})
            strategy = data.get("deploy_strategy", "immediate")
            try:
                deploy_message = deployer.deploy(proposed, scores, strategy=strategy)
            except Exception as e:
                logger.error("Deploy failed for review %s: %s", item_id, e)
                raise HTTPException(
                    status_code=502,
                    detail=f"Approval accepted but deploy failed: {e}. Review kept for retry.",
                )

        pr_store.delete_review(item_id)

        # Update optimization memory
        if memory is not None and hasattr(memory, "get_all") and hasattr(memory, "log"):
            for attempt in memory.get_all():
                if attempt.attempt_id == item_id:
                    attempt.status = "accepted"
                    memory.log(attempt)
                    break

        return UnifiedReviewActionResponse(
            status="approved",
            id=item_id,
            source="optimizer",
            message="Optimizer proposal approved and deployed",
            deploy_message=deploy_message,
        )

    elif source == "change_card":
        cc_store = _get_change_card_store(request)
        if cc_store is None:
            raise HTTPException(status_code=503, detail="Change card store not configured")

        card = cc_store.get(item_id)
        if card is None:
            raise HTTPException(status_code=404, detail=f"Change card not found: {item_id}")
        if card.status != "pending":
            raise HTTPException(status_code=400, detail=f"Card is not pending (status={card.status})")

        ok = cc_store.update_status(item_id, "applied")
        if not ok:
            raise HTTPException(status_code=500, detail="Failed to update card status")

        return UnifiedReviewActionResponse(
            status="applied",
            id=item_id,
            source="change_card",
            message="Change card applied",
        )

    else:
        raise HTTPException(status_code=400, detail=f"Unknown source: {source!r}. Expected 'optimizer' or 'change_card'.")


@router.post("/{item_id}/reject")
async def reject_review(
    item_id: str,
    request: Request,
    body: UnifiedReviewActionRequest | None = None,
) -> UnifiedReviewActionResponse:
    """Reject a review item, dispatching to the correct underlying store."""

    if body is None:
        raise HTTPException(status_code=400, detail="Request body with 'source' field is required")

    source = body.source.strip().lower()
    reason = body.reason

    if source == "optimizer":
        pr_store = _get_pending_review_store(request)
        if pr_store is None:
            raise HTTPException(status_code=503, detail="Pending review store not configured")

        raw_review = pr_store.get_review(item_id)
        if raw_review is None:
            raise HTTPException(status_code=404, detail=f"Pending review not found: {item_id}")

        pr_store.delete_review(item_id)

        # Update optimization memory
        memory = getattr(request.app.state, "optimization_memory", None)
        if memory is not None and hasattr(memory, "get_all") and hasattr(memory, "log"):
            for attempt in memory.get_all():
                if attempt.attempt_id == item_id:
                    attempt.status = "rejected_human"
                    memory.log(attempt)
                    break

        return UnifiedReviewActionResponse(
            status="rejected",
            id=item_id,
            source="optimizer",
            message="Optimizer proposal rejected and discarded",
        )

    elif source == "change_card":
        cc_store = _get_change_card_store(request)
        if cc_store is None:
            raise HTTPException(status_code=503, detail="Change card store not configured")

        card = cc_store.get(item_id)
        if card is None:
            raise HTTPException(status_code=404, detail=f"Change card not found: {item_id}")
        if card.status != "pending":
            raise HTTPException(status_code=400, detail=f"Card is not pending (status={card.status})")

        ok = cc_store.update_status(item_id, "rejected", reason=reason)
        if not ok:
            raise HTTPException(status_code=500, detail="Failed to update card status")

        return UnifiedReviewActionResponse(
            status="rejected",
            id=item_id,
            source="change_card",
            message=f"Change card rejected{f': {reason}' if reason else ''}",
        )

    else:
        raise HTTPException(status_code=400, detail=f"Unknown source: {source!r}. Expected 'optimizer' or 'change_card'.")
