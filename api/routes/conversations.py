"""Conversation endpoints — list, get, stats."""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from api.models import (
    ConversationListResponse,
    ConversationRecord as ConversationRecordModel,
    ConversationStatsResponse,
)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


def _record_to_model(record: Any) -> ConversationRecordModel:
    """Convert a logger.store.ConversationRecord dataclass to the API model."""
    return ConversationRecordModel(
        conversation_id=record.conversation_id,
        session_id=record.session_id,
        user_message=record.user_message,
        agent_response=record.agent_response,
        tool_calls=record.tool_calls,
        latency_ms=record.latency_ms,
        token_count=record.token_count,
        outcome=record.outcome,
        safety_flags=record.safety_flags,
        error_message=record.error_message,
        specialist_used=record.specialist_used,
        config_version=record.config_version,
        timestamp=record.timestamp,
    )


@router.get("/stats", response_model=ConversationStatsResponse)
async def get_conversation_stats(request: Request) -> ConversationStatsResponse:
    """Aggregate conversation statistics."""
    store = request.app.state.conversation_store
    total = store.count()

    if total == 0:
        return ConversationStatsResponse(total=0)

    # Get all recent for stats computation
    records = store.get_recent(limit=10000)
    by_outcome: dict[str, int] = {}
    total_latency = 0.0
    total_tokens = 0
    for r in records:
        by_outcome[r.outcome] = by_outcome.get(r.outcome, 0) + 1
        total_latency += r.latency_ms
        total_tokens += r.token_count

    count = len(records)
    return ConversationStatsResponse(
        total=total,
        by_outcome=by_outcome,
        avg_latency_ms=total_latency / count if count > 0 else 0.0,
        avg_token_count=total_tokens / count if count > 0 else 0.0,
    )


@router.get("", response_model=ConversationListResponse)
async def list_conversations(
    request: Request,
    limit: int = Query(50, ge=1, le=1000, description="Max records to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    outcome: str | None = Query(None, description="Filter by outcome (success, fail, error, abandon)"),
) -> ConversationListResponse:
    """List conversations with optional filtering."""
    store = request.app.state.conversation_store
    total = store.count()

    if outcome:
        records = store.get_by_outcome(outcome, limit=limit + offset)
        # Manual offset since the store doesn't support it natively
        records = records[offset : offset + limit]
    else:
        # Get with offset support
        all_records = store.get_recent(limit=limit + offset)
        records = all_records[offset : offset + limit]

    conversations = [_record_to_model(r) for r in records]
    return ConversationListResponse(
        conversations=conversations,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{conversation_id}", response_model=ConversationRecordModel)
async def get_conversation(conversation_id: str, request: Request) -> ConversationRecordModel:
    """Get a single conversation by ID."""
    store = request.app.state.conversation_store
    # The store doesn't have a get_by_id, so query directly
    try:
        with sqlite3.connect(store.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}")

    if row is None:
        raise HTTPException(status_code=404, detail=f"Conversation not found: {conversation_id}")

    record = store._row_to_record(row)
    return _record_to_model(record)
