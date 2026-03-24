"""Tests for agent tracing middleware."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.tracing import TracingMiddleware
from observer.traces import TraceEventType, TraceStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_middleware(tmp_path: Path) -> tuple[TracingMiddleware, TraceStore]:
    """Return a (TracingMiddleware, TraceStore) pair backed by a temp DB."""
    store = TraceStore(db_path=str(tmp_path / "traces.db"))
    middleware = TracingMiddleware(trace_store=store)
    return middleware, store


def _mock_agent(message: str) -> str:
    """Minimal mock agent that echoes its input."""
    return f"echo: {message}"


def _mock_agent_transfer(message: str) -> dict:
    """Mock agent that signals a specialist routing decision."""
    return {"agent_transfer": "orders", "reply": "routing you to orders"}


def _mock_agent_raises(message: str) -> str:
    """Mock agent that always raises."""
    raise RuntimeError("agent exploded")


def _mock_tool(query: str) -> list[dict]:
    """Minimal mock tool that returns a fixed result."""
    return [{"id": "PROD-001", "name": "Headphones"}]


def _mock_tool_raises(query: str) -> list[dict]:
    """Mock tool that always raises."""
    raise ValueError("tool broken")


# ---------------------------------------------------------------------------
# wrap_agent_fn — happy path
# ---------------------------------------------------------------------------


def test_wrap_agent_fn_returns_original_response(tmp_path: Path) -> None:
    """Wrapped agent must return the same value the unwrapped agent returns."""
    middleware, _ = _make_middleware(tmp_path)
    wrapped = middleware.wrap_agent_fn(_mock_agent, session_id="sess-1")

    result = wrapped("hello world")

    assert result == "echo: hello world"


def test_wrap_agent_fn_produces_trace_events(tmp_path: Path) -> None:
    """Wrapping an agent fn should produce model_call and model_response events."""
    middleware, store = _make_middleware(tmp_path)
    wrapped = middleware.wrap_agent_fn(_mock_agent, session_id="sess-2")
    wrapped("test message")

    events = store.get_recent_events(limit=50)
    event_types = {e.event_type for e in events}

    assert TraceEventType.state_delta.value in event_types  # trace start
    assert TraceEventType.model_call.value in event_types
    assert TraceEventType.model_response.value in event_types


def test_wrap_agent_fn_sets_session_id(tmp_path: Path) -> None:
    """All events in a wrapped call should share the supplied session_id."""
    middleware, store = _make_middleware(tmp_path)
    wrapped = middleware.wrap_agent_fn(_mock_agent, session_id="my-session")
    wrapped("ping")

    events = store.get_events_by_session("my-session")
    assert len(events) >= 3  # state_delta + model_call + model_response
    assert all(e.session_id == "my-session" for e in events)


def test_wrap_agent_fn_auto_generates_session_id(tmp_path: Path) -> None:
    """Without a session_id argument, each call gets its own unique session."""
    middleware, store = _make_middleware(tmp_path)
    wrapped = middleware.wrap_agent_fn(_mock_agent)

    wrapped("call 1")
    wrapped("call 2")

    all_events = store.get_recent_events(limit=100)
    session_ids = {e.session_id for e in all_events}
    # Two separate calls without a fixed session_id must produce two distinct sessions.
    assert len(session_ids) == 2


def test_wrap_agent_fn_model_call_has_token_estimate(tmp_path: Path) -> None:
    """model_call event should carry a positive tokens_in estimate."""
    middleware, store = _make_middleware(tmp_path)
    wrapped = middleware.wrap_agent_fn(_mock_agent, session_id="sess-tok")
    wrapped("please search for running shoes near me")

    events = store.get_events_by_session("sess-tok")
    model_calls = [e for e in events if e.event_type == TraceEventType.model_call.value]
    assert len(model_calls) == 1
    assert model_calls[0].tokens_in > 0


def test_wrap_agent_fn_records_agent_transfer(tmp_path: Path) -> None:
    """When the agent result signals a specialist, an agent_transfer event is emitted."""
    middleware, store = _make_middleware(tmp_path)
    wrapped = middleware.wrap_agent_fn(
        _mock_agent_transfer, session_id="sess-transfer", agent_path="root"
    )
    wrapped("I need help with my order")

    events = store.get_events_by_session("sess-transfer")
    transfer_events = [
        e for e in events if e.event_type == TraceEventType.agent_transfer.value
    ]
    assert len(transfer_events) == 1
    assert transfer_events[0].metadata["from_agent"] == "root"
    assert transfer_events[0].metadata["to_agent"] == "orders"


def test_wrap_agent_fn_sets_agent_path(tmp_path: Path) -> None:
    """Events should carry the agent_path supplied at wrap time."""
    middleware, store = _make_middleware(tmp_path)
    wrapped = middleware.wrap_agent_fn(
        _mock_agent, session_id="sess-path", agent_path="root/support"
    )
    wrapped("help")

    events = store.get_events_by_session("sess-path")
    assert all(e.agent_path == "root/support" for e in events)


def test_wrap_agent_fn_sets_branch(tmp_path: Path) -> None:
    """Events should carry the branch label supplied at wrap time."""
    middleware, store = _make_middleware(tmp_path)
    wrapped = middleware.wrap_agent_fn(
        _mock_agent, session_id="sess-branch", branch="v042"
    )
    wrapped("hello")

    events = store.get_events_by_session("sess-branch")
    assert all(e.branch == "v042" for e in events)


# ---------------------------------------------------------------------------
# wrap_agent_fn — error path
# ---------------------------------------------------------------------------


def test_wrap_agent_fn_records_error_on_exception(tmp_path: Path) -> None:
    """An exception in the agent fn should produce an error event and re-raise."""
    middleware, store = _make_middleware(tmp_path)
    wrapped = middleware.wrap_agent_fn(_mock_agent_raises, session_id="sess-err")

    with pytest.raises(RuntimeError, match="agent exploded"):
        wrapped("boom")

    events = store.get_events_by_session("sess-err")
    error_events = [e for e in events if e.event_type == TraceEventType.error.value]
    assert len(error_events) == 1
    assert "agent exploded" in (error_events[0].error_message or "")


def test_wrap_agent_fn_records_model_response_on_exception(tmp_path: Path) -> None:
    """A model_response event with tokens_out=0 should still be written on error."""
    middleware, store = _make_middleware(tmp_path)
    wrapped = middleware.wrap_agent_fn(_mock_agent_raises, session_id="sess-err2")

    with pytest.raises(RuntimeError):
        wrapped("boom")

    events = store.get_events_by_session("sess-err2")
    model_responses = [
        e for e in events if e.event_type == TraceEventType.model_response.value
    ]
    assert len(model_responses) == 1
    assert model_responses[0].tokens_out == 0


# ---------------------------------------------------------------------------
# instrument_tool — happy path
# ---------------------------------------------------------------------------


def test_instrument_tool_returns_original_result(tmp_path: Path) -> None:
    """Instrumented tool must return the same value the underlying tool returns."""
    middleware, _ = _make_middleware(tmp_path)
    wrapped_tool = middleware.instrument_tool(
        _mock_tool, "search_catalog", session_id="sess-t1"
    )

    result = wrapped_tool("headphones")

    assert result == [{"id": "PROD-001", "name": "Headphones"}]


def test_instrument_tool_emits_tool_call_and_response(tmp_path: Path) -> None:
    """instrument_tool should produce tool_call and tool_response events."""
    middleware, store = _make_middleware(tmp_path)
    wrapped_tool = middleware.instrument_tool(
        _mock_tool, "search_catalog", session_id="sess-t2"
    )
    wrapped_tool("shoes")

    events = store.get_events_by_session("sess-t2")
    event_types = {e.event_type for e in events}
    assert TraceEventType.tool_call.value in event_types
    assert TraceEventType.tool_response.value in event_types


def test_instrument_tool_records_tool_name(tmp_path: Path) -> None:
    """tool_call and tool_response events should carry the correct tool_name."""
    middleware, store = _make_middleware(tmp_path)
    wrapped_tool = middleware.instrument_tool(
        _mock_tool, "my_catalog_tool", session_id="sess-t3"
    )
    wrapped_tool("running")

    events = store.get_events_by_session("sess-t3")
    tool_events = [
        e
        for e in events
        if e.event_type
        in {TraceEventType.tool_call.value, TraceEventType.tool_response.value}
    ]
    assert all(e.tool_name == "my_catalog_tool" for e in tool_events)


def test_instrument_tool_records_input(tmp_path: Path) -> None:
    """tool_call event should capture the kwargs passed to the tool."""
    middleware, store = _make_middleware(tmp_path)
    wrapped_tool = middleware.instrument_tool(
        _mock_tool, "search_catalog", session_id="sess-t4"
    )
    wrapped_tool(query="keyboard")

    events = store.get_events_by_session("sess-t4")
    call_events = [
        e for e in events if e.event_type == TraceEventType.tool_call.value
    ]
    assert len(call_events) == 1
    import json
    tool_input = json.loads(call_events[0].tool_input or "{}")
    assert tool_input.get("query") == "keyboard"


def test_instrument_tool_records_latency(tmp_path: Path) -> None:
    """tool_response event should carry a non-negative latency_ms value."""
    middleware, store = _make_middleware(tmp_path)
    wrapped_tool = middleware.instrument_tool(
        _mock_tool, "search_catalog", session_id="sess-t5"
    )
    wrapped_tool("desk")

    events = store.get_events_by_session("sess-t5")
    response_events = [
        e for e in events if e.event_type == TraceEventType.tool_response.value
    ]
    assert len(response_events) == 1
    assert response_events[0].latency_ms >= 0.0


def test_instrument_tool_correlates_with_trace_id_provider(tmp_path: Path) -> None:
    """When trace_id_provider is supplied, tool events share the parent trace_id."""
    middleware, store = _make_middleware(tmp_path)

    # Simulate a parent trace already in progress.
    parent_trace_id = middleware.collector.start_trace(
        session_id="sess-t6",
        invocation_id="inv-parent",
        agent_path="root",
        branch="v001",
    )

    wrapped_tool = middleware.instrument_tool(
        _mock_tool,
        "search_catalog",
        session_id="sess-t6",
        trace_id_provider=lambda: parent_trace_id,
    )
    wrapped_tool("monitor")

    # All events under this trace_id include the parent start + tool events.
    events = store.get_trace(parent_trace_id)
    event_types = {e.event_type for e in events}
    assert TraceEventType.tool_call.value in event_types
    assert TraceEventType.tool_response.value in event_types


# ---------------------------------------------------------------------------
# instrument_tool — error path
# ---------------------------------------------------------------------------


def test_instrument_tool_records_error_on_exception(tmp_path: Path) -> None:
    """A tool exception should produce an error-typed tool_response and re-raise."""
    middleware, store = _make_middleware(tmp_path)
    wrapped_tool = middleware.instrument_tool(
        _mock_tool_raises, "broken_tool", session_id="sess-terr"
    )

    with pytest.raises(ValueError, match="tool broken"):
        wrapped_tool("query")

    events = store.get_events_by_session("sess-terr")
    # record_tool_response uses error type when error kwarg is set.
    error_events = [e for e in events if e.event_type == TraceEventType.error.value]
    assert len(error_events) == 1
    assert "tool broken" in (error_events[0].error_message or "")


def test_instrument_tool_no_tool_response_on_success_for_error_path(
    tmp_path: Path,
) -> None:
    """On error there should be no tool_response event (only error)."""
    middleware, store = _make_middleware(tmp_path)
    wrapped_tool = middleware.instrument_tool(
        _mock_tool_raises, "broken_tool", session_id="sess-terr2"
    )

    with pytest.raises(ValueError):
        wrapped_tool("q")

    events = store.get_events_by_session("sess-terr2")
    tool_response_events = [
        e for e in events if e.event_type == TraceEventType.tool_response.value
    ]
    assert len(tool_response_events) == 0


# ---------------------------------------------------------------------------
# record_transfer — explicit API
# ---------------------------------------------------------------------------


def test_record_transfer_delegates_to_collector(tmp_path: Path) -> None:
    """record_transfer should write an agent_transfer event to the store."""
    middleware, store = _make_middleware(tmp_path)

    trace_id = middleware.collector.start_trace(
        session_id="sess-xfr",
        invocation_id="inv-xfr",
        agent_path="root",
        branch="v001",
    )
    middleware.record_transfer(
        trace_id=trace_id,
        from_agent="root",
        to_agent="root/recommendations",
        session_id="sess-xfr",
        invocation_id="inv-xfr",
        branch="v001",
    )

    events = store.get_trace(trace_id)
    transfer_events = [
        e for e in events if e.event_type == TraceEventType.agent_transfer.value
    ]
    assert len(transfer_events) == 1
    assert transfer_events[0].metadata["to_agent"] == "root/recommendations"


# ---------------------------------------------------------------------------
# TraceStore integration — data persists across middleware instances
# ---------------------------------------------------------------------------


def test_trace_store_persists_across_middleware_instances(tmp_path: Path) -> None:
    """Data written by one middleware instance is readable by a second one."""
    db_path = str(tmp_path / "shared.db")

    middleware_a = TracingMiddleware(trace_store=TraceStore(db_path=db_path))
    wrapped = middleware_a.wrap_agent_fn(_mock_agent, session_id="sess-persist")
    wrapped("hello")

    # New instance, same DB.
    middleware_b = TracingMiddleware(trace_store=TraceStore(db_path=db_path))
    events = middleware_b.store.get_events_by_session("sess-persist")
    assert len(events) >= 3


# ---------------------------------------------------------------------------
# Multiple sequential invocations — isolation
# ---------------------------------------------------------------------------


def test_multiple_invocations_produce_separate_traces(tmp_path: Path) -> None:
    """Each call to a wrapped agent fn should produce a distinct trace_id."""
    middleware, store = _make_middleware(tmp_path)
    wrapped = middleware.wrap_agent_fn(_mock_agent)

    wrapped("first call")
    wrapped("second call")

    all_events = store.get_recent_events(limit=100)
    trace_ids = {e.trace_id for e in all_events}
    assert len(trace_ids) == 2


def test_multiple_tool_calls_accumulate_in_store(tmp_path: Path) -> None:
    """N tool calls should produce 2N tool events (call + response each)."""
    middleware, store = _make_middleware(tmp_path)
    session_id = "sess-multi"
    parent_trace_id = middleware.collector.start_trace(
        session_id=session_id,
        invocation_id="inv-multi",
        agent_path="root",
        branch="v001",
    )
    wrapped_tool = middleware.instrument_tool(
        _mock_tool,
        "catalog",
        session_id=session_id,
        trace_id_provider=lambda: parent_trace_id,
    )

    for _ in range(3):
        wrapped_tool("query")

    events = store.get_trace(parent_trace_id)
    call_events = [e for e in events if e.event_type == TraceEventType.tool_call.value]
    resp_events = [
        e for e in events if e.event_type == TraceEventType.tool_response.value
    ]
    assert len(call_events) == 3
    assert len(resp_events) == 3
