"""Unit tests for observer metrics and diagnosis behavior."""

from __future__ import annotations

from logger.store import ConversationStore
from observer import Observer
from observer.anomaly import AnomalyDetector
from observer.metrics import HealthMetrics, compute_metrics

from tests.helpers import build_record


def test_compute_metrics_calculates_expected_values() -> None:
    """compute_metrics should aggregate success, error, latency, safety, and cost."""
    records = [
        build_record(outcome="success", latency_ms=100.0, token_count=100, safety_flags=[]),
        build_record(outcome="fail", latency_ms=200.0, token_count=200, safety_flags=["weapon"]),
        build_record(outcome="error", latency_ms=300.0, token_count=300, safety_flags=[]),
    ]

    metrics = compute_metrics(records)

    assert metrics.total_conversations == 3
    assert metrics.success_rate == 1 / 3
    assert metrics.error_rate == 2 / 3
    assert metrics.avg_latency_ms == 200.0
    assert metrics.safety_violation_rate == 1 / 3
    assert metrics.avg_cost == 0.2


def test_anomaly_detector_flags_two_sigma_breaches() -> None:
    """AnomalyDetector should emit anomalies for extreme metric values."""
    detector = AnomalyDetector()
    metrics = HealthMetrics(
        success_rate=0.40,        # below default lower bound (0.75)
        avg_latency_ms=400.0,     # above default upper bound (250)
        error_rate=0.30,          # above default upper bound (0.16)
        safety_violation_rate=0.10,
        avg_cost=0.40,
        total_conversations=10,
    )

    anomalies = detector.detect(metrics)

    assert any("success_rate" in item for item in anomalies)
    assert any("avg_latency_ms" in item for item in anomalies)
    assert any("error_rate" in item for item in anomalies)


def test_observer_marks_system_for_optimization(conversation_store: ConversationStore) -> None:
    """Observer should request optimization when failure patterns are unhealthy."""
    # High-failure examples that trigger multiple buckets.
    for _ in range(8):
        conversation_store.log(
            build_record(
                user_message="Please write code for me",
                agent_response="ok",
                outcome="fail",
                latency_ms=4000.0,
                token_count=50,
                safety_flags=["hack"],
                tool_calls=[{"tool": "faq", "status": "error"}],
                specialist_used="support",
            )
        )

    # A couple of successful records so we still have mixed data.
    for _ in range(2):
        conversation_store.log(
            build_record(
                user_message="Where is my order ORD-1001?",
                agent_response="I checked your order and it is shipped.",
                outcome="success",
                latency_ms=140.0,
                token_count=180,
                safety_flags=[],
                tool_calls=[{"tool": "orders_db", "status": "ok"}],
                specialist_used="orders",
            )
        )

    observer = Observer(conversation_store)
    report = observer.observe(window=20)

    assert report.needs_optimization is True
    assert report.metrics.success_rate == 0.2
    assert report.failure_buckets["tool_failure"] >= 1
    assert report.failure_buckets["timeout"] >= 1
    assert report.failure_buckets["unhelpful_response"] >= 1
    assert report.failure_buckets["safety_violation"] >= 1


def test_observer_failure_buckets_follow_requested_window(conversation_store: ConversationStore) -> None:
    """Observer failure buckets should be derived from the same window as metrics."""
    for _ in range(3):
        conversation_store.log(
            build_record(
                user_message="Please write code",
                agent_response="ok",
                outcome="fail",
                latency_ms=3500.0,
                tool_calls=[{"tool": "faq", "status": "error"}],
                specialist_used="support",
            )
        )

    # Most recent records are healthy; window=2 should ignore the older failures above.
    conversation_store.log(
        build_record(
            user_message="Where is my order?",
            agent_response="Your order is shipped and arrives tomorrow.",
            outcome="success",
            safety_flags=[],
            specialist_used="orders",
        )
    )
    conversation_store.log(
        build_record(
            user_message="Can you recommend something similar?",
            agent_response="Absolutely. Here are three alternatives that fit your budget.",
            outcome="success",
            safety_flags=[],
            specialist_used="recommendations",
        )
    )

    report = Observer(conversation_store).observe(window=2)
    assert report.failure_buckets["tool_failure"] == 0
    assert report.failure_buckets["timeout"] == 0
