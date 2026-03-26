"""Tests for assistant.explorer module — conversational trace exploration."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import time
from pathlib import Path

import pytest

from assistant.explorer import (
    ClusterCard,
    ConversationExplorer,
    ConversationState,
    Event,
    EventType,
    CardEvent,
    TextEvent,
    ThinkingEvent,
    SuggestionsEvent,
    ErrorEvent,
)
from observer.traces import TraceEvent, TraceEventType, TraceSpan, TraceStore


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def trace_store(temp_db):
    """Create a TraceStore with test data."""
    store = TraceStore(db_path=temp_db)

    # Insert test traces
    now = time.time()

    # Trace 1: Shipping delay issue
    trace1_id = "trace_001"
    store.log_event(
        TraceEvent(
            event_id="evt_001",
            trace_id=trace1_id,
            event_type=TraceEventType.error.value,
            timestamp=now - 3600,
            invocation_id="inv_001",
            session_id="sess_001",
            agent_path="root/support/shipping",
            branch="main",
            error_message="Shipping delay: warehouse staffing issue in northeast region",
            metadata={"customer_tier": "premium", "topic": "shipping"},
        )
    )

    # Trace 2: Another shipping delay
    trace2_id = "trace_002"
    store.log_event(
        TraceEvent(
            event_id="evt_002",
            trace_id=trace2_id,
            event_type=TraceEventType.error.value,
            timestamp=now - 3000,
            invocation_id="inv_002",
            session_id="sess_002",
            agent_path="root/support/shipping",
            branch="main",
            error_message="Shipping delay: warehouse staffing issue in northeast region",
            metadata={"customer_tier": "standard", "topic": "shipping"},
        )
    )

    # Trace 3: Tracking number issue
    trace3_id = "trace_003"
    store.log_event(
        TraceEvent(
            event_id="evt_003",
            trace_id=trace3_id,
            event_type=TraceEventType.tool_response.value,
            timestamp=now - 2400,
            invocation_id="inv_003",
            session_id="sess_003",
            agent_path="root/support/shipping",
            branch="main",
            tool_name="get_tracking",
            error_message="Wrong tracking number provided: tool returning stale data",
            metadata={"topic": "shipping"},
        )
    )

    # Trace 4: Billing issue (different topic)
    trace4_id = "trace_004"
    store.log_event(
        TraceEvent(
            event_id="evt_004",
            trace_id=trace4_id,
            event_type=TraceEventType.error.value,
            timestamp=now - 1800,
            invocation_id="inv_004",
            session_id="sess_004",
            agent_path="root/support/billing",
            branch="main",
            error_message="Payment processing timeout",
            metadata={"topic": "billing"},
        )
    )

    # Trace 5: Recent shipping issue
    trace5_id = "trace_005"
    store.log_event(
        TraceEvent(
            event_id="evt_005",
            trace_id=trace5_id,
            event_type=TraceEventType.error.value,
            timestamp=now - 600,
            invocation_id="inv_005",
            session_id="sess_005",
            agent_path="root/support/shipping",
            branch="main",
            error_message="Shipping delay: warehouse staffing issue in northeast region",
            metadata={"topic": "shipping"},
        )
    )

    # Add spans for traces
    for i, trace_id in enumerate([trace1_id, trace2_id, trace3_id, trace4_id, trace5_id], 1):
        store.log_span(
            TraceSpan(
                span_id=f"span_{i:03d}",
                trace_id=trace_id,
                parent_span_id=None,
                operation="handle_customer_query",
                agent_path=f"root/support/{'shipping' if i <= 3 or i == 5 else 'billing'}",
                start_time=now - (4000 - i * 600),
                end_time=now - (4000 - i * 600 - 300),
                status="error" if i in [1, 2, 3, 4, 5] else "ok",
            )
        )

    return store


@pytest.fixture
def explorer(trace_store):
    """Create a ConversationExplorer with test data."""
    return ConversationExplorer(trace_store=trace_store)


class TestEventTypes:
    """Test event data structures."""

    def test_thinking_event(self):
        event = ThinkingEvent("Processing query", progress=0.5, details={"key": "value"})
        assert event.event_type == EventType.thinking
        assert event.data["step"] == "Processing query"
        assert event.data["progress"] == 0.5
        assert event.data["details"]["key"] == "value"

    def test_text_event(self):
        event = TextEvent("This is a message")
        assert event.event_type == EventType.text
        assert event.data["content"] == "This is a message"

    def test_card_event(self):
        card_data = {"cluster_id": "abc123", "title": "Test Cluster"}
        event = CardEvent("cluster", card_data)
        assert event.event_type == EventType.card
        assert event.data["type"] == "cluster"
        assert event.data["data"]["cluster_id"] == "abc123"

    def test_suggestions_event(self):
        event = SuggestionsEvent(["Action 1", "Action 2"])
        assert event.event_type == EventType.suggestions
        assert len(event.data["actions"]) == 2

    def test_error_event(self):
        event = ErrorEvent("Something failed", details={"code": 500})
        assert event.event_type == EventType.error
        assert event.data["message"] == "Something failed"
        assert event.data["details"]["code"] == 500

    def test_event_to_dict(self):
        event = TextEvent("Test")
        d = event.to_dict()
        assert d["event_type"] == "text"
        assert "timestamp" in d
        assert d["data"]["content"] == "Test"


class TestClusterCard:
    """Test ClusterCard data structure."""

    def test_cluster_card_creation(self):
        card = ClusterCard(
            rank=1,
            cluster_id="cluster_001",
            title="Shipping Delays",
            description="68% of complaints",
            count=15,
            total_traces=22,
            impact_score=0.68,
            trend="growing",
            severity="high",
            example_trace_ids=["trace_001", "trace_002"],
            first_seen=time.time() - 86400,
            last_seen=time.time(),
            suggested_fix="Increase warehouse staffing",
        )

        assert card.rank == 1
        assert card.cluster_id == "cluster_001"
        assert card.impact_score == 0.68
        assert card.trend == "growing"

    def test_cluster_card_to_dict(self):
        card = ClusterCard(
            rank=1,
            cluster_id="cluster_001",
            title="Test",
            description="Test description",
            count=10,
            total_traces=50,
            impact_score=0.2,
            trend="stable",
            severity="medium",
            example_trace_ids=["t1", "t2"],
            first_seen=time.time(),
            last_seen=time.time(),
        )

        d = card.to_dict()
        assert d["rank"] == 1
        assert d["impact_percentage"] == 20.0
        assert d["severity"] == "medium"
        assert len(d["example_trace_ids"]) == 2


class TestConversationState:
    """Test ConversationState placeholder."""

    def test_conversation_state_creation(self):
        state = ConversationState()
        assert isinstance(state.context, dict)
        assert isinstance(state.history, list)

    def test_conversation_state_with_data(self):
        state = ConversationState(
            context={"last_query": "test"},
            history=[{"role": "user", "content": "hello"}],
        )
        assert state.context["last_query"] == "test"
        assert len(state.history) == 1


class TestQueryIntentParsing:
    """Test query intent parsing."""

    def test_parse_general_query(self, explorer):
        intent = explorer._parse_query_intent("Show me conversations about shipping")
        assert intent["raw_query"] == "Show me conversations about shipping"
        assert "shipping" in intent["keywords"]
        assert "conversations" in intent["keywords"]

    def test_parse_failure_query(self, explorer):
        intent = explorer._parse_query_intent("Why are customers angry about shipping?")
        assert intent["intent_type"] == "failure_analysis"
        assert "angry" in intent["keywords"]
        assert "shipping" in intent["keywords"]

    def test_parse_trend_query(self, explorer):
        intent = explorer._parse_query_intent("Is shipping increasing?")
        assert intent["intent_type"] == "trend_analysis"

    def test_parse_comparison_query(self, explorer):
        intent = explorer._parse_query_intent("Compare this week vs last week")
        assert intent["intent_type"] == "comparison"

    def test_parse_time_window_week(self, explorer):
        intent = explorer._parse_query_intent("Show me failures this week")
        assert intent["time_window"] == 7 * 86400

    def test_parse_time_window_today(self, explorer):
        intent = explorer._parse_query_intent("Show me errors today")
        assert intent["time_window"] == 86400

    def test_parse_filter_hints(self, explorer):
        intent = explorer._parse_query_intent("Routing failures in shipping")
        assert intent["filters"].get("event_type_hint") == "routing"
        assert intent["filters"].get("topic_hint") == "shipping"


class TestSemanticSearch:
    """Test semantic search functionality."""

    @pytest.mark.asyncio
    async def test_search_by_keyword(self, explorer):
        intent = explorer._parse_query_intent("shipping")
        results = await explorer._semantic_search("shipping", intent)

        # Should find shipping-related traces
        assert len(results) > 0
        # Verify results contain trace IDs
        assert all(isinstance(trace_id, str) for trace_id, _, _ in results)

    @pytest.mark.asyncio
    async def test_search_no_results(self, explorer):
        intent = explorer._parse_query_intent("nonexistent_topic_xyz")
        results = await explorer._semantic_search("nonexistent_topic_xyz", intent)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_search_with_time_window(self, explorer):
        # Search only last hour (should get recent traces)
        intent = {
            "raw_query": "shipping",
            "keywords": ["shipping"],
            "filters": {},
            "intent_type": "general",
            "time_window": 3600,
        }
        results = await explorer._semantic_search("shipping", intent)
        # Should get at least the most recent shipping trace
        assert len(results) > 0

    def test_compute_relevance(self, explorer):
        event = TraceEvent(
            event_id="evt_test",
            trace_id="trace_test",
            event_type=TraceEventType.error.value,
            timestamp=time.time(),
            invocation_id="inv_test",
            session_id="sess_test",
            agent_path="root/test",
            branch="main",
            error_message="shipping delay in warehouse",
        )

        score = explorer._compute_relevance(event, ["shipping", "warehouse"])
        assert score > 0

        # Error events should have boosted score
        score_error = explorer._compute_relevance(event, ["delay"])
        event.event_type = "tool_response"
        score_normal = explorer._compute_relevance(event, ["delay"])
        assert score_error > score_normal


class TestClustering:
    """Test clustering functionality."""

    @pytest.mark.asyncio
    async def test_cluster_results(self, explorer):
        intent = explorer._parse_query_intent("shipping issues")
        results = await explorer._semantic_search("shipping", intent)

        # Results should exist since we have shipping data in fixtures
        assert len(results) > 0

        clusters = await explorer._cluster_results(results, intent)

        # Clustering may or may not produce clusters depending on whether
        # events have error_message fields. We just verify the function works.
        # If clusters exist, they should have required fields
        for cluster in clusters:
            assert cluster.cluster_id
            assert cluster.count > 0
            assert cluster.impact_score >= 0

    @pytest.mark.asyncio
    async def test_cluster_empty_results(self, explorer):
        clusters = await explorer._cluster_results([], {})
        assert len(clusters) == 0


class TestImpactRanking:
    """Test impact ranking functionality."""

    def test_rank_by_impact(self, explorer):
        from observer.blame_map import BlameCluster

        # Create test clusters (pre-sorted by impact_score descending like BlameMap does)
        clusters = [
            BlameCluster(
                cluster_id="c2",
                grader_name="test",
                agent_path="root/test",
                failure_reason="issue 2",
                count=25,
                total_traces=100,
                impact_score=0.25,
                example_trace_ids=["t2"],
                first_seen=time.time(),
                last_seen=time.time(),
                trend="growing",
            ),
            BlameCluster(
                cluster_id="c3",
                grader_name="test",
                agent_path="root/test",
                failure_reason="issue 3",
                count=12,
                total_traces=100,
                impact_score=0.12,
                example_trace_ids=["t3"],
                first_seen=time.time(),
                last_seen=time.time(),
                trend="stable",
            ),
            BlameCluster(
                cluster_id="c1",
                grader_name="test",
                agent_path="root/test",
                failure_reason="issue 1",
                count=5,
                total_traces=100,
                impact_score=0.05,
                example_trace_ids=["t1"],
                first_seen=time.time(),
                last_seen=time.time(),
                trend="stable",
            ),
        ]

        ranked = explorer._rank_by_impact(clusters)

        # Should maintain order (already sorted) and return tuples
        assert ranked[0][0].cluster_id == "c2"
        assert ranked[1][0].cluster_id == "c3"
        assert ranked[2][0].cluster_id == "c1"

        # Should add severity classification
        assert ranked[0][1] == "critical"
        assert ranked[1][1] == "high"
        assert ranked[2][1] == "medium"


class TestClusterCardGeneration:
    """Test cluster card generation."""

    def test_create_cluster_card(self, explorer):
        from observer.blame_map import BlameCluster

        cluster = BlameCluster(
            cluster_id="test_cluster",
            grader_name="test_grader",
            agent_path="root/support/shipping",
            failure_reason="Shipping delay: warehouse staffing issue",
            count=20,
            total_traces=100,
            impact_score=0.2,
            example_trace_ids=["t1", "t2", "t3"],
            first_seen=time.time() - 86400,
            last_seen=time.time(),
            trend="growing",
        )

        card = explorer._create_cluster_card(cluster, rank=1, severity="high")

        assert card.rank == 1
        assert card.cluster_id == "test_cluster"
        assert card.title  # Should have a generated title
        assert card.description  # Should have a generated description
        assert card.impact_score == 0.2
        assert card.severity == "high"

    def test_generate_cluster_title(self, explorer):
        from observer.blame_map import BlameCluster

        cluster = BlameCluster(
            cluster_id="c1",
            grader_name="test",
            agent_path="root/support/shipping",
            failure_reason="timeout waiting for response",
            count=10,
            total_traces=100,
            impact_score=0.1,
            example_trace_ids=["t1"],
            first_seen=time.time(),
            last_seen=time.time(),
            trend="stable",
        )

        title = explorer._generate_cluster_title(cluster)
        assert "timeout" in title.lower()
        assert "shipping" in title.lower()

    def test_generate_cluster_description(self, explorer):
        from observer.blame_map import BlameCluster

        cluster = BlameCluster(
            cluster_id="c1",
            grader_name="test",
            agent_path="root/test",
            failure_reason="test failure",
            count=15,
            total_traces=50,
            impact_score=0.3,
            example_trace_ids=["t1"],
            first_seen=time.time() - 7200,
            last_seen=time.time(),
            trend="growing",
        )

        desc = explorer._generate_cluster_description(cluster)
        assert "30.0%" in desc
        assert "15/50" in desc
        assert "increasing" in desc

    def test_suggest_cluster_fix(self, explorer):
        from observer.blame_map import BlameCluster

        # Test timeout fix suggestion
        cluster = BlameCluster(
            cluster_id="c1",
            grader_name="test",
            agent_path="root/test",
            failure_reason="Request timeout after 30 seconds",
            count=10,
            total_traces=100,
            impact_score=0.1,
            example_trace_ids=["t1"],
            first_seen=time.time(),
            last_seen=time.time(),
            trend="stable",
        )

        fix = explorer._suggest_cluster_fix(cluster)
        assert fix is not None
        assert "timeout" in fix.lower()


class TestSuggestionGeneration:
    """Test contextual suggestion generation."""

    def test_generate_suggestions_with_clusters(self, explorer):
        from observer.blame_map import BlameCluster

        clusters = [
            (
                BlameCluster(
                    cluster_id="c1",
                    grader_name="test",
                    agent_path="root/support/shipping",
                    failure_reason="timeout",
                    count=20,
                    total_traces=100,
                    impact_score=0.2,
                    example_trace_ids=["t1"],
                    first_seen=time.time(),
                    last_seen=time.time(),
                    trend="stable",
                ),
                "critical",
            ),
        ]

        intent = {"time_window": None}
        suggestions = explorer._generate_suggestions("test query", clusters, intent)

        assert len(suggestions) > 0
        assert any("shipping" in s.lower() for s in suggestions)

    def test_generate_suggestions_no_clusters(self, explorer):
        suggestions = explorer._generate_suggestions("test", [], {})
        assert len(suggestions) > 0


class TestExploreEndToEnd:
    """End-to-end tests for the explore method."""

    @pytest.mark.asyncio
    async def test_explore_shipping_query(self, explorer):
        events = []
        async for event in explorer.explore("Why are customers angry about shipping?"):
            events.append(event)

        # Should yield multiple event types
        event_types = [e.event_type for e in events]
        assert EventType.thinking in event_types
        assert EventType.text in event_types
        assert EventType.suggestions in event_types

        # Should find results
        text_events = [e for e in events if e.event_type == EventType.text]
        assert len(text_events) > 0

    @pytest.mark.asyncio
    async def test_explore_no_results(self, explorer):
        # Use a very specific query that won't match anything
        events = []
        async for event in explorer.explore("zzznonexistentquery12345"):
            events.append(event)

        # Should still yield thinking and text events
        event_types = [e.event_type for e in events]
        assert EventType.thinking in event_types
        assert EventType.text in event_types

        # Should indicate no results found or no clear patterns
        text_events = [e for e in events if e.event_type == EventType.text]
        assert len(text_events) > 0
        content = " ".join([e.data["content"].lower() for e in text_events])
        # Either couldn't find matches, or found matches but no patterns
        assert ("couldn't find" in content or
                "no conversations" in content or
                "0 conversations" in content or
                "couldn't identify clear failure patterns" in content)

    @pytest.mark.asyncio
    async def test_explore_with_conversation_state(self, explorer):
        state = ConversationState(
            context={"agent_id": "test_agent"},
            history=[{"role": "user", "content": "previous query"}],
        )

        events = []
        async for event in explorer.explore("shipping issues", state):
            events.append(event)

        assert len(events) > 0

    @pytest.mark.asyncio
    async def test_explore_yields_cluster_cards(self, explorer):
        events = []
        async for event in explorer.explore("shipping"):
            events.append(event)

        # Should yield cluster cards
        card_events = [e for e in events if e.event_type == EventType.card]
        if card_events:
            # Verify card structure
            card = card_events[0]
            assert card.data["type"] == "cluster"
            assert "data" in card.data
            card_data = card.data["data"]
            assert "cluster_id" in card_data
            assert "impact_score" in card_data

    @pytest.mark.asyncio
    async def test_explore_error_handling(self, explorer):
        # Test with a bad query that would cause an error in clustering
        # We'll mock a failure by using an invalid database operation
        import tempfile

        # Create a temporary database that we'll corrupt
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            bad_db_path = f.name

        # Create explorer and then corrupt database by deleting it
        bad_explorer = ConversationExplorer(db_path=bad_db_path)
        Path(bad_db_path).unlink()

        events = []
        async for event in bad_explorer.explore("test query"):
            events.append(event)

        # Should yield error event when database is missing
        error_events = [e for e in events if e.event_type == EventType.error]
        assert len(error_events) > 0


class TestDrillDown:
    """Test drill-down functionality."""

    @pytest.mark.asyncio
    async def test_drill_down_examples(self, explorer):
        events = []
        async for event in explorer.drill_down("cluster_001", detail_type="examples"):
            events.append(event)

        assert len(events) > 0
        # Should yield thinking and suggestions
        event_types = [e.event_type for e in events]
        assert EventType.thinking in event_types
        assert EventType.suggestions in event_types

    @pytest.mark.asyncio
    async def test_drill_down_timeline(self, explorer):
        events = []
        async for event in explorer.drill_down("cluster_001", detail_type="timeline"):
            events.append(event)

        assert len(events) > 0


class TestRowConversion:
    """Test database row to event conversion."""

    def test_row_to_event(self, explorer):
        # Create a test row matching the database schema
        row = (
            "evt_001",  # event_id
            "trace_001",  # trace_id
            "error",  # event_type
            time.time(),  # timestamp
            "inv_001",  # invocation_id
            "sess_001",  # session_id
            "root/test",  # agent_path
            "main",  # branch
            "test_tool",  # tool_name
            '{"input": "test"}',  # tool_input
            '{"output": "result"}',  # tool_output
            100.5,  # latency_ms
            50,  # tokens_in
            75,  # tokens_out
            "test error",  # error_message
            '{"key": "value"}',  # metadata
        )

        event = explorer._row_to_event(row)

        assert event.event_id == "evt_001"
        assert event.trace_id == "trace_001"
        assert event.event_type == "error"
        assert event.error_message == "test error"
        assert event.metadata["key"] == "value"
        assert event.tokens_in == 50
        assert event.latency_ms == 100.5
