"""Health endpoint — full health report with metrics, anomalies, trends."""

from __future__ import annotations

import time

from fastapi import APIRouter, Query, Request

from api.models import HealthMetricsData, HealthResponse, SystemHealthResponse

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


@router.get("/system", response_model=SystemHealthResponse)
async def get_system_health(request: Request) -> SystemHealthResponse:
    """Operational health endpoint for loop/watchdog/dead-letter monitoring."""
    task_manager = request.app.state.task_manager
    running_tasks = [task for task in task_manager.list_tasks() if task.status == "running"]

    from api.routes import loop as loop_routes

    loop_task_id = loop_routes._loop_task_id
    last_heartbeat = loop_routes._loop_last_heartbeat
    loop_running = False
    if loop_task_id:
        loop_task = task_manager.get_task(loop_task_id)
        loop_running = bool(loop_task and loop_task.status == "running")

    loop_stalled = request.app.state.loop_watchdog.is_stalled() if last_heartbeat is not None else False
    dead_letter_count = request.app.state.dead_letter_queue.count()
    uptime_seconds = max(0.0, time.time() - float(getattr(request.app.state, "started_at", time.time())))
    status = "degraded" if loop_stalled else "ok"

    return SystemHealthResponse(
        status=status,
        loop_running=loop_running,
        loop_stalled=loop_stalled,
        last_heartbeat=last_heartbeat,
        dead_letter_count=dead_letter_count,
        tasks_running=len(running_tasks),
        uptime_seconds=uptime_seconds,
    )
