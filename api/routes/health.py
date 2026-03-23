"""Health endpoint — full health report with metrics, anomalies, trends."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from api.models import HealthMetricsData, HealthResponse

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("", response_model=HealthResponse)
async def get_health(
    request: Request,
    window: int = Query(100, ge=1, le=10000, description="Number of recent conversations to analyze"),
) -> HealthResponse:
    """Full health report with metrics, anomalies, and failure buckets."""
    observer = request.app.state.observer
    report = observer.observe(window=window)

    metrics = HealthMetricsData(
        success_rate=report.metrics.success_rate,
        avg_latency_ms=report.metrics.avg_latency_ms,
        error_rate=report.metrics.error_rate,
        safety_violation_rate=report.metrics.safety_violation_rate,
        avg_cost=report.metrics.avg_cost,
        total_conversations=report.metrics.total_conversations,
    )

    return HealthResponse(
        metrics=metrics,
        anomalies=report.anomalies,
        failure_buckets=report.failure_buckets,
        needs_optimization=report.needs_optimization,
        reason=report.reason,
    )
