"""Trace viewer API endpoints."""

from __future__ import annotations

import dataclasses
from typing import Optional

from fastapi import APIRouter, Query, Request, HTTPException

router = APIRouter(prefix="/api/traces", tags=["traces"])


def _event_to_dict(event) -> dict:
    """Serialize a TraceEvent dataclass to a JSON-safe dict."""
    d = dataclasses.asdict(event)
    return d


def _span_to_dict(span) -> dict:
    """Serialize a TraceSpan dataclass to a JSON-safe dict."""
    return dataclasses.asdict(span)


@router.get("/recent")
async def get_recent_traces(
    request: Request,
    limit: int = Query(100, ge=1, le=10000, description="Maximum number of recent events"),
) -> dict:
    """Return recent trace events."""
    trace_store = getattr(request.app.state, "trace_store", None)
    if trace_store is None:
        return {"events": [], "message": "Trace store not configured"}
    events = trace_store.get_recent_events(limit=limit)
    return {"events": [_event_to_dict(e) for e in events]}


@router.get("/search")
async def search_traces(
    request: Request,
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    agent_path: Optional[str] = Query(None, description="Filter by agent path"),
    since: Optional[float] = Query(None, description="Only events after this epoch timestamp"),
    limit: int = Query(100, ge=1, le=10000, description="Maximum results"),
) -> dict:
    """Search trace events by type, agent path, or time range."""
    trace_store = getattr(request.app.state, "trace_store", None)
    if trace_store is None:
        return {"events": [], "message": "Trace store not configured"}
    events = trace_store.search_events(
        event_type=event_type,
        agent_path=agent_path,
        since=since,
        limit=limit,
    )
    return {"events": [_event_to_dict(e) for e in events]}


@router.get("/errors")
async def get_error_traces(
    request: Request,
    limit: int = Query(50, ge=1, le=10000, description="Maximum error events to return"),
) -> dict:
    """Return recent error events."""
    trace_store = getattr(request.app.state, "trace_store", None)
    if trace_store is None:
        return {"events": [], "message": "Trace store not configured"}
    events = trace_store.get_error_events(limit=limit)
    return {"events": [_event_to_dict(e) for e in events]}


@router.get("/sessions/{session_id}")
async def get_session_traces(
    session_id: str,
    request: Request,
) -> dict:
    """Return all trace events for a specific session."""
    trace_store = getattr(request.app.state, "trace_store", None)
    if trace_store is None:
        return {"session_id": session_id, "events": [], "message": "Trace store not configured"}
    events = trace_store.get_events_by_session(session_id)
    return {"session_id": session_id, "events": [_event_to_dict(e) for e in events]}


@router.get("/blame")
async def get_blame_map(
    request: Request,
    window: int = Query(86400, ge=1, description="Time window in seconds"),
) -> dict:
    """Build a blame map of failure clusters."""
    from observer.blame_map import BlameMap
    from observer.trace_grading import TraceGrader

    trace_store = getattr(request.app.state, "trace_store", None)
    if trace_store is None:
        raise HTTPException(status_code=503, detail="Trace store not configured")
    grader = TraceGrader()
    blame_map = BlameMap.from_store(trace_store, grader, window_seconds=window)
    clusters = blame_map.compute(window_seconds=window)
    return {"clusters": [c.to_dict() for c in clusters], "window_seconds": window}


@router.get("/{trace_id}/grades")
async def get_trace_grades(
    trace_id: str,
    request: Request,
) -> dict:
    """Grade all spans in a trace."""
    from observer.trace_grading import TraceGrader

    trace_store = getattr(request.app.state, "trace_store", None)
    if trace_store is None:
        raise HTTPException(status_code=503, detail="Trace store not configured")
    grader = TraceGrader()
    grades = grader.grade_trace(trace_id, trace_store)
    return {"trace_id": trace_id, "grades": [g.to_dict() for g in grades]}


@router.get("/{trace_id}/graph")
async def get_trace_graph(
    trace_id: str,
    request: Request,
) -> dict:
    """Build a graph representation of a trace."""
    from observer.trace_graph import TraceGraph
    from observer.trace_grading import TraceGrader

    trace_store = getattr(request.app.state, "trace_store", None)
    if trace_store is None:
        raise HTTPException(status_code=503, detail="Trace store not configured")

    spans = trace_store.get_spans(trace_id)
    grader = TraceGrader()
    grades = grader.grade_trace(trace_id, trace_store)
    graph = TraceGraph.from_spans(spans, grades)
    critical_path = graph.get_critical_path()
    bottlenecks = graph.get_bottlenecks()

    return {
        "nodes": [n.to_dict() for n in graph.nodes.values()],
        "edges": [e.to_dict() for e in graph.edges],
        "critical_path": [n.to_dict() for n in critical_path],
        "bottlenecks": [n.to_dict() for n in bottlenecks],
    }


@router.get("/{trace_id}")
async def get_trace(
    trace_id: str,
    request: Request,
) -> dict:
    """Return all events and spans for a specific trace."""
    trace_store = getattr(request.app.state, "trace_store", None)
    if trace_store is None:
        return {"trace_id": trace_id, "events": [], "spans": [], "message": "Trace store not configured"}
    events = trace_store.get_trace(trace_id)
    spans = trace_store.get_spans(trace_id)
    return {
        "trace_id": trace_id,
        "events": [_event_to_dict(e) for e in events],
        "spans": [_span_to_dict(s) for s in spans],
    }
