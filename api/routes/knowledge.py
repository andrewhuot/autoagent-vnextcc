"""Knowledge mining API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


class MiningRequest(BaseModel):
    """Request to trigger knowledge mining."""

    min_score: float = 0.9
    limit: int = 100


class ReviewRequest(BaseModel):
    """Request to review a knowledge entry."""

    decision: str  # approved, rejected
    comment: str | None = None


@router.post("/mine")
async def trigger_mining(request: Request, body: MiningRequest) -> dict:
    """Trigger a knowledge mining run."""
    from observer.knowledge_miner import KnowledgeMiner
    from observer.knowledge_store import KnowledgeStore

    conversation_store = request.app.state.conversation_store
    knowledge_store = KnowledgeStore()

    miner = KnowledgeMiner(conversation_store)

    # Mine successful conversations
    successful = miner.mine_successes(min_score=body.min_score, limit=body.limit)

    # Extract patterns
    patterns = miner.extract_patterns(successful)

    # Generate and save entries
    entries = miner.generate_knowledge_entries(patterns)
    for entry in entries:
        try:
            knowledge_store.create(entry)
        except Exception:
            pass  # Skip duplicates

    return {
        "status": "completed",
        "conversations_analyzed": len(successful),
        "patterns_found": len(patterns),
        "entries_created": len(entries),
    }


@router.get("/entries")
async def list_entries(
    request: Request,
    status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
) -> dict:
    """List knowledge entries with filters."""
    from observer.knowledge_store import KnowledgeStore

    knowledge_store = KnowledgeStore()
    entries = knowledge_store.list(status=status, limit=limit)

    return {"entries": entries, "count": len(entries)}


@router.post("/apply/{pattern_id}")
async def apply_entry(request: Request, pattern_id: str) -> dict:
    """Apply a knowledge entry as a mutation."""
    from observer.knowledge_store import KnowledgeStore

    knowledge_store = KnowledgeStore()
    entry = knowledge_store.get(pattern_id)

    if not entry:
        raise HTTPException(status_code=404, detail="Knowledge entry not found")

    # TODO: Actually apply the pattern as a mutation
    # For now, just mark it as applied
    success = knowledge_store.mark_applied(pattern_id)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to mark entry as applied")

    return {"status": "applied", "pattern_id": pattern_id}


@router.put("/review/{pattern_id}")
async def review_entry(request: Request, pattern_id: str, body: ReviewRequest) -> dict:
    """Approve or reject a knowledge entry."""
    from observer.knowledge_store import KnowledgeStore

    knowledge_store = KnowledgeStore()

    if body.decision == "approved":
        new_status = "reviewed"
    elif body.decision == "rejected":
        new_status = "retired"
    else:
        raise HTTPException(status_code=400, detail="Invalid decision")

    success = knowledge_store.update_status(pattern_id, new_status)

    if not success:
        raise HTTPException(status_code=404, detail="Knowledge entry not found")

    return {"status": "updated", "new_status": new_status}
