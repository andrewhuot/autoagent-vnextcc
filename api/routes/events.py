"""System event log API endpoints.

Includes the original system event log endpoint and a unified endpoint
that merges system events with builder events for a single timeline.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from builder.events import event_to_dict

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("")
async def list_events(
    request: Request,
    limit: int = Query(100, ge=1, le=1000),
    event_type: str | None = Query(None),
) -> dict:
    """List append-only system events."""
    event_log = request.app.state.event_log
    events = event_log.list_events(limit=limit, event_type=event_type)
    return {"events": events}


@router.get("/unified")
async def list_unified_events(
    request: Request,
    limit: int = Query(100, ge=1, le=1000),
    session_id: str | None = Query(None),
    source: str | None = Query(None, description="Filter by source: system, builder, or all"),
) -> dict:
    """Return a merged, time-ordered timeline of all runtime events.

    Merges two durable stores:
    - **system**: EventLog (optimizer, eval, deploy, autofix, judges, broadcasts)
    - **builder**: DurableEventStore (builder harness lifecycle and content events)

    Each returned event includes a ``source`` field (``"system"`` or ``"builder"``)
    so consumers can distinguish origin.  Results are sorted newest-first.
    """
    event_log = request.app.state.event_log
    builder_events_broker = getattr(request.app.state, "builder_events", None)
    include_builder = source in (None, "builder") and builder_events_broker is not None

    # Bridged builder event types appear in both system EventLog and builder
    # DurableEventStore.  When querying both sources, exclude the bridged copies
    # from the system results to avoid duplicates in the timeline.
    _BRIDGED_BUILDER_TYPES = frozenset({
        "builder_task_started", "builder_task_completed", "builder_task_failed",
        "builder_session_opened", "builder_session_closed",
        "builder_eval_started", "builder_eval_completed",
    })

    merged: list[dict] = []

    # Collect system events
    if source in (None, "system"):
        system_events = event_log.list_events(limit=limit, session_id=session_id)
        for evt in system_events:
            # Skip bridged builder events when builder source is also included
            if include_builder and evt["event_type"] in _BRIDGED_BUILDER_TYPES:
                continue
            merged.append({
                "id": f"sys-{evt['id']}",
                "timestamp": evt["timestamp"],
                "event_type": evt["event_type"],
                "source": "system",
                "session_id": evt.get("session_id"),
                "payload": evt.get("payload", {}),
            })

    # Collect builder events from durable store
    if include_builder:
        builder_events = builder_events_broker.list_events(
            session_id=session_id,
            limit=limit,
        )
        for evt in builder_events:
            evt_dict = event_to_dict(evt)
            merged.append({
                "id": f"bld-{evt_dict['event_id']}",
                "timestamp": evt_dict["timestamp"],
                "event_type": evt_dict["event_type"],
                "source": "builder",
                "session_id": evt_dict.get("session_id"),
                "payload": evt_dict.get("payload", {}),
            })

    # Sort by timestamp descending (newest first) and apply limit
    merged.sort(key=lambda e: e["timestamp"], reverse=True)
    merged = merged[:limit]

    return {"events": merged, "count": len(merged)}
