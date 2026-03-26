"""Conversational exploration over conversation traces.

Provides semantic search, clustering, and impact ranking for natural language
queries over the trace database. Integrates with existing BlameMap and TraceStore
modules.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator

from observer.blame_map import BlameCluster, BlameMap
from observer.traces import TraceEvent, TraceSpan, TraceStore


class EventType(str, Enum):
    """Types of events yielded during exploration."""

    thinking = "thinking"
    text = "text"
    card = "card"
    suggestions = "suggestions"
    error = "error"


@dataclass
class Event:
    """Base event emitted during exploration streaming."""

    event_type: EventType
    timestamp: float = field(default_factory=time.time)
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary for JSON serialization."""
        return {
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "data": self.data,
        }


@dataclass
class ThinkingEvent(Event):
    """Progress update during exploration."""

    def __init__(self, step: str, progress: float | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            event_type=EventType.thinking,
            data={
                "step": step,
                "progress": progress,
                "details": details or {},
            },
        )


@dataclass
class TextEvent(Event):
    """Plain text message to the user."""

    def __init__(self, content: str) -> None:
        super().__init__(
            event_type=EventType.text,
            data={"content": content},
        )


@dataclass
class CardEvent(Event):
    """Rich card presentation (cluster, conversation, metrics, etc.)."""

    def __init__(self, card_type: str, card_data: dict[str, Any]) -> None:
        super().__init__(
            event_type=EventType.card,
            data={
                "type": card_type,
                "data": card_data,
            },
        )


@dataclass
class SuggestionsEvent(Event):
    """Suggested next actions for the user."""

    def __init__(self, actions: list[str]) -> None:
        super().__init__(
            event_type=EventType.suggestions,
            data={"actions": actions},
        )


@dataclass
class ErrorEvent(Event):
    """Error encountered during exploration."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            event_type=EventType.error,
            data={
                "message": message,
                "details": details or {},
            },
        )


@dataclass
class ClusterCard:
    """Data structure for a blame cluster visualization card."""

    rank: int
    cluster_id: str
    title: str
    description: str
    count: int
    total_traces: int
    impact_score: float
    trend: str  # "growing", "stable", "shrinking"
    severity: str  # "critical", "high", "medium", "low"
    example_trace_ids: list[str]
    first_seen: float
    last_seen: float
    suggested_fix: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert cluster card to dictionary."""
        return {
            "rank": self.rank,
            "cluster_id": self.cluster_id,
            "title": self.title,
            "description": self.description,
            "count": self.count,
            "total_traces": self.total_traces,
            "impact_score": self.impact_score,
            "impact_percentage": round(self.impact_score * 100, 1),
            "trend": self.trend,
            "severity": self.severity,
            "example_trace_ids": self.example_trace_ids,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "suggested_fix": self.suggested_fix,
            "metadata": self.metadata,
        }


@dataclass
class ConversationState:
    """Maintains conversation context across turns.

    This is a placeholder for the full ConversationState that will be
    implemented in conversation.py. For now, we accept it as a parameter
    and extract what we need.
    """

    context: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)


