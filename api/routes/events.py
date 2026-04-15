"""System event log API endpoints.

Includes the original system event log endpoint and a unified endpoint
that merges system events with builder events for a single timeline.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from builder.events import BRIDGED_SYSTEM_EVENT_TYPES, event_to_dict

router = APIRouter(prefix="/api/events", tags=["events"])


def _event_source_metadata(source: str | None, has_builder_events: bool) -> dict[str, dict]:
    """Return display metadata for the event stores included in a query."""
    return {
        "system": {
            "included": source in (None, "system"),
            "durable": True,
            "label": "System event log",
        },
        "builder": {
            "included": source in (None, "builder") and has_builder_events,
            "durable": has_builder_events,
            "label": "Builder event history",
        },
    }


def _normalize_event_source(source: str | None) -> str | None:
    """Normalize the event source query so clients can request every store explicitly."""
    if source is None or source == "all":
        return None
    if source in {"system", "builder"}:
        return source
    raise HTTPException(status_code=400, detail="source must be one of: all, system, builder")


def _history_continuity() -> dict[str, str]:
    """Describe the unified event timeline as durable restart-safe history."""
    return {
        "state": "historical",
        "label": "Durable event history",
        "detail": "This timeline merges persisted system events and builder events so history remains visible after restart.",
    }


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
    normalized_source = _normalize_event_source(source)
    include_builder = normalized_source in (None, "builder") and builder_events_broker is not None
    source_metadata = _event_source_metadata(normalized_source, builder_events_broker is not None)

    # Bridged builder event types appear in both system EventLog and builder
    # DurableEventStore.  When querying both sources, exclude the bridged copies
    # from the system results to avoid duplicates in the timeline.
    merged: list[dict] = []

    # Collect system events
    if normalized_source in (None, "system"):
        system_events = event_log.list_events(limit=limit, session_id=session_id)
        for evt in system_events:
            # Skip bridged builder events when builder source is also included
            if include_builder and evt["event_type"] in BRIDGED_SYSTEM_EVENT_TYPES:
                continue
            merged.append({
                "id": f"sys-{evt['id']}",
                "timestamp": evt["timestamp"],
                "event_type": evt["event_type"],
                "source": "system",
                "source_label": source_metadata["system"]["label"],
                "continuity_state": "historical",
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
                "source_label": source_metadata["builder"]["label"],
                "continuity_state": "historical",
                "session_id": evt_dict.get("session_id"),
                "payload": evt_dict.get("payload", {}),
            })

    # Sort by timestamp descending (newest first) and apply limit
    merged.sort(key=lambda e: e["timestamp"], reverse=True)
    merged = merged[:limit]

    return {
        "events": merged,
        "count": len(merged),
        "sources": source_metadata,
        "continuity": _history_continuity(),
    }
