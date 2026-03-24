"""Root-cause clustering via blame maps.

Aggregates span grades across traces into ``BlameCluster`` objects ranked by
impact score (severity x frequency).  Supports trend detection over a time
window.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from observer.trace_grading import SpanGrade, TraceGrader
from observer.traces import TraceStore


# ---------------------------------------------------------------------------
# BlameCluster
# ---------------------------------------------------------------------------

@dataclass
class BlameCluster:
    """A cluster of related failures."""

    cluster_id: str
    grader_name: str
    agent_path: str
    failure_reason: str
    count: int
    total_traces: int
    impact_score: float  # count / total_traces
    example_trace_ids: list[str]
    first_seen: float  # epoch
    last_seen: float
    trend: str  # "growing", "shrinking", "stable"

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "grader_name": self.grader_name,
            "agent_path": self.agent_path,
            "failure_reason": self.failure_reason,
            "count": self.count,
            "total_traces": self.total_traces,
            "impact_score": self.impact_score,
            "example_trace_ids": self.example_trace_ids,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "trend": self.trend,
        }


# ---------------------------------------------------------------------------
# BlameMap
# ---------------------------------------------------------------------------

class BlameMap:
    """Aggregate span grades across traces into blame clusters."""

    def __init__(self) -> None:
        self._grades: list[tuple[str, SpanGrade, float]] = []  # (trace_id, grade, timestamp)
        self._trace_ids: set[str] = set()

    def add_grades(self, trace_id: str, grades: list[SpanGrade], timestamp: float | None = None) -> None:
        """Add graded spans from a trace."""
        ts = timestamp or time.time()
        self._trace_ids.add(trace_id)
        for g in grades:
            self._grades.append((trace_id, g, ts))

    def compute(self, window_seconds: float | None = None) -> list[BlameCluster]:
        """Compute blame clusters from accumulated grades.

        Groups failures by (grader_name, agent_path, failure_reason).
        Ranks by impact_score = count / total_traces.
        Computes trend by comparing first_half vs second_half counts.
        """
        now = time.time()

        # Filter by window
        if window_seconds is not None:
            cutoff = now - window_seconds
            entries = [(tid, g, ts) for tid, g, ts in self._grades if ts >= cutoff]
            trace_ids = {tid for tid, _, ts in entries if ts >= cutoff}
        else:
            entries = list(self._grades)
            trace_ids = set(self._trace_ids)

        total_traces = len(trace_ids) or 1

        # Only consider failures
        failures = [(tid, g, ts) for tid, g, ts in entries if not g.passed]
        if not failures:
            return []

        # Group by (grader_name, agent_path_from_metadata_or_span, failure_reason)
        clusters_raw: dict[tuple[str, str, str], list[tuple[str, float]]] = {}
        for tid, g, ts in failures:
            # Use span_id prefix as proxy for agent_path (stored in metadata if available)
            agent_path = g.metadata.get("agent_path", "unknown")
            reason = g.failure_reason or "unspecified"
            key = (g.grader_name, agent_path, reason)
            clusters_raw.setdefault(key, []).append((tid, ts))

        # Build clusters
        clusters: list[BlameCluster] = []
        for (grader_name, agent_path, failure_reason), items in clusters_raw.items():
            count = len(items)
            example_trace_ids = sorted(set(tid for tid, _ in items))[:5]
            timestamps = [ts for _, ts in items]
            first_seen = min(timestamps)
            last_seen = max(timestamps)

            # Trend: compare first-half vs second-half of the window
            mid = (first_seen + last_seen) / 2.0 if first_seen != last_seen else first_seen
            first_half = sum(1 for _, ts in items if ts <= mid)
            second_half = sum(1 for _, ts in items if ts > mid)
            if first_seen == last_seen or count <= 1:
                trend = "stable"
            elif second_half > first_half:
                trend = "growing"
            elif second_half < first_half:
                trend = "shrinking"
            else:
                trend = "stable"

            clusters.append(
                BlameCluster(
                    cluster_id=uuid.uuid4().hex[:12],
                    grader_name=grader_name,
                    agent_path=agent_path,
                    failure_reason=failure_reason,
                    count=count,
                    total_traces=total_traces,
                    impact_score=count / total_traces,
                    example_trace_ids=example_trace_ids,
                    first_seen=first_seen,
                    last_seen=last_seen,
                    trend=trend,
                )
            )

        # Sort by impact_score descending
        clusters.sort(key=lambda c: c.impact_score, reverse=True)
        return clusters

    def get_top_clusters(self, n: int = 10) -> list[BlameCluster]:
        """Return top N blame clusters by impact score."""
        return self.compute()[:n]

    @staticmethod
    def from_store(
        store: TraceStore,
        grader: TraceGrader,
        window_seconds: float = 86400,
        context: dict[str, Any] | None = None,
    ) -> "BlameMap":
        """Build blame map from trace store over a time window."""
        context = context or {}
        cutoff = time.time() - window_seconds

        # Get distinct trace_ids from spans within the window
        with sqlite3.connect(store.db_path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT trace_id FROM trace_spans WHERE start_time >= ? ORDER BY start_time DESC",
                (cutoff,),
            ).fetchall()

        trace_ids = [row[0] for row in rows]

        bmap = BlameMap()
        for trace_id in trace_ids:
            grades = grader.grade_trace(trace_id, store, context)
            # Enrich grades with agent_path from spans
            spans = store.get_spans(trace_id)
            span_agent_paths: dict[str, str] = {s.span_id: s.agent_path for s in spans}
            for g in grades:
                if "agent_path" not in g.metadata:
                    g.metadata["agent_path"] = span_agent_paths.get(g.span_id, "unknown")

            # Use earliest span start_time as the trace timestamp
            trace_ts = min((s.start_time for s in spans), default=time.time())
            bmap.add_grades(trace_id, grades, timestamp=trace_ts)

        return bmap
