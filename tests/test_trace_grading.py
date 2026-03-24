"""Comprehensive tests for trace grading, trace graph, and blame map."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from observer.traces import TraceEvent, TraceEventType, TraceSpan, TraceStore
from observer.trace_grading import (
    FinalOutcomeGrader,
    HandoffQualityGrader,
    MemoryUseGrader,
    RetrievalQualityGrader,
    RoutingGrader,
    SpanGrade,
    SpanGrader,
    ToolArgumentGrader,
    ToolSelectionGrader,
    TraceGrader,
)
from observer.trace_graph import TraceGraph, TraceGraphEdge, TraceGraphNode
from observer.blame_map import BlameCluster, BlameMap


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_T = 1000000.0  # base timestamp


def _event(
    event_id: str = "e1",
    trace_id: str = "t1",
    event_type: str = TraceEventType.tool_call.value,
    timestamp: float = _T,
    agent_path: str = "root/support",
    tool_name: str | None = None,
    tool_input: str | None = None,
    tool_output: str | None = None,
    error_message: str | None = None,
    metadata: dict | None = None,
    latency_ms: float = 0.0,
    tokens_in: int = 0,
    tokens_out: int = 0,
) -> TraceEvent:
    return TraceEvent(
        event_id=event_id,
        trace_id=trace_id,
        event_type=event_type,
        timestamp=timestamp,
        invocation_id="inv-1",
        session_id="sess-1",
        agent_path=agent_path,
        branch="v1",
        tool_name=tool_name,
        tool_input=tool_input,
        tool_output=tool_output,
        error_message=error_message,
        metadata=metadata or {},
        latency_ms=latency_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )


def _span(
    span_id: str = "s1",
    trace_id: str = "t1",
    parent_span_id: str | None = None,
    operation: str = "handle_request",
    agent_path: str = "root/support",
    start_time: float = _T,
    end_time: float = _T + 1.0,
    status: str = "ok",
) -> TraceSpan:
    return TraceSpan(
        span_id=span_id,
        trace_id=trace_id,
        parent_span_id=parent_span_id,
        operation=operation,
        agent_path=agent_path,
        start_time=start_time,
        end_time=end_time,
        status=status,
    )


def _populate_store(store: TraceStore, spans: list[TraceSpan], events: list[TraceEvent]) -> None:
    """Helper to insert spans and events into a store."""
    for s in spans:
        store.log_span(s)
    for e in events:
        store.log_event(e)


# ===========================================================================
# SpanGrade tests
# ===========================================================================

class TestSpanGrade:
    def test_creation(self) -> None:
        g = SpanGrade(span_id="s1", grader_name="test", score=0.8, passed=True, evidence="ok")
        assert g.span_id == "s1"
        assert g.score == 0.8
        assert g.passed is True
        assert g.failure_reason is None

    def test_to_dict(self) -> None:
        g = SpanGrade(
            span_id="s1", grader_name="test", score=0.5, passed=False,
            evidence="bad", failure_reason="oops", metadata={"k": "v"},
        )
        d = g.to_dict()
        assert d["span_id"] == "s1"
        assert d["score"] == 0.5
        assert d["failure_reason"] == "oops"
        assert d["metadata"] == {"k": "v"}

    def test_defaults(self) -> None:
        g = SpanGrade(span_id="x", grader_name="g", score=1.0, passed=True, evidence="e")
        assert g.metadata == {}
        assert g.failure_reason is None


# ===========================================================================
# RoutingGrader tests
# ===========================================================================

class TestRoutingGrader:
    def setup_method(self) -> None:
        self.grader = RoutingGrader()
        self.span = _span()

    def test_no_transfers(self) -> None:
        grade = self.grader.grade(self.span, [], {})
        assert grade.passed is True
        assert grade.score == 1.0

    def test_correct_routing(self) -> None:
        evt = _event(
            event_type=TraceEventType.agent_transfer.value,
            metadata={"from_agent": "root", "to_agent": "orders"},
        )
        grade = self.grader.grade(self.span, [evt], {"expected_specialist": "orders"})
        assert grade.passed is True
        assert grade.score == 1.0

    def test_wrong_routing(self) -> None:
        evt = _event(
            event_type=TraceEventType.agent_transfer.value,
            metadata={"from_agent": "root", "to_agent": "billing"},
        )
        grade = self.grader.grade(self.span, [evt], {"expected_specialist": "orders"})
        assert grade.passed is False
        assert grade.score == 0.0
        assert "Wrong routing" in (grade.failure_reason or "")

    def test_no_expected_specialist(self) -> None:
        evt = _event(
            event_type=TraceEventType.agent_transfer.value,
            metadata={"from_agent": "root", "to_agent": "billing"},
        )
        grade = self.grader.grade(self.span, [evt], {})
        assert grade.passed is True


# ===========================================================================
# ToolSelectionGrader tests
# ===========================================================================

class TestToolSelectionGrader:
    def setup_method(self) -> None:
        self.grader = ToolSelectionGrader()
        self.span = _span()

    def test_no_tool_calls(self) -> None:
        grade = self.grader.grade(self.span, [], {})
        assert grade.passed is True

    def test_correct_tool(self) -> None:
        evt = _event(tool_name="search_orders")
        grade = self.grader.grade(self.span, [evt], {"expected_tool": "search_orders"})
        assert grade.passed is True
        assert grade.score == 1.0

    def test_wrong_tool(self) -> None:
        evt = _event(tool_name="search_products")
        grade = self.grader.grade(self.span, [evt], {"expected_tool": "search_orders"})
        assert grade.passed is False
        assert grade.score == 0.0

    def test_no_expected_tool(self) -> None:
        evt = _event(tool_name="anything")
        grade = self.grader.grade(self.span, [evt], {})
        assert grade.passed is True


# ===========================================================================
# ToolArgumentGrader tests
# ===========================================================================

class TestToolArgumentGrader:
    def setup_method(self) -> None:
        self.grader = ToolArgumentGrader()
        self.span = _span()

    def test_no_tool_calls(self) -> None:
        grade = self.grader.grade(self.span, [], {})
        assert grade.passed is True

    def test_valid_args(self) -> None:
        evt = _event(tool_name="search", tool_input=json.dumps({"query": "shoes"}))
        grade = self.grader.grade(self.span, [evt], {})
        assert grade.passed is True
        assert grade.score == 1.0

    def test_empty_input(self) -> None:
        evt = _event(tool_name="search", tool_input=None)
        grade = self.grader.grade(self.span, [evt], {})
        assert grade.score < 1.0

    def test_empty_args_dict(self) -> None:
        evt = _event(tool_name="search", tool_input=json.dumps({}))
        grade = self.grader.grade(self.span, [evt], {})
        assert grade.score < 1.0

    def test_error_after_tool_call(self) -> None:
        tc = _event(event_id="e1", tool_name="search", tool_input=json.dumps({"q": "x"}))
        err = _event(
            event_id="e2",
            event_type=TraceEventType.error.value,
            error_message="invalid argument",
        )
        grade = self.grader.grade(self.span, [tc, err], {})
        assert grade.score < 1.0

    def test_expected_args_match(self) -> None:
        evt = _event(tool_name="search", tool_input=json.dumps({"query": "shoes", "limit": 10}))
        ctx = {"expected_tool_args": {"query": "shoes"}}
        grade = self.grader.grade(self.span, [evt], ctx)
        assert grade.passed is True
        assert grade.score == 1.0

    def test_expected_args_missing(self) -> None:
        evt = _event(tool_name="search", tool_input=json.dumps({"limit": 10}))
        ctx = {"expected_tool_args": {"query": "shoes"}}
        grade = self.grader.grade(self.span, [evt], ctx)
        assert grade.score < 1.0


# ===========================================================================
# RetrievalQualityGrader tests
# ===========================================================================

class TestRetrievalQualityGrader:
    def setup_method(self) -> None:
        self.grader = RetrievalQualityGrader()
        self.span = _span()

    def test_no_responses(self) -> None:
        grade = self.grader.grade(self.span, [], {})
        assert grade.passed is True

    def test_good_retrieval(self) -> None:
        evt = _event(
            event_type=TraceEventType.tool_response.value,
            tool_output=json.dumps({"results": [{"doc": "relevant"}]}),
        )
        grade = self.grader.grade(self.span, [evt], {})
        assert grade.passed is True
        assert grade.score == 1.0

    def test_empty_retrieval(self) -> None:
        evt = _event(
            event_type=TraceEventType.tool_response.value,
            tool_output=json.dumps({"results": []}),
        )
        grade = self.grader.grade(self.span, [evt], {})
        assert grade.passed is False
        assert grade.score == 0.0

    def test_non_retrieval_response(self) -> None:
        evt = _event(
            event_type=TraceEventType.tool_response.value,
            tool_output=json.dumps({"status": "ok"}),
        )
        grade = self.grader.grade(self.span, [evt], {})
        assert grade.passed is True  # no retrieval-like results key


# ===========================================================================
# HandoffQualityGrader tests
# ===========================================================================

class TestHandoffQualityGrader:
    def setup_method(self) -> None:
        self.grader = HandoffQualityGrader()
        self.span = _span()

    def test_no_transfers(self) -> None:
        grade = self.grader.grade(self.span, [], {})
        assert grade.passed is True

    def test_good_handoff(self) -> None:
        evt = _event(
            event_type=TraceEventType.agent_transfer.value,
            metadata={"from_agent": "root", "to_agent": "orders"},
        )
        grade = self.grader.grade(self.span, [evt], {})
        assert grade.passed is True
        assert grade.score == 1.0

    def test_handoff_missing_goal(self) -> None:
        evt = _event(
            event_type=TraceEventType.agent_transfer.value,
            metadata={
                "from_agent": "root",
                "to_agent": "orders",
                "handoff_artifact": {"goal": "", "known_facts": {"a": 1}},
            },
        )
        grade = self.grader.grade(self.span, [evt], {})
        assert grade.score < 1.0


# ===========================================================================
# MemoryUseGrader tests
# ===========================================================================

class TestMemoryUseGrader:
    def setup_method(self) -> None:
        self.grader = MemoryUseGrader()
        self.span = _span()

    def test_no_state_deltas(self) -> None:
        grade = self.grader.grade(self.span, [], {})
        assert grade.passed is True

    def test_fresh_memory(self) -> None:
        evt = _event(event_type=TraceEventType.state_delta.value, metadata={"action": "read"})
        grade = self.grader.grade(self.span, [evt], {})
        assert grade.passed is True
        assert grade.score == 1.0

    def test_stale_memory(self) -> None:
        evt = _event(event_type=TraceEventType.state_delta.value, metadata={"stale": True})
        grade = self.grader.grade(self.span, [evt], {})
        assert grade.score == 0.0
        assert grade.passed is False

    def test_mixed_staleness(self) -> None:
        e1 = _event(event_id="e1", event_type=TraceEventType.state_delta.value, metadata={"stale": True})
        e2 = _event(event_id="e2", event_type=TraceEventType.state_delta.value, metadata={})
        grade = self.grader.grade(self.span, [e1, e2], {})
        assert grade.score == 0.5


# ===========================================================================
# FinalOutcomeGrader tests
# ===========================================================================

class TestFinalOutcomeGrader:
    def setup_method(self) -> None:
        self.grader = FinalOutcomeGrader()
        self.span = _span()

    def test_success_with_response(self) -> None:
        evt = _event(event_type=TraceEventType.model_response.value, tokens_out=100)
        grade = self.grader.grade(self.span, [evt], {})
        assert grade.passed is True
        assert grade.score == 1.0

    def test_error_event(self) -> None:
        evt = _event(event_type=TraceEventType.error.value, error_message="timeout")
        grade = self.grader.grade(self.span, [evt], {})
        assert grade.passed is False
        assert grade.score == 0.0
        assert grade.failure_reason == "timeout"

    def test_error_status_no_events(self) -> None:
        span = _span(status="error")
        grade = self.grader.grade(span, [], {})
        assert grade.passed is False
        assert grade.score == 0.0

    def test_ok_no_responses(self) -> None:
        grade = self.grader.grade(self.span, [], {})
        assert grade.passed is True
        assert grade.score == 0.5  # ambiguous


# ===========================================================================
# TraceGrader tests
# ===========================================================================

class TestTraceGrader:
    def test_grade_trace_with_tool_span(self, tmp_path: Path) -> None:
        store = TraceStore(db_path=str(tmp_path / "traces.db"))
        span = _span(span_id="s1", trace_id="t1", start_time=_T, end_time=_T + 2.0)
        evt = _event(trace_id="t1", event_type=TraceEventType.tool_call.value, tool_name="search")
        _populate_store(store, [span], [evt])

        grader = TraceGrader()
        grades = grader.grade_trace("t1", store)
        # Should have tool_selection and tool_argument grades (and final_outcome since root span)
        grader_names = {g.grader_name for g in grades}
        assert "tool_selection" in grader_names
        assert "tool_argument" in grader_names
        assert "final_outcome" in grader_names

    def test_grade_trace_with_transfer_span(self, tmp_path: Path) -> None:
        store = TraceStore(db_path=str(tmp_path / "traces.db"))
        span = _span(span_id="s1", trace_id="t1")
        evt = _event(
            trace_id="t1",
            event_type=TraceEventType.agent_transfer.value,
            metadata={"from_agent": "root", "to_agent": "orders"},
        )
        _populate_store(store, [span], [evt])

        grader = TraceGrader()
        grades = grader.grade_trace("t1", store, {"expected_specialist": "orders"})
        grader_names = {g.grader_name for g in grades}
        assert "routing" in grader_names
        assert "handoff_quality" in grader_names

    def test_grader_applies_filtering(self) -> None:
        """Graders should only apply to spans with relevant events."""
        grader = TraceGrader()
        span = _span(parent_span_id="parent")  # not root

        # No events -> only final_outcome could apply (but not root, so nothing)
        tool_call_evt = _event(event_type=TraceEventType.tool_call.value)
        memory_evt = _event(event_type=TraceEventType.state_delta.value)

        assert TraceGrader._grader_applies(RoutingGrader(), span, []) is False
        assert TraceGrader._grader_applies(ToolSelectionGrader(), span, [tool_call_evt]) is True
        assert TraceGrader._grader_applies(MemoryUseGrader(), span, [memory_evt]) is True
        assert TraceGrader._grader_applies(FinalOutcomeGrader(), span, []) is False

    def test_final_outcome_applies_to_root(self) -> None:
        span = _span(parent_span_id=None)
        assert TraceGrader._grader_applies(FinalOutcomeGrader(), span, []) is True

    def test_final_outcome_applies_to_error_span(self) -> None:
        span = _span(parent_span_id="parent", status="error")
        assert TraceGrader._grader_applies(FinalOutcomeGrader(), span, []) is True

    def test_custom_graders(self, tmp_path: Path) -> None:
        store = TraceStore(db_path=str(tmp_path / "traces.db"))
        span = _span(span_id="s1", trace_id="t1")
        evt = _event(trace_id="t1", event_type=TraceEventType.tool_call.value, tool_name="x")
        _populate_store(store, [span], [evt])

        grader = TraceGrader(graders=[ToolSelectionGrader()])
        grades = grader.grade_trace("t1", store)
        assert all(g.grader_name == "tool_selection" for g in grades)

    def test_empty_trace(self, tmp_path: Path) -> None:
        store = TraceStore(db_path=str(tmp_path / "traces.db"))
        grader = TraceGrader()
        grades = grader.grade_trace("nonexistent", store)
        assert grades == []


# ===========================================================================
# TraceGraph tests
# ===========================================================================

class TestTraceGraph:
    def test_from_spans_basic(self) -> None:
        root = _span(span_id="root", parent_span_id=None, start_time=_T, end_time=_T + 5.0)
        child = _span(span_id="child", parent_span_id="root", start_time=_T + 0.5, end_time=_T + 3.0)
        graph = TraceGraph.from_spans([root, child])
        assert len(graph.nodes) == 2
        assert any(e.edge_type == "parent_child" for e in graph.edges)

    def test_get_root_nodes(self) -> None:
        root = _span(span_id="root", parent_span_id=None)
        child = _span(span_id="child", parent_span_id="root")
        graph = TraceGraph.from_spans([root, child])
        roots = graph.get_root_nodes()
        assert len(roots) == 1
        assert roots[0].span_id == "root"

    def test_get_children(self) -> None:
        root = _span(span_id="root", parent_span_id=None)
        c1 = _span(span_id="c1", parent_span_id="root", start_time=_T, end_time=_T + 1)
        c2 = _span(span_id="c2", parent_span_id="root", start_time=_T + 1, end_time=_T + 2)
        graph = TraceGraph.from_spans([root, c1, c2])
        children = graph.get_children("root")
        assert len(children) == 2
        assert {c.span_id for c in children} == {"c1", "c2"}

    def test_sequential_edges(self) -> None:
        root = _span(span_id="root", parent_span_id=None)
        c1 = _span(span_id="c1", parent_span_id="root", start_time=_T, end_time=_T + 1)
        c2 = _span(span_id="c2", parent_span_id="root", start_time=_T + 1, end_time=_T + 2)
        graph = TraceGraph.from_spans([root, c1, c2])
        seq_edges = [e for e in graph.edges if e.edge_type == "sequential"]
        assert len(seq_edges) >= 1
        assert seq_edges[0].source_span_id == "c1"
        assert seq_edges[0].target_span_id == "c2"

    def test_get_critical_path(self) -> None:
        root = _span(span_id="root", parent_span_id=None, start_time=_T, end_time=_T + 10)
        fast = _span(span_id="fast", parent_span_id="root", start_time=_T, end_time=_T + 1)
        slow = _span(span_id="slow", parent_span_id="root", start_time=_T + 1, end_time=_T + 8)
        graph = TraceGraph.from_spans([root, fast, slow])
        path = graph.get_critical_path()
        span_ids = [n.span_id for n in path]
        assert "root" in span_ids
        assert "slow" in span_ids

    def test_get_bottlenecks(self) -> None:
        fast = _span(span_id="fast", parent_span_id=None, start_time=_T, end_time=_T + 0.5)
        slow = _span(span_id="slow", parent_span_id=None, start_time=_T, end_time=_T + 5.0)
        graph = TraceGraph.from_spans([fast, slow])
        bottlenecks = graph.get_bottlenecks(threshold_ms=1000.0)
        assert len(bottlenecks) == 1
        assert bottlenecks[0].span_id == "slow"

    def test_to_dict(self) -> None:
        root = _span(span_id="root", parent_span_id=None)
        graph = TraceGraph.from_spans([root])
        d = graph.to_dict()
        assert "nodes" in d
        assert "edges" in d
        assert len(d["nodes"]) == 1

    def test_empty_graph(self) -> None:
        graph = TraceGraph.from_spans([])
        assert graph.get_root_nodes() == []
        assert graph.get_critical_path() == []
        assert graph.get_bottlenecks() == []

    def test_grades_attached_to_nodes(self) -> None:
        span = _span(span_id="s1")
        grade = SpanGrade(span_id="s1", grader_name="test", score=0.9, passed=True, evidence="ok")
        graph = TraceGraph.from_spans([span], grades=[grade])
        node = graph.nodes["s1"]
        assert len(node.grades) == 1
        assert node.grades[0].score == 0.9

    def test_node_duration_ms(self) -> None:
        node = TraceGraphNode(
            span_id="s1", operation="op", agent_path="root",
            start_time=100.0, end_time=102.5, status="ok",
        )
        assert node.duration_ms == 2500.0


# ===========================================================================
# BlameMap tests
# ===========================================================================

class TestBlameMap:
    def test_add_grades_and_compute(self) -> None:
        bmap = BlameMap()
        g1 = SpanGrade(
            span_id="s1", grader_name="routing", score=0.0, passed=False,
            evidence="wrong", failure_reason="Wrong routing",
            metadata={"agent_path": "root/support"},
        )
        bmap.add_grades("t1", [g1])
        clusters = bmap.compute()
        assert len(clusters) == 1
        assert clusters[0].grader_name == "routing"
        assert clusters[0].count == 1

    def test_no_failures(self) -> None:
        bmap = BlameMap()
        g1 = SpanGrade(span_id="s1", grader_name="routing", score=1.0, passed=True, evidence="ok")
        bmap.add_grades("t1", [g1])
        clusters = bmap.compute()
        assert clusters == []

    def test_impact_score(self) -> None:
        bmap = BlameMap()
        fail = SpanGrade(
            span_id="s1", grader_name="tool_selection", score=0.0, passed=False,
            evidence="wrong", failure_reason="Wrong tool",
            metadata={"agent_path": "root"},
        )
        ok = SpanGrade(span_id="s2", grader_name="routing", score=1.0, passed=True, evidence="ok")
        bmap.add_grades("t1", [fail])
        bmap.add_grades("t2", [ok])
        clusters = bmap.compute()
        assert len(clusters) == 1
        assert clusters[0].impact_score == pytest.approx(0.5)  # 1 failure / 2 traces

    def test_multiple_clusters(self) -> None:
        bmap = BlameMap()
        g1 = SpanGrade(
            span_id="s1", grader_name="routing", score=0.0, passed=False,
            evidence="a", failure_reason="Wrong routing",
            metadata={"agent_path": "root"},
        )
        g2 = SpanGrade(
            span_id="s2", grader_name="tool_selection", score=0.0, passed=False,
            evidence="b", failure_reason="Wrong tool",
            metadata={"agent_path": "root"},
        )
        bmap.add_grades("t1", [g1, g2])
        clusters = bmap.compute()
        assert len(clusters) == 2

    def test_get_top_clusters(self) -> None:
        bmap = BlameMap()
        for i in range(5):
            bmap.add_grades(f"t{i}", [
                SpanGrade(
                    span_id=f"s{i}", grader_name="routing", score=0.0, passed=False,
                    evidence="x", failure_reason=f"reason_{i % 2}",
                    metadata={"agent_path": "root"},
                ),
            ])
        top = bmap.get_top_clusters(n=1)
        assert len(top) == 1

    def test_trend_growing(self) -> None:
        bmap = BlameMap()
        # 1 failure in first half, 3 in second half
        base = time.time() - 100
        bmap.add_grades("t1", [
            SpanGrade(span_id="s1", grader_name="routing", score=0.0, passed=False,
                      evidence="x", failure_reason="bad", metadata={"agent_path": "root"}),
        ], timestamp=base)
        for i in range(3):
            bmap.add_grades(f"t{i+10}", [
                SpanGrade(span_id=f"s{i+10}", grader_name="routing", score=0.0, passed=False,
                          evidence="x", failure_reason="bad", metadata={"agent_path": "root"}),
            ], timestamp=base + 80)
        clusters = bmap.compute()
        assert len(clusters) == 1
        assert clusters[0].trend == "growing"

    def test_trend_shrinking(self) -> None:
        bmap = BlameMap()
        base = time.time() - 100
        for i in range(3):
            bmap.add_grades(f"t{i}", [
                SpanGrade(span_id=f"s{i}", grader_name="routing", score=0.0, passed=False,
                          evidence="x", failure_reason="bad", metadata={"agent_path": "root"}),
            ], timestamp=base)
        bmap.add_grades("t10", [
            SpanGrade(span_id="s10", grader_name="routing", score=0.0, passed=False,
                      evidence="x", failure_reason="bad", metadata={"agent_path": "root"}),
        ], timestamp=base + 80)
        clusters = bmap.compute()
        assert len(clusters) == 1
        assert clusters[0].trend == "shrinking"

    def test_trend_stable(self) -> None:
        bmap = BlameMap()
        g = SpanGrade(span_id="s1", grader_name="routing", score=0.0, passed=False,
                      evidence="x", failure_reason="bad", metadata={"agent_path": "root"})
        bmap.add_grades("t1", [g])
        clusters = bmap.compute()
        assert clusters[0].trend == "stable"

    def test_cluster_to_dict(self) -> None:
        c = BlameCluster(
            cluster_id="c1", grader_name="routing", agent_path="root",
            failure_reason="bad", count=3, total_traces=10,
            impact_score=0.3, example_trace_ids=["t1"],
            first_seen=1000.0, last_seen=2000.0, trend="stable",
        )
        d = c.to_dict()
        assert d["cluster_id"] == "c1"
        assert d["impact_score"] == 0.3

    def test_from_store(self, tmp_path: Path) -> None:
        store = TraceStore(db_path=str(tmp_path / "traces.db"))
        now = time.time()

        # Create a trace with a routing failure
        span = _span(span_id="s1", trace_id="t1", start_time=now - 10, end_time=now - 9)
        evt = _event(
            trace_id="t1",
            event_type=TraceEventType.agent_transfer.value,
            timestamp=now - 9.5,
            metadata={"from_agent": "root", "to_agent": "billing"},
        )
        _populate_store(store, [span], [evt])

        grader = TraceGrader()
        bmap = BlameMap.from_store(store, grader, window_seconds=3600,
                                   context={"expected_specialist": "orders"})
        clusters = bmap.compute()
        # Should find at least a routing failure cluster
        routing_clusters = [c for c in clusters if c.grader_name == "routing"]
        assert len(routing_clusters) >= 1
        assert routing_clusters[0].count >= 1


# ===========================================================================
# Integration: full pipeline
# ===========================================================================

class TestIntegration:
    def test_full_grading_pipeline(self, tmp_path: Path) -> None:
        """End-to-end: populate store -> grade -> build graph -> build blame map."""
        store = TraceStore(db_path=str(tmp_path / "traces.db"))
        now = time.time()

        # Trace 1: successful tool call
        s1 = _span(span_id="s1", trace_id="t1", start_time=now - 20, end_time=now - 18)
        e1 = _event(
            event_id="e1", trace_id="t1",
            event_type=TraceEventType.tool_call.value,
            timestamp=now - 19, tool_name="search",
            tool_input=json.dumps({"query": "shoes"}),
        )
        e2 = _event(
            event_id="e2", trace_id="t1",
            event_type=TraceEventType.model_response.value,
            timestamp=now - 18.5, tokens_out=50,
        )

        # Trace 2: failed routing
        s2 = _span(span_id="s2", trace_id="t2", start_time=now - 15, end_time=now - 13)
        e3 = _event(
            event_id="e3", trace_id="t2",
            event_type=TraceEventType.agent_transfer.value,
            timestamp=now - 14,
            metadata={"from_agent": "root", "to_agent": "billing"},
        )

        _populate_store(store, [s1, s2], [e1, e2, e3])

        grader = TraceGrader()

        # Grade both traces
        g1 = grader.grade_trace("t1", store, {"expected_tool": "search"})
        g2 = grader.grade_trace("t2", store, {"expected_specialist": "orders"})

        assert len(g1) > 0
        assert len(g2) > 0

        # Build graph for t1
        graph = TraceGraph.from_spans([s1], grades=g1)
        assert len(graph.nodes) == 1

        # Build blame map
        bmap = BlameMap()
        for g in g1:
            g.metadata["agent_path"] = "root/support"
        for g in g2:
            g.metadata["agent_path"] = "root"
        bmap.add_grades("t1", g1, timestamp=now - 20)
        bmap.add_grades("t2", g2, timestamp=now - 15)
        clusters = bmap.compute()

        # At least the routing failure should show up
        failure_clusters = [c for c in clusters if not c.grader_name == ""]
        assert len(failure_clusters) >= 1
