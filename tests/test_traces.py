"""Unit tests for the trace store and trace collector."""

from __future__ import annotations

import time
from pathlib import Path

from observer.traces import TraceCollector, TraceEvent, TraceEventType, TraceStore


def _make_event(
    trace_id: str = "trace-1",
    event_type: str = TraceEventType.tool_call.value,
    session_id: str = "sess-1",
    agent_path: str = "root/support",
    event_id: str | None = None,
    error_message: str | None = None,
) -> TraceEvent:
    """Build a minimal TraceEvent for tests."""
    return TraceEvent(
        event_id=event_id or f"evt-{time.time_ns()}",
        trace_id=trace_id,
        event_type=event_type,
        timestamp=time.time(),
        invocation_id="inv-1",
        session_id=session_id,
        agent_path=agent_path,
        branch="v001",
        error_message=error_message,
    )


def test_trace_store_log_and_get_event(tmp_path: Path) -> None:
    """Log an event and retrieve it via get_trace."""
    store = TraceStore(db_path=str(tmp_path / "traces.db"))
    event = _make_event(trace_id="t1", event_id="e1")
    store.log_event(event)

    events = store.get_trace("t1")
    assert len(events) == 1
    assert events[0].event_id == "e1"
    assert events[0].trace_id == "t1"


def test_trace_collector_records_full_trace(tmp_path: Path) -> None:
    """TraceCollector should record start + tool_call + tool_response + model_call + model_response."""
    store = TraceStore(db_path=str(tmp_path / "traces.db"))
    collector = TraceCollector(store)

    trace_id = collector.start_trace(
        session_id="sess-1",
        invocation_id="inv-1",
        agent_path="root",
        branch="v001",
    )

    collector.record_tool_call(
        trace_id=trace_id,
        tool_name="catalog",
        tool_input={"query": "shoes"},
        agent_path="root",
        session_id="sess-1",
        invocation_id="inv-1",
        branch="v001",
    )
    collector.record_tool_response(
        trace_id=trace_id,
        tool_name="catalog",
        tool_output={"results": ["shoe1"]},
        latency_ms=50.0,
        agent_path="root",
        session_id="sess-1",
        invocation_id="inv-1",
        branch="v001",
    )
    collector.record_model_call(
        trace_id=trace_id,
        tokens_in=100,
        agent_path="root",
        session_id="sess-1",
        invocation_id="inv-1",
        branch="v001",
    )
    collector.record_model_response(
        trace_id=trace_id,
        tokens_out=80,
        latency_ms=200.0,
        agent_path="root",
        session_id="sess-1",
        invocation_id="inv-1",
        branch="v001",
    )

    events = store.get_trace(trace_id)
    # start_trace creates 1 state_delta event, then 4 more = 5 total
    assert len(events) == 5
    types = [e.event_type for e in events]
    assert TraceEventType.state_delta.value in types
    assert TraceEventType.tool_call.value in types
    assert TraceEventType.tool_response.value in types
    assert TraceEventType.model_call.value in types
    assert TraceEventType.model_response.value in types


def test_trace_store_search_by_type(tmp_path: Path) -> None:
    """search_events with event_type filter should return only matching events."""
    store = TraceStore(db_path=str(tmp_path / "traces.db"))
    store.log_event(_make_event(event_id="e1", event_type=TraceEventType.tool_call.value))
    store.log_event(_make_event(event_id="e2", event_type=TraceEventType.error.value, error_message="boom"))
    store.log_event(_make_event(event_id="e3", event_type=TraceEventType.tool_call.value))

    errors = store.search_events(event_type=TraceEventType.error.value)
    assert len(errors) == 1
    assert errors[0].event_id == "e2"


def test_trace_store_get_error_events(tmp_path: Path) -> None:
    """get_error_events should return only error-typed events."""
    store = TraceStore(db_path=str(tmp_path / "traces.db"))
    now = time.time()
    store.log_event(
        TraceEvent(
            event_id="ok1", trace_id="t1", event_type=TraceEventType.tool_call.value,
            timestamp=now, invocation_id="inv-1", session_id="s1",
            agent_path="root", branch="v001",
        )
    )
    store.log_event(
        TraceEvent(
            event_id="err1", trace_id="t1", event_type=TraceEventType.error.value,
            timestamp=now + 1, invocation_id="inv-1", session_id="s1",
            agent_path="root", branch="v001", error_message="timeout",
        )
    )
    store.log_event(
        TraceEvent(
            event_id="err2", trace_id="t2", event_type=TraceEventType.error.value,
            timestamp=now + 2, invocation_id="inv-2", session_id="s2",
            agent_path="root", branch="v001", error_message="null ref",
        )
    )

    errors = store.get_error_events()
    assert len(errors) == 2
    assert all(e.event_type == TraceEventType.error.value for e in errors)


def test_trace_store_get_by_session(tmp_path: Path) -> None:
    """get_events_by_session should return only events for the specified session."""
    store = TraceStore(db_path=str(tmp_path / "traces.db"))
    store.log_event(_make_event(event_id="e1", session_id="sess-A"))
    store.log_event(_make_event(event_id="e2", session_id="sess-B"))
    store.log_event(_make_event(event_id="e3", session_id="sess-A"))

    session_a = store.get_events_by_session("sess-A")
    assert len(session_a) == 2
    assert all(e.session_id == "sess-A" for e in session_a)

    session_b = store.get_events_by_session("sess-B")
    assert len(session_b) == 1


def test_trace_collector_record_agent_transfer(tmp_path: Path) -> None:
    """record_agent_transfer should create an agent_transfer event with from/to metadata."""
    store = TraceStore(db_path=str(tmp_path / "traces.db"))
    collector = TraceCollector(store)

    trace_id = collector.start_trace(
        session_id="sess-1",
        invocation_id="inv-1",
        agent_path="root",
        branch="v001",
    )
    collector.record_agent_transfer(
        trace_id=trace_id,
        from_agent="root",
        to_agent="root/support",
        session_id="sess-1",
        invocation_id="inv-1",
        branch="v001",
    )

    events = store.get_trace(trace_id)
    transfer_events = [e for e in events if e.event_type == TraceEventType.agent_transfer.value]
    assert len(transfer_events) == 1
    assert transfer_events[0].metadata["from_agent"] == "root"
    assert transfer_events[0].metadata["to_agent"] == "root/support"
