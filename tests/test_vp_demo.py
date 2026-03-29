"""Tests for VP demo functionality."""

from __future__ import annotations


from evals.vp_demo_data import (
    SyntheticDataset,
    generate_vp_demo_dataset,
    get_vp_demo_summary,
    seed_demo_data,
    seed_optimization_history,
    seed_trace_demo_data,
)
from logger.store import ConversationRecord, ConversationStore
from observer.traces import TraceStore
from optimizer.memory import OptimizationMemory


def test_vp_demo_data_deterministic() -> None:
    """VP demo data is deterministic with fixed seed."""
    ds1 = generate_vp_demo_dataset(seed=42)
    ds2 = generate_vp_demo_dataset(seed=42)

    assert len(ds1.conversations) == len(ds2.conversations)
    assert len(ds1.conversations) == 41

    # Check first and last conversation match
    assert ds1.conversations[0].user_message == ds2.conversations[0].user_message
    assert ds1.conversations[0].agent_response == ds2.conversations[0].agent_response
    assert ds1.conversations[-1].user_message == ds2.conversations[-1].user_message
    assert ds1.conversations[-1].agent_response == ds2.conversations[-1].agent_response


def test_vp_demo_data_has_expected_failures() -> None:
    """VP demo data includes all required failure types."""
    ds = generate_vp_demo_dataset(seed=42)

    # Count failures by looking at error messages and specialist routing
    billing_misroutes = sum(
        1 for c in ds.conversations
        if c.specialist_used == "tech_support_agent"
        and c.outcome == "fail"
        and ("billing" in c.error_message.lower() or
             "refund" in c.user_message.lower() or
             "invoice" in c.user_message.lower() or
             "charge" in c.user_message.lower() or
             "payment" in c.user_message.lower())
    )

    safety_violations = sum(
        1 for c in ds.conversations
        if len(c.safety_flags) > 0
    )

    high_latency = sum(
        1 for c in ds.conversations
        if c.latency_ms > 5000
    )

    successful = sum(
        1 for c in ds.conversations
        if c.outcome == "success"
    )

    # At least the specified minimums from the brief
    assert billing_misroutes >= 10, f"Expected >=10 billing misroutes, got {billing_misroutes}"
    assert safety_violations >= 3, f"Expected >=3 safety violations, got {safety_violations}"
    assert high_latency >= 8, f"Expected >=8 high-latency conversations, got {high_latency}"
    assert successful >= 10, f"Expected >=10 successful conversations, got {successful}"


def test_vp_demo_data_returns_synthetic_dataset() -> None:
    """VP demo data returns a properly structured SyntheticDataset."""
    ds = generate_vp_demo_dataset(seed=42)

    assert isinstance(ds, SyntheticDataset)
    assert isinstance(ds.conversations, list)
    assert all(isinstance(c, ConversationRecord) for c in ds.conversations)


def test_vp_demo_data_has_realistic_conversations() -> None:
    """VP demo conversations have named users and specific references."""
    ds = generate_vp_demo_dataset(seed=42)

    # Check at least some conversations have realistic elements
    has_named_users = any(
        any(name in c.user_message for name in ["Sarah", "James", "Maria", "David", "Emily"])
        for c in ds.conversations
    )

    has_order_numbers = any(
        "#A" in c.user_message or "#INV" in c.user_message or "Order #" in c.user_message
        for c in ds.conversations
    )

    has_product_refs = any(
        any(prod in c.user_message or prod in c.agent_response
            for prod in ["Pro Plan", "Enterprise", "Premium"])
        for c in ds.conversations
    )

    assert has_named_users, "No named users found in conversations"
    assert has_order_numbers, "No order numbers found in conversations"
    assert has_product_refs, "No product references found in conversations"


def test_vp_demo_summary() -> None:
    """VP demo summary shows expected metrics."""
    summary = get_vp_demo_summary()

    assert "total_conversations" in summary
    assert summary["total_conversations"] == 41

    breakdown = summary["breakdown"]
    assert breakdown["billing_misroutes"] == 15
    assert breakdown["safety_violations"] == 3
    assert breakdown["high_latency"] == 8
    assert breakdown["successful"] == 10
    assert breakdown["quality_issues"] == 5

    # Overall score should be around 0.62 (CRITICAL range)
    expected = summary["expected_metrics"]
    assert expected["overall_score"] == 0.62
    assert 0.55 <= expected["overall_score"] <= 0.70


def test_vp_demo_score_progression() -> None:
    """VP demo expects specific score progression: 0.62 → 0.74 → 0.81 → 0.87"""
    # This is a documentation test - the runner.py implements this progression
    # through 3 optimization cycles. We just verify the data supports it.
    summary = get_vp_demo_summary()
    expected = summary["expected_metrics"]

    # Starting score should be low enough to show dramatic improvement
    assert expected["overall_score"] < 0.70, "Starting score should be below 0.70 for dramatic effect"

    # Should have enough failures to fix
    breakdown = summary["breakdown"]
    total_failures = (
        breakdown["billing_misroutes"] +
        breakdown["safety_violations"] +
        breakdown["high_latency"] +
        breakdown["quality_issues"]
    )
    assert total_failures >= 30, "Need enough failures for 3 cycles of optimization"


def test_seed_demo_data_populates_conversation_store(tmp_path) -> None:
    """seed_demo_data should persist the VP demo dataset into the provided DB."""
    db_path = tmp_path / "vp-demo.db"

    seeded_count = seed_demo_data(str(db_path))

    store = ConversationStore(str(db_path))
    records = store.get_recent(limit=100)
    assert seeded_count == 41
    assert len(records) == 41


def test_seed_trace_demo_data_populates_trace_store(tmp_path) -> None:
    """Trace seeding should create recent trace events for the demo UI."""
    db_path = tmp_path / "traces.db"

    seeded_count = seed_trace_demo_data(str(db_path))

    store = TraceStore(str(db_path))
    assert seeded_count > 0
    assert store.count_events() == seeded_count


def test_seed_optimization_history_populates_memory_store(tmp_path) -> None:
    """Optimization history seeding should create accepted attempts for dashboards."""
    db_path = tmp_path / "optimizer_memory.db"

    seeded_count = seed_optimization_history(str(db_path))

    memory = OptimizationMemory(str(db_path))
    attempts = memory.recent(limit=10)
    assert seeded_count == 3
    assert len(attempts) == 3
    assert all(attempt.status == "accepted" for attempt in attempts)
