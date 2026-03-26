"""Collaborative review API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/reviews", tags=["collaboration"])


class ReviewRequestBody(BaseModel):
    """Request to create a review."""

    change_id: str
    reviewers: list[str]
    policy: str = "any_one"


class ReviewSubmissionBody(BaseModel):
    """Submit a review."""

    reviewer: str
    decision: str  # approve, reject
    comment: str = ""


@router.post("/request")
async def create_review_request(request: Request, body: ReviewRequestBody) -> dict:
    """Create a review request."""
    from collaboration.review import ReviewManager

    review_manager = ReviewManager()
    request_id = review_manager.request_review(
        change_id=body.change_id,
        reviewers=body.reviewers,
        policy=body.policy,
    )

    return {"request_id": request_id, "status": "created"}


@router.post("/{request_id}/submit")
async def submit_review(
    request: Request, request_id: str, body: ReviewSubmissionBody
) -> dict:
    """Submit a review."""
    from collaboration.review import ReviewManager

    review_manager = ReviewManager()
    success = review_manager.submit_review(
        request_id=request_id,
        reviewer=body.reviewer,
        decision=body.decision,
        comment=body.comment,
    )

    if not success:
        raise HTTPException(status_code=404, detail="Review request not found")

    return {"status": "submitted"}


@router.get("/pending")
async def list_pending_reviews(request: Request) -> dict:
    """List pending reviews."""
    from collaboration.review import ReviewManager

    review_manager = ReviewManager()
    reviews = review_manager.list_pending()

    return {"reviews": reviews}


@router.get("/{request_id}")
async def get_review_details(request: Request, request_id: str) -> dict:
    """Get review details with comments."""
    from collaboration.review import ReviewManager

    review_manager = ReviewManager()
    review = review_manager.get_review(request_id)

    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    return review
