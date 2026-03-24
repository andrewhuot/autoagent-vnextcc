"""Directed graph representation of a trace.

Converts flat lists of ``TraceSpan`` objects into a graph with parent-child
and sequential edges, enabling critical-path analysis and bottleneck detection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from observer.trace_grading import SpanGrade
from observer.traces import TraceSpan


# ---------------------------------------------------------------------------
# Graph primitives
# ---------------------------------------------------------------------------

@dataclass
class TraceGraphNode:
    """Node in the trace graph (represents a span)."""

    span_id: str
    operation: str
    agent_path: str
    start_time: float
    end_time: float
    status: str
    grades: list[SpanGrade] = field(default_factory=list)

    @property
    def duration_ms(self) -> float:
        return (self.end_time - self.start_time) * 1000.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "operation": self.operation,
            "agent_path": self.agent_path,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "grades": [g.to_dict() for g in self.grades],
        }


@dataclass
class TraceGraphEdge:
    """Edge in the trace graph (parent -> child dependency)."""

    source_span_id: str
    target_span_id: str
    edge_type: str  # "parent_child", "sequential"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_span_id": self.source_span_id,
            "target_span_id": self.target_span_id,
            "edge_type": self.edge_type,
        }


# ---------------------------------------------------------------------------
# TraceGraph
# ---------------------------------------------------------------------------

class TraceGraph:
    """Directed graph representation of a trace."""

    def __init__(self, nodes: list[TraceGraphNode], edges: list[TraceGraphEdge]) -> None:
        self.nodes: dict[str, TraceGraphNode] = {n.span_id: n for n in nodes}
        self.edges: list[TraceGraphEdge] = list(edges)

    @classmethod
    def from_spans(
        cls,
        spans: list[TraceSpan],
        grades: list[SpanGrade] | None = None,
    ) -> "TraceGraph":
        """Build graph from spans and optional grades."""
        grades_by_span: dict[str, list[SpanGrade]] = {}
        if grades:
            for g in grades:
                grades_by_span.setdefault(g.span_id, []).append(g)

        nodes: list[TraceGraphNode] = []
        for span in spans:
            nodes.append(
                TraceGraphNode(
                    span_id=span.span_id,
                    operation=span.operation,
                    agent_path=span.agent_path,
                    start_time=span.start_time,
                    end_time=span.end_time,
                    status=span.status,
                    grades=grades_by_span.get(span.span_id, []),
                )
            )

        edges: list[TraceGraphEdge] = []
        span_ids = {s.span_id for s in spans}

        # Parent-child edges
        for span in spans:
            if span.parent_span_id and span.parent_span_id in span_ids:
                edges.append(
                    TraceGraphEdge(
                        source_span_id=span.parent_span_id,
                        target_span_id=span.span_id,
                        edge_type="parent_child",
                    )
                )

        # Sequential edges: siblings (same parent) ordered by start_time
        children_by_parent: dict[str | None, list[TraceSpan]] = {}
        for span in spans:
            children_by_parent.setdefault(span.parent_span_id, []).append(span)

        for parent_id, children in children_by_parent.items():
            sorted_children = sorted(children, key=lambda s: s.start_time)
            for i in range(len(sorted_children) - 1):
                edges.append(
                    TraceGraphEdge(
                        source_span_id=sorted_children[i].span_id,
                        target_span_id=sorted_children[i + 1].span_id,
                        edge_type="sequential",
                    )
                )

        return cls(nodes, edges)

    def get_root_nodes(self) -> list[TraceGraphNode]:
        """Return nodes with no incoming parent_child edges."""
        child_ids = {e.target_span_id for e in self.edges if e.edge_type == "parent_child"}
        return [n for n in self.nodes.values() if n.span_id not in child_ids]

    def get_children(self, span_id: str) -> list[TraceGraphNode]:
        """Return direct children of a node via parent_child edges."""
        child_ids = [
            e.target_span_id
            for e in self.edges
            if e.source_span_id == span_id and e.edge_type == "parent_child"
        ]
        return [self.nodes[cid] for cid in child_ids if cid in self.nodes]

    def get_critical_path(self) -> list[TraceGraphNode]:
        """Longest path by cumulative duration (greedy DFS from each root)."""
        if not self.nodes:
            return []

        # Build adjacency for parent_child edges
        children_map: dict[str, list[str]] = {}
        for edge in self.edges:
            if edge.edge_type == "parent_child":
                children_map.setdefault(edge.source_span_id, []).append(edge.target_span_id)

        def _longest_path(node_id: str) -> list[str]:
            kids = children_map.get(node_id, [])
            if not kids:
                return [node_id]
            best: list[str] = []
            for kid in kids:
                candidate = _longest_path(kid)
                candidate_duration = sum(self.nodes[nid].duration_ms for nid in candidate if nid in self.nodes)
                best_duration = sum(self.nodes[nid].duration_ms for nid in best if nid in self.nodes)
                if candidate_duration > best_duration:
                    best = candidate
            return [node_id] + best

        roots = self.get_root_nodes()
        overall_best: list[str] = []
        overall_best_dur = 0.0
        for root in roots:
            path = _longest_path(root.span_id)
            dur = sum(self.nodes[nid].duration_ms for nid in path if nid in self.nodes)
            if dur > overall_best_dur:
                overall_best = path
                overall_best_dur = dur

        return [self.nodes[nid] for nid in overall_best if nid in self.nodes]

    def get_bottlenecks(self, threshold_ms: float = 1000.0) -> list[TraceGraphNode]:
        """Nodes where duration exceeds threshold."""
        return [n for n in self.nodes.values() if n.duration_ms >= threshold_ms]

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "edges": [e.to_dict() for e in self.edges],
        }
