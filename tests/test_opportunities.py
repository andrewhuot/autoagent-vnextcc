"""Unit tests for the opportunity queue and failure clusterer."""

from __future__ import annotations

import time
from pathlib import Path

from observer.opportunities import (
    FailureClusterer,
    FailureFamily,
    OptimizationOpportunity,
    OpportunityQueue,
)


def _make_opportunity(
    opportunity_id: str = "opp-1",
    priority_score: float = 0.5,
    status: str = "open",
    failure_family: str = FailureFamily.tool_error.value,
) -> OptimizationOpportunity:
    """Build a minimal OptimizationOpportunity for tests."""
    return OptimizationOpportunity(
        opportunity_id=opportunity_id,
        created_at=time.time(),
        cluster_id="cluster-1",
        failure_family=failure_family,
        affected_agent_path="root/support",
        affected_surface_candidates=["tool_definitions"],
        severity=0.5,
        prevalence=0.3,
        recency=1.0,
        business_impact=0.4,
        sample_trace_ids=["trace-1"],
        recommended_operator_families=["tool_description_edit"],
        priority_score=priority_score,
        status=status,
        resolution_experiment_id=None,
    )


def test_opportunity_queue_push_and_pop(tmp_path: Path) -> None:
    """Push 3 items with different priorities; pop returns highest priority first."""
    queue = OpportunityQueue(db_path=str(tmp_path / "opp.db"))
    queue.push(_make_opportunity(opportunity_id="low", priority_score=0.2))
    queue.push(_make_opportunity(opportunity_id="high", priority_score=0.9))
    queue.push(_make_opportunity(opportunity_id="mid", priority_score=0.5))

    top = queue.pop_top(n=1)
    assert len(top) == 1
    assert top[0].opportunity_id == "high"


def test_opportunity_queue_list_open(tmp_path: Path) -> None:
    """list_open should return only open items."""
    queue = OpportunityQueue(db_path=str(tmp_path / "opp.db"))
    queue.push(_make_opportunity(opportunity_id="o1", status="open"))
    queue.push(_make_opportunity(opportunity_id="o2", status="resolved"))
    queue.push(_make_opportunity(opportunity_id="o3", status="open"))

    open_items = queue.list_open()
    assert len(open_items) == 2
    assert all(o.status == "open" for o in open_items)


def test_opportunity_queue_update_status(tmp_path: Path) -> None:
    """update_status should change an opportunity's status to resolved."""
    queue = OpportunityQueue(db_path=str(tmp_path / "opp.db"))
    queue.push(_make_opportunity(opportunity_id="opp-resolve"))

    queue.update_status("opp-resolve", "resolved", resolution_experiment_id="exp-42")

    item = queue.get("opp-resolve")
    assert item is not None
    assert item.status == "resolved"
    assert item.resolution_experiment_id == "exp-42"


def test_opportunity_queue_count_open(tmp_path: Path) -> None:
    """count_open should return the number of open opportunities."""
    queue = OpportunityQueue(db_path=str(tmp_path / "opp.db"))
    queue.push(_make_opportunity(opportunity_id="o1", status="open"))
    queue.push(_make_opportunity(opportunity_id="o2", status="open"))
    queue.push(_make_opportunity(opportunity_id="o3", status="resolved"))

    assert queue.count_open() == 2


def test_failure_clusterer_maps_buckets() -> None:
    """FailureClusterer should map bucket counts to opportunities with correct families/operators."""

    class FakeRecord:
        conversation_id = "conv-1"
        specialist_used = "support"

    clusterer = FailureClusterer()
    records = [FakeRecord(), FakeRecord(), FakeRecord(), FakeRecord(), FakeRecord()]
    buckets = {"tool_failure": 3, "routing_error": 2}

    opportunities = clusterer.cluster(records, buckets)

    assert len(opportunities) == 2
    families = {o.failure_family for o in opportunities}
    assert FailureFamily.tool_error.value in families
    assert FailureFamily.routing_failure.value in families

    # Check operator recommendations
    tool_opp = [o for o in opportunities if o.failure_family == FailureFamily.tool_error.value][0]
    assert "tool_description_edit" in tool_opp.recommended_operator_families

    routing_opp = [o for o in opportunities if o.failure_family == FailureFamily.routing_failure.value][0]
    assert "routing_edit" in routing_opp.recommended_operator_families

    # Sorted by priority_score descending
    assert opportunities[0].priority_score >= opportunities[1].priority_score


def test_failure_clusterer_empty_buckets() -> None:
    """No failures should produce no opportunities."""
    clusterer = FailureClusterer()
    opportunities = clusterer.cluster([], {})
    assert opportunities == []

    # Also test with zero-count buckets
    opportunities = clusterer.cluster([], {"tool_failure": 0, "routing_error": 0})
    assert opportunities == []
