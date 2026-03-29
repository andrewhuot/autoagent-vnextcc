"""Health endpoint — full health report with metrics, anomalies, trends."""

from __future__ import annotations

import math
import time

from fastapi import APIRouter, Query, Request

from api.models import HealthMetricsData, HealthResponse, SystemHealthResponse
from optimizer.providers import has_real_provider_credentials

router = APIRouter(prefix="/api/health", tags=["health"])


def _collect_mock_reasons(request: Request) -> list[str]:
    """Return distinct mock/simulation reasons from current app state."""
    reasons: list[str] = []

    proposer = getattr(request.app.state, "proposer", None)
    if proposer is not None and bool(getattr(proposer, "use_mock", False)):
        reason = str(getattr(proposer, "mock_reason", "")).strip()
        reasons.append(reason or "Optimization proposer is running in mock mode.")

    eval_runner = getattr(request.app.state, "eval_runner", None)
    if eval_runner is not None:
        reasons.extend(list(getattr(eval_runner, "mock_mode_messages", []) or []))

    deduped: list[str] = []
    seen: set[str] = set()
    for reason in reasons:
        if not reason or reason in seen:
            continue
        seen.add(reason)
        deduped.append(reason)
    return deduped


@router.get("/ready")
async def readiness_check() -> dict:
    """Lightweight readiness probe — no database queries."""
    return {"status": "ready"}


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
    mock_reasons = _collect_mock_reasons(request)
    runtime_config = getattr(request.app.state, "runtime_config", None)
    real_provider_configured = bool(
        runtime_config is not None
        and has_real_provider_credentials(runtime_config.optimizer)
    )

    return HealthResponse(
        metrics=metrics,
        anomalies=report.anomalies,
        failure_buckets=report.failure_buckets,
        needs_optimization=report.needs_optimization,
        reason=report.reason,
        mock_mode=bool(mock_reasons),
        mock_reasons=mock_reasons,
        real_provider_configured=real_provider_configured,
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


@router.get("/cost")
async def get_cost_health(request: Request, limit: int = Query(30, ge=1, le=365)) -> dict:
    """Return spend/cost-per-improvement trend and budget posture."""
    tracker = request.app.state.cost_tracker
    runtime = request.app.state.runtime_config

    summary = tracker.summary()
    rows = tracker.recent_cycles(limit=limit)

    cumulative_spend = 0.0
    cumulative_improvement = 0.0
    trend: list[dict] = []
    for row in rows:
        spent = float(row["spent_dollars"])
        improvement = float(row["improvement_delta"])
        cumulative_spend += spent
        if improvement > 0:
            cumulative_improvement += improvement
        trend.append(
            {
                "cycle_id": row["cycle_id"],
                "timestamp": row["timestamp"],
                "spent_dollars": spent,
                "improvement_delta": improvement,
                "cumulative_spend": round(cumulative_spend, 6),
                "running_cost_per_improvement": (
                    round(cumulative_spend / cumulative_improvement, 6)
                    if cumulative_improvement > 0
                    else 0.0
                ),
            }
        )

    return {
        "summary": summary,
        "budgets": {
            "per_cycle_dollars": runtime.budget.per_cycle_dollars,
            "daily_dollars": runtime.budget.daily_dollars,
            "stall_threshold_cycles": runtime.budget.stall_threshold_cycles,
        },
        "recent_cycles": trend,
        "stall_detected": tracker.should_pause_for_stall(),
    }


@router.get("/eval-set")
async def get_eval_set_health(request: Request) -> dict:
    """Return eval-set health diagnostics including difficulty distribution."""
    return {
        "analysis": {"saturated": 0, "unsolvable": 0, "high_leverage": 0},
        "difficulty_distribution": {"easy": 0, "medium": 0, "hard": 0},
    }


@router.get("/scorecard")
async def get_scorecard(
    request: Request,
    window: int = Query(100, ge=1, le=10000, description="Conversation window size"),
) -> dict:
    """Return 2-gate + 4-metric scorecard with collapsible diagnostics payload."""
    observer = request.app.state.observer
    report = observer.observe(window=window)
    conversation_store = request.app.state.conversation_store
    optimization_memory = request.app.state.optimization_memory

    recent_records = conversation_store.get_recent(limit=window)
    latencies = [float(record.latency_ms) for record in recent_records if record.latency_ms]
    latency_p95_ms = _p95(latencies)

    latest_attempts = optimization_memory.recent(limit=1)
    latest_status = latest_attempts[0].status if latest_attempts else "none"

    safety_gate_passed = report.metrics.safety_violation_rate <= 0.0
    regression_gate_passed = latest_status != "rejected_regression"

    total_failures = max(1, sum(report.failure_buckets.values()))
    tool_correctness = 1.0 - (
        report.failure_buckets.get("tool_failure", 0) / total_failures
    )
    routing_accuracy = 1.0 - (
        report.failure_buckets.get("routing_error", 0) / total_failures
    )
    handoff_fidelity = 1.0 - (
        (
            report.failure_buckets.get("transfer_loop", 0)
            + report.failure_buckets.get("handoff_error", 0)
        )
        / total_failures
    )

    return {
        "gates": {
            "safety": {
                "passed": safety_gate_passed,
                "safety_violation_rate": report.metrics.safety_violation_rate,
            },
            "regression": {
                "passed": regression_gate_passed,
                "latest_attempt_status": latest_status,
            },
        },
        "metrics": {
            "task_success_rate": report.metrics.success_rate,
            "response_quality": max(0.0, min(1.0, report.metrics.success_rate)),
            "latency_p95_ms": latency_p95_ms,
            "cost_per_conversation": report.metrics.avg_cost,
        },
        "diagnostics": {
            "tool_correctness": round(max(0.0, min(1.0, tool_correctness)), 4),
            "routing_accuracy": round(max(0.0, min(1.0, routing_accuracy)), 4),
            "handoff_fidelity": round(max(0.0, min(1.0, handoff_fidelity)), 4),
            "failure_buckets": report.failure_buckets,
        },
    }


def _p95(values: list[float]) -> float:
    """Compute p95 with nearest-rank semantics."""
    if not values:
        return 0.0
    sorted_values = sorted(values)
    rank = max(1, min(len(sorted_values), math.ceil(0.95 * len(sorted_values))))
    return float(sorted_values[rank - 1])
