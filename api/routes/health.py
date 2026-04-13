"""Health endpoint — full health report with metrics, anomalies, trends."""

from __future__ import annotations

import math
import time

from fastapi import APIRouter, Query, Request

from api.models import HealthMetricsData, HealthResponse, SystemHealthResponse, WorkspaceStateResponse
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


def _workspace_state_response(request: Request) -> WorkspaceStateResponse:
    """Return startup workspace state without querying workspace files per request."""
    state = getattr(request.app.state, "workspace_state", None)
    if isinstance(state, WorkspaceStateResponse):
        return state
    if state is not None and hasattr(state, "to_dict"):
        return WorkspaceStateResponse(**state.to_dict())
    if isinstance(state, dict):
        return WorkspaceStateResponse(**state)
    return WorkspaceStateResponse()


@router.get("/ready")
async def readiness_check(request: Request) -> dict:
    """Lightweight readiness probe — no database queries."""
    workspace = _workspace_state_response(request)
    return {
        "status": "ready",
        "workspace_valid": workspace.valid,
        "workspace": workspace.model_dump(),
    }


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
    workspace = _workspace_state_response(request)

    active_provider: str | None = None
    active_model: str | None = None
    if runtime_config is not None and getattr(runtime_config.optimizer, "models", None):
        primary = runtime_config.optimizer.models[0]
        active_provider = str(getattr(primary, "provider", "") or "") or None
        active_model = str(getattr(primary, "model", "") or "") or None

    return HealthResponse(
        metrics=metrics,
        anomalies=report.anomalies,
        failure_buckets=report.failure_buckets,
        needs_optimization=report.needs_optimization,
        reason=report.reason,
        mock_mode=bool(mock_reasons),
        mock_reasons=mock_reasons,
        real_provider_configured=real_provider_configured,
        active_provider=active_provider,
        active_model=active_model,
        workspace_valid=workspace.valid,
        workspace=workspace,
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
    workspace = _workspace_state_response(request)
    status = "degraded" if loop_stalled or not workspace.valid else "ok"

    return SystemHealthResponse(
        status=status,
        loop_running=loop_running,
        loop_stalled=loop_stalled,
        last_heartbeat=last_heartbeat,
        dead_letter_count=dead_letter_count,
        tasks_running=len(running_tasks),
        uptime_seconds=uptime_seconds,
        workspace_valid=workspace.valid,
        workspace=workspace,
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
    """Return eval-set health diagnostics computed from real run history.

    A case is:
    - **saturated** if it passed in every one of the last 3 runs that included it.
    - **unsolvable** if it failed in every one of the last 3 runs that included it.
    - **high-leverage** otherwise (mixed pass/fail signal — most informative for the optimizer).

    Difficulty distribution buckets cases by historical pass rate:
    - easy:   pass_rate >= 0.8
    - medium: 0.4 <= pass_rate < 0.8
    - hard:   pass_rate < 0.4
    """
    eval_runner = getattr(request.app.state, "eval_runner", None)
    history_store = getattr(eval_runner, "history_store", None) if eval_runner is not None else None
    if history_store is None:
        return {
            "status": "no_history_store",
            "total_cases": 0,
            "analysis": {"saturated": 0, "unsolvable": 0, "high_leverage": 0},
            "difficulty_distribution": {"easy": 0, "medium": 0, "hard": 0},
        }

    try:
        recent_runs = history_store.list_runs(limit=20)
    except Exception:  # noqa: BLE001 - degraded health is better than 500
        return {
            "status": "history_unavailable",
            "total_cases": 0,
            "analysis": {"saturated": 0, "unsolvable": 0, "high_leverage": 0},
            "difficulty_distribution": {"easy": 0, "medium": 0, "hard": 0},
        }

    if not recent_runs:
        return {
            "status": "no_eval_set",
            "total_cases": 0,
            "analysis": {"saturated": 0, "unsolvable": 0, "high_leverage": 0},
            "difficulty_distribution": {"easy": 0, "medium": 0, "hard": 0},
        }

    # Per-case rolling history of last 3 outcomes (most-recent run first).
    per_case_outcomes: dict[str, list[bool]] = {}
    for run_summary in recent_runs:
        try:
            run_detail = history_store.get_run(run_summary["run_id"])
        except Exception:  # noqa: BLE001
            continue
        if not run_detail:
            continue
        for case in run_detail.get("cases", []):
            case_id = str(case.get("case_id") or "").strip()
            if not case_id:
                continue
            history = per_case_outcomes.setdefault(case_id, [])
            if len(history) >= 3:
                continue
            history.append(bool(case.get("passed")))

    saturated = 0
    unsolvable = 0
    high_leverage = 0
    easy = 0
    medium = 0
    hard = 0
    for outcomes in per_case_outcomes.values():
        if not outcomes:
            continue
        passed = sum(1 for o in outcomes if o)
        total = len(outcomes)
        if total >= 3 and passed == total:
            saturated += 1
        elif total >= 3 and passed == 0:
            unsolvable += 1
        else:
            high_leverage += 1
        pass_rate = passed / total
        if pass_rate >= 0.8:
            easy += 1
        elif pass_rate >= 0.4:
            medium += 1
        else:
            hard += 1

    total_cases = len(per_case_outcomes)
    if total_cases == 0:
        status = "no_eval_set"
    elif saturated / total_cases > 0.8:
        status = "needs_attention"  # eval set is too easy — add harder cases
    elif unsolvable / total_cases > 0.5:
        status = "needs_attention"  # eval set is too hard — agent hasn't shipped any wins
    else:
        status = "healthy"

    return {
        "status": status,
        "total_cases": total_cases,
        "runs_analyzed": min(len(recent_runs), 20),
        "analysis": {
            "saturated": saturated,
            "unsolvable": unsolvable,
            "high_leverage": high_leverage,
        },
        "difficulty_distribution": {"easy": easy, "medium": medium, "hard": hard},
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