class ConversationExplorer:
    """Natural language exploration over conversation traces.

    Provides semantic search, clustering, impact ranking, and drill-down
    capabilities for analyzing conversation data stored in TraceStore.
    """

    def __init__(
        self,
        trace_store: TraceStore | None = None,
        db_path: str = "traces.db",
    ) -> None:
        """Initialize the conversation explorer.

        Args:
            trace_store: TraceStore instance (creates new if None)
            db_path: Path to SQLite trace database
        """
        self.trace_store = trace_store or TraceStore(db_path=db_path)
        self.db_path = self.trace_store.db_path

    async def explore(
        self,
        query: str,
        conversation_state: ConversationState | None = None,
    ) -> AsyncIterator[Event]:
        """Explore conversations based on natural language query.

        Args:
            query: Natural language query (e.g., "Why are customers angry about shipping?")
            conversation_state: Current conversation context (optional)

        Yields:
            Event objects (thinking, text, card, suggestions) for streaming to UI
        """
        try:
            # Parse query intent
            query_intent = self._parse_query_intent(query)

            yield ThinkingEvent("Searching conversations...", progress=0.1)

            # Semantic search over traces
            results = await self._semantic_search(query, query_intent)

            if not results:
                yield TextEvent(f"I couldn't find any conversations matching '{query}'.")
                yield SuggestionsEvent(["Try a different query", "Show all recent conversations"])
                return

            yield ThinkingEvent(f"Found {len(results)} matching conversations", progress=0.3)

            # Cluster by root cause
            yield ThinkingEvent("Clustering by root cause...", progress=0.5)
            clusters = await self._cluster_results(results, query_intent)

            if not clusters:
                yield TextEvent(f"Found {len(results)} conversations but couldn't identify clear failure patterns.")
                yield SuggestionsEvent(["Show example conversations", "Refine query"])
                return

            # Rank by impact
            ranked_clusters = self._rank_by_impact(clusters)

            yield ThinkingEvent("Analyzing impact and trends...", progress=0.8)

            # Present findings
            yield TextEvent(
                f"I analyzed {len(results)} conversations matching '{query}'. "
                f"Found {len(ranked_clusters)} root causes:"
            )

            # Yield cluster cards
            for i, (cluster, severity) in enumerate(ranked_clusters[:5], 1):
                cluster_card = self._create_cluster_card(cluster, i, severity)
                yield CardEvent("cluster", cluster_card.to_dict())

            # Generate contextual suggestions
            suggestions = self._generate_suggestions(query, ranked_clusters, query_intent)
            yield SuggestionsEvent(suggestions)

        except Exception as e:
            yield ErrorEvent(f"Exploration failed: {str(e)}", details={"query": query})

    async def drill_down(
        self,
        cluster_id: str,
        detail_type: str = "examples",
    ) -> AsyncIterator[Event]:
        """Drill down into a specific cluster.

        Args:
            cluster_id: ID of the cluster to examine
            detail_type: Type of detail ("examples", "timeline", "fix")

        Yields:
            Event objects for streaming to UI
        """
        try:
            yield ThinkingEvent(f"Loading cluster details for {cluster_id}...")

            # Retrieve cluster from cache or recompute
            # For now, this is a placeholder
            yield TextEvent(f"Drill-down for cluster {cluster_id} (detail type: {detail_type})")
            yield SuggestionsEvent(["Back to overview", "Suggest fix", "Export data"])

        except Exception as e:
            yield ErrorEvent(f"Drill-down failed: {str(e)}", details={"cluster_id": cluster_id})

    def _parse_query_intent(self, query: str) -> dict[str, Any]:
        """Parse query to extract search intent and filters.

        Args:
            query: Natural language query

        Returns:
            Dictionary with intent, keywords, filters, etc.
        """
        intent = {
            "raw_query": query,
            "keywords": [],
            "filters": {},
            "intent_type": "general",  # general, failure_analysis, trend_analysis, comparison
            "time_window": None,
        }

        # Extract keywords (simple tokenization)
        # In production, use more sophisticated NLP or LLM-based extraction
        query_lower = query.lower()
        intent["keywords"] = [
            word.strip("?!.,")
            for word in query_lower.split()
            if len(word) > 3 and word.strip("?!.,") not in {"what", "when", "where", "why", "how", "that", "this", "with", "from", "have", "been"}
        ]

        # Detect intent type
        if any(word in query_lower for word in ["fail", "error", "wrong", "issue", "problem", "angry", "upset"]):
            intent["intent_type"] = "failure_analysis"
        elif any(word in query_lower for word in ["trend", "increasing", "growing", "decreasing"]):
            intent["intent_type"] = "trend_analysis"
        elif any(word in query_lower for word in ["compare", "vs", "versus", "difference"]):
            intent["intent_type"] = "comparison"

        # Extract time window
        if "this week" in query_lower or "last 7 days" in query_lower:
            intent["time_window"] = 7 * 86400
        elif "today" in query_lower:
            intent["time_window"] = 86400
        elif "this month" in query_lower or "last 30 days" in query_lower:
            intent["time_window"] = 30 * 86400

        # Extract specific filters (agent_path, event_type, etc.)
        # This is a simplified version - production would use LLM to extract structured filters
        if "routing" in query_lower:
            intent["filters"]["event_type_hint"] = "routing"
        if "shipping" in query_lower:
            intent["filters"]["topic_hint"] = "shipping"

        return intent

    async def _semantic_search(
        self,
        query: str,
        query_intent: dict[str, Any],
    ) -> list[tuple[str, TraceEvent, float]]:
        """Search traces using semantic similarity.

        For now, this uses keyword matching and SQL LIKE queries.
        In production, this should use embeddings + vector search.

        Args:
            query: Natural language query
            query_intent: Parsed query intent

        Returns:
            List of (trace_id, event, relevance_score) tuples
        """
        keywords = query_intent["keywords"]
        time_window = query_intent.get("time_window")

        results: list[tuple[str, TraceEvent, float]] = []

        # Build SQL query with filters
        clauses: list[str] = []
        params: list[Any] = []

        # Time filter
        if time_window:
            cutoff = time.time() - time_window
            clauses.append("timestamp >= ?")
            params.append(cutoff)

        # Keyword search (simple LIKE for now)
        # Search in: error_message, tool_input, tool_output, metadata
        if keywords:
            keyword_clauses = []
            for kw in keywords[:5]:  # Limit to 5 keywords
                keyword_clauses.append(
                    "(error_message LIKE ? OR tool_input LIKE ? OR tool_output LIKE ? OR metadata LIKE ?)"
                )
                search_term = f"%{kw}%"
                params.extend([search_term, search_term, search_term, search_term])

            if keyword_clauses:
                clauses.append(f"({' OR '.join(keyword_clauses)})")

        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT DISTINCT trace_id, event_id, event_type, timestamp, invocation_id,
                   session_id, agent_path, branch, tool_name, tool_input,
                   tool_output, latency_ms, tokens_in, tokens_out,
                   error_message, metadata
            FROM trace_events
            {where_clause}
            ORDER BY timestamp DESC
            LIMIT 1000
        """

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(sql, params).fetchall()

        # Convert rows to TraceEvent objects and compute relevance scores
        for row in rows:
            event = self._row_to_event(row)
            # Simple relevance scoring: count keyword matches
            relevance = self._compute_relevance(event, keywords)
            if relevance > 0:
                results.append((event.trace_id, event, relevance))

        # Sort by relevance descending
        results.sort(key=lambda x: x[2], reverse=True)

        # Limit to top 500 results
        return results[:500]

    def _compute_relevance(self, event: TraceEvent, keywords: list[str]) -> float:
        """Compute relevance score for an event based on keyword matches.

        Args:
            event: TraceEvent to score
            keywords: List of search keywords

        Returns:
            Relevance score (higher is more relevant)
        """
        score = 0.0

        # Combine searchable text
        searchable_text = " ".join([
            event.error_message or "",
            event.tool_input or "",
            event.tool_output or "",
            json.dumps(event.metadata),
        ]).lower()

        # Count keyword occurrences
        for kw in keywords:
            count = searchable_text.count(kw.lower())
            score += count * 1.0

        # Boost score for error events
        if event.event_type == "error":
            score *= 2.0

        return score

    async def _cluster_results(
        self,
        results: list[tuple[str, TraceEvent, float]],
        query_intent: dict[str, Any],
    ) -> list[BlameCluster]:
        """Cluster search results by root cause using existing BlameMap.

        Args:
            results: List of (trace_id, event, relevance_score) tuples
            query_intent: Parsed query intent

        Returns:
            List of BlameCluster objects
        """
        # Extract unique trace IDs from results
        trace_ids = list(set(trace_id for trace_id, _, _ in results))

        if not trace_ids:
            return []

        # Use BlameMap to cluster failures
        # We'll create a simple grader that marks all events as failures to force clustering
        bmap = BlameMap()

        for trace_id in trace_ids:
            # Get all events for this trace
            events = self.trace_store.get_trace(trace_id)
            spans = self.trace_store.get_spans(trace_id)

            # Convert events to SpanGrade-like objects for BlameMap
            # Since we don't have a real grader, we'll create synthetic grades
            from observer.trace_grading import SpanGrade

            grades: list[SpanGrade] = []

            for event in events:
                # Only create grades for error or tool_response events
                if event.event_type in ["error", "tool_response"] and event.error_message:
                    grade = SpanGrade(
                        grader_name="semantic_search",
                        span_id=event.event_id,
                        passed=False,  # Mark as failure
                        score=0.0,
                        failure_reason=event.error_message or "unspecified",
                        metadata={"agent_path": event.agent_path},
                    )
                    grades.append(grade)

            if grades:
                # Use earliest event timestamp as trace timestamp
                trace_ts = min((e.timestamp for e in events), default=time.time())
                bmap.add_grades(trace_id, grades, timestamp=trace_ts)

        # Compute clusters
        time_window = query_intent.get("time_window")
        clusters = bmap.compute(window_seconds=time_window)

        return clusters

    def _rank_by_impact(self, clusters: list[BlameCluster]) -> list[tuple[BlameCluster, str]]:
        """Rank clusters by impact score and compute severity.

        BlameMap already sorts by impact_score, but we add additional
        metadata like severity classification.

        Args:
            clusters: List of BlameCluster objects

        Returns:
            List of (cluster, severity) tuples
        """
        # For now, just return as-is (already sorted by impact_score)
        # In production, we could incorporate:
        # - Business impact scoring (customer tier, revenue impact)
        # - Severity classification (critical, high, medium, low)
        # - Trend acceleration (growing faster = higher priority)

        # Add severity classification based on impact_score
        result = []
        for cluster in clusters:
            if cluster.impact_score >= 0.2:
                severity = "critical"
            elif cluster.impact_score >= 0.1:
                severity = "high"
            elif cluster.impact_score >= 0.05:
                severity = "medium"
            else:
                severity = "low"
            result.append((cluster, severity))

        return result

    def _create_cluster_card(self, cluster: BlameCluster, rank: int, severity: str = "medium") -> ClusterCard:
        """Create a ClusterCard from a BlameCluster.

        Args:
            cluster: BlameCluster from BlameMap
            rank: Display rank (1-based)
            severity: Severity level (critical, high, medium, low)

        Returns:
            ClusterCard object
        """
        # Generate human-readable title and description
        title = self._generate_cluster_title(cluster)
        description = self._generate_cluster_description(cluster)
        suggested_fix = self._suggest_cluster_fix(cluster)

        return ClusterCard(
            rank=rank,
            cluster_id=cluster.cluster_id,
            title=title,
            description=description,
            count=cluster.count,
            total_traces=cluster.total_traces,
            impact_score=cluster.impact_score,
            trend=cluster.trend,
            severity=severity,
            example_trace_ids=cluster.example_trace_ids,
            first_seen=cluster.first_seen,
            last_seen=cluster.last_seen,
            suggested_fix=suggested_fix,
            metadata={
                "grader_name": cluster.grader_name,
                "agent_path": cluster.agent_path,
                "raw_failure_reason": cluster.failure_reason,
            },
        )

    def _generate_cluster_title(self, cluster: BlameCluster) -> str:
        """Generate human-readable title for a cluster.

        Args:
            cluster: BlameCluster to generate title for

        Returns:
            Human-readable title string
        """
        # Extract key information
        agent = cluster.agent_path.split("/")[-1] if cluster.agent_path != "unknown" else "agent"
        failure = cluster.failure_reason[:50] if cluster.failure_reason else "unspecified error"

        # Create title based on failure pattern
        if "timeout" in failure.lower():
            return f"Timeout errors in {agent}"
        elif "not found" in failure.lower() or "missing" in failure.lower():
            return f"Missing data in {agent}"
        elif "auth" in failure.lower() or "permission" in failure.lower():
            return f"Authentication failures in {agent}"
        elif "rate limit" in failure.lower():
            return f"Rate limiting issues in {agent}"
        else:
            # Generic title
            return f"{agent.title()} failures: {failure[:40]}..."

    def _generate_cluster_description(self, cluster: BlameCluster) -> str:
        """Generate human-readable description for a cluster.

        Args:
            cluster: BlameCluster to describe

        Returns:
            Human-readable description string
        """
        impact_pct = round(cluster.impact_score * 100, 1)
        trend_desc = {
            "growing": "increasing",
            "stable": "stable",
            "shrinking": "decreasing",
        }.get(cluster.trend, cluster.trend)

        desc = f"{impact_pct}% of conversations ({cluster.count}/{cluster.total_traces}) are affected. "
        desc += f"Trend: {trend_desc}. "

        # Add time information
        time_span_hours = (cluster.last_seen - cluster.first_seen) / 3600
        if time_span_hours < 1:
            desc += "First seen in the last hour."
        elif time_span_hours < 24:
            desc += f"First seen {int(time_span_hours)} hours ago."
        else:
            desc += f"First seen {int(time_span_hours / 24)} days ago."

        return desc

    def _suggest_cluster_fix(self, cluster: BlameCluster) -> str | None:
        """Suggest a potential fix for a cluster.

        Args:
            cluster: BlameCluster to analyze

        Returns:
            Suggested fix description or None
        """
        failure = cluster.failure_reason.lower()

        # Pattern matching for common fixes
        if "timeout" in failure:
            return "Increase timeout threshold or optimize slow operations"
        elif "rate limit" in failure:
            return "Implement request throttling or upgrade API tier"
        elif "not found" in failure or "missing" in failure:
            return "Add validation checks and fallback handling"
        elif "auth" in failure or "permission" in failure:
            return "Review authentication flow and token refresh logic"
        elif "routing" in failure:
            return "Refine routing rules or add disambiguation logic"
        elif "tool" in failure:
            return "Fix tool integration or add error recovery"

        return None

    def _generate_suggestions(
        self,
        query: str,
        clusters: list[tuple[BlameCluster, str]],
        query_intent: dict[str, Any],
    ) -> list[str]:
        """Generate contextual suggestions for next actions.

        Args:
            query: Original query
            clusters: Ranked clusters with severity
            query_intent: Parsed query intent

        Returns:
            List of suggested action strings
        """
        suggestions = []

        if clusters:
            # Top cluster drill-down
            top_cluster, top_severity = clusters[0]
            agent = top_cluster.agent_path.split("/")[-1]
            suggestions.append(f"Tell me more about the {agent} failures")

            # Fix suggestion if available
            top_card = self._create_cluster_card(top_cluster, 1, top_severity)
            if top_card.suggested_fix:
                suggestions.append("Fix the top issue")

            # Comparison suggestion
            if len(clusters) > 1:
                suggestions.append("Compare top 2 issues")

        # Show examples
        suggestions.append("Show example conversations")

        # Time-based suggestions
        if query_intent.get("time_window"):
            suggestions.append("Compare to previous period")
        else:
            suggestions.append("Show trends over time")

        return suggestions[:4]  # Limit to 4 suggestions

    @staticmethod
    def _row_to_event(row: tuple) -> TraceEvent:
        """Convert database row to TraceEvent.

        Args:
            row: Database row tuple

        Returns:
            TraceEvent object
        """
        return TraceEvent(
            event_id=row[0],
            trace_id=row[1],
            event_type=row[2],
            timestamp=row[3],
            invocation_id=row[4],
            session_id=row[5],
            agent_path=row[6],
            branch=row[7],
            tool_name=row[8],
            tool_input=row[9],
            tool_output=row[10],
            latency_ms=row[11],
            tokens_in=row[12],
            tokens_out=row[13],
            error_message=row[14],
            metadata=json.loads(row[15]) if row[15] else {},
        )
