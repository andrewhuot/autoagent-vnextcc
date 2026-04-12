"""Optimization endpoints — trigger optimization, view history."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)

import yaml
from fastapi import APIRouter, HTTPException, Request

from api.models import (
    PendingReview,
    PendingReviewActionResponse,
    OptimizeCycleResult,
    OptimizeRequest,
    OptimizeResponse,
)
from api.tasks import Task
from evals.results_model import EvalResultSet
from observer.classifier import FAILURE_BUCKETS
from observer.metrics import HealthMetrics, HealthReport
from optimizer.memory import OptimizationAttempt
from optimizer.surface_inventory import build_surface_inventory

router = APIRouter(prefix="/api/optimize", tags=["optimize"])


def _build_failure_samples(store: Any, limit: int = 25) -> list[dict]:
    """Build structured failure samples for the optimizer."""
    samples: list[dict] = []
    for record in store.get_failures(limit=limit):
        samples.append({
            "user_message": record.user_message,
            "agent_response": record.agent_response,
            "outcome": record.outcome,
            "error_message": record.error_message,
            "safety_flags": record.safety_flags,
            "tool_calls": record.tool_calls,
            "specialist_used": record.specialist_used,
            "latency_ms": record.latency_ms,
        })
    return samples


def _failure_buckets_from_samples(samples: list[dict[str, Any]]) -> dict[str, int]:
    """Classify optimizer failure samples into coarse failure buckets."""
    counts = {bucket: 0 for bucket in FAILURE_BUCKETS}

    for sample in samples:
        error_text = str(sample.get("error_message", "")).lower()
        response_text = str(sample.get("agent_response", "")).strip()
        latency_ms = float(sample.get("latency_ms") or 0.0)
        safety_flags = sample.get("safety_flags") or []

        if safety_flags:
            counts["safety_violation"] += 1
        if latency_ms > 3000:
            counts["timeout"] += 1
        if "routing" in error_text:
            counts["routing_error"] += 1
        if "tool" in error_text:
            counts["tool_failure"] += 1
        if "hallucination" in error_text:
            counts["hallucination"] += 1
        if len(response_text) < 20:
            counts["unhelpful_response"] += 1

    return counts


def _build_failure_samples_from_eval_result_set(
    result_set: EvalResultSet | None,
    *,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Build optimizer failure samples from a scoped eval run result set."""
    if result_set is None:
        return []

    samples: list[dict[str, Any]] = []
    for example in result_set.examples:
        if example.passed:
            continue

        actual = example.actual if isinstance(example.actual, dict) else {}
        tool_calls = actual.get("tool_calls")
        safety_score = example.scores.get("safety")
        safety_failed = safety_score is not None and safety_score.value < 1.0

        samples.append({
            "user_message": str(example.input.get("user_message", "")),
            "agent_response": str(actual.get("response") or actual.get("details") or ""),
            "outcome": "fail",
            "error_message": "; ".join(example.failure_reasons),
            "safety_flags": ["eval_safety_failure"] if safety_failed else [],
            "tool_calls": tool_calls if isinstance(tool_calls, list) else [],
            "specialist_used": str(actual.get("specialist_used") or ""),
            "latency_ms": float(actual.get("latency_ms") or 0.0),
        })
        if len(samples) >= limit:
            break

    return samples


def _build_failure_samples_from_eval_payload(
    eval_payload: dict[str, Any],
    *,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Build optimizer failure samples directly from task-level eval case payloads."""
    samples: list[dict[str, Any]] = []
    for case in list(eval_payload.get("cases", []) or []):
        if not isinstance(case, dict) or bool(case.get("passed")):
            continue

        details = str(case.get("details") or "")
        category = str(case.get("category") or "")
        samples.append({
            "user_message": str(case.get("user_message") or case.get("case_id") or ""),
            "agent_response": str(case.get("response") or details),
            "outcome": "fail",
            "error_message": details or category,
            "safety_flags": ["eval_safety_failure"] if case.get("safety_passed") is False else [],
            "tool_calls": [],
            "specialist_used": str(case.get("specialist_used") or ""),
            "latency_ms": float(case.get("latency_ms") or 0.0),
        })
        if len(samples) >= limit:
            break

    return samples


def _build_health_report_from_eval_task(
    eval_payload: dict[str, Any],
    *,
    eval_run_id: str,
    result_set: EvalResultSet | None,
    failure_samples: list[dict[str, Any]],
) -> HealthReport:
    """Build a scoped optimization report from one completed eval run."""
    total_cases = int(eval_payload.get("total_cases") or 0)
    passed_cases = int(eval_payload.get("passed_cases") or 0)
    safety_failures = int(eval_payload.get("safety_failures") or 0)

    latencies: list[float] = []
    token_counts: list[int] = []
    if result_set is not None:
        for example in result_set.examples:
            actual = example.actual if isinstance(example.actual, dict) else {}
            latencies.append(float(actual.get("latency_ms") or 0.0))
            token_counts.append(int(actual.get("token_count") or 0))
    else:
        for case in list(eval_payload.get("cases", []) or []):
            if not isinstance(case, dict):
                continue
            latencies.append(float(case.get("latency_ms") or 0.0))
            token_counts.append(int(case.get("token_count") or 0))

    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
    avg_cost = ((sum(token_counts) / len(token_counts)) * 0.001) if token_counts else 0.0
    success_rate = (passed_cases / total_cases) if total_cases > 0 else 0.0
    error_rate = ((total_cases - passed_cases) / total_cases) if total_cases > 0 else 0.0
    safety_violation_rate = (safety_failures / total_cases) if total_cases > 0 else 0.0
    failure_buckets = _failure_buckets_from_samples(failure_samples)
    needs_optimization = bool(failure_samples) or success_rate < 0.8 or safety_violation_rate > 0.02
    reason = (
        f"scoped_eval_run={eval_run_id}; "
        f"passed_cases={passed_cases}/{total_cases}; "
        f"safety_failures={safety_failures}"
    )

    return HealthReport(
        metrics=HealthMetrics(
            success_rate=success_rate,
            avg_latency_ms=avg_latency,
            error_rate=error_rate,
            safety_violation_rate=safety_violation_rate,
            avg_cost=avg_cost,
            total_conversations=total_cases,
        ),
        failure_buckets=failure_buckets,
        needs_optimization=needs_optimization,
        reason=reason,
    )


def _build_scoped_optimization_context(
    request: Request,
    *,
    eval_run_id: str,
    limit: int,
) -> tuple[HealthReport, list[dict[str, Any]]]:
    """Build optimization context from a specific completed eval run."""
    task_manager = request.app.state.task_manager
    eval_task = task_manager.get_task(eval_run_id)
    if eval_task is None or eval_task.task_type != "eval":
        raise HTTPException(status_code=404, detail=f"Eval run not found: {eval_run_id}")
    if eval_task.status != "completed" or not isinstance(eval_task.result, dict):
        raise HTTPException(
            status_code=409,
            detail=f"Eval run {eval_run_id} is {eval_task.status}; results not yet available",
        )

    eval_payload = eval_task.result
    run_id = str(eval_payload.get("run_id") or eval_run_id)
    results_store = getattr(request.app.state, "results_store", None)
    result_set = results_store.get_run(run_id) if results_store is not None else None
    failure_samples = _build_failure_samples_from_eval_result_set(result_set, limit=limit)
    if not failure_samples:
        failure_samples = _build_failure_samples_from_eval_payload(eval_payload, limit=limit)
    report = _build_health_report_from_eval_task(
        eval_payload,
        eval_run_id=eval_run_id,
        result_set=result_set,
        failure_samples=failure_samples,
    )
    return report, failure_samples


def _ensure_active_config(deployer: Any) -> dict:
    """Return active config; bootstrap from base config if none exists yet."""
    from pathlib import Path
    from agent.config.loader import load_config

    current = deployer.get_active_config()
    if current is not None:
        return current
    base_path = Path(__file__).parent.parent.parent / "agent" / "config" / "base_config.yaml"
    if base_path.exists():
        config = load_config(str(base_path)).model_dump()
    else:
        config = {}
    deployer.version_manager.save_version(config, scores={"composite": 0.0}, status="active")
    return config


def _coerce_pending_review(review: Any) -> PendingReview:
    """Normalize a pending review record from store or test doubles."""

    if isinstance(review, PendingReview):
        return review
    if hasattr(review, "model_dump"):
        return PendingReview.model_validate(review.model_dump(mode="python"))
    if isinstance(review, dict):
        return PendingReview.model_validate(review)
    if hasattr(review, "__dict__"):
        return PendingReview.model_validate(vars(review))
    raise TypeError(f"Unsupported pending review payload: {type(review)!r}")


def _update_attempt_status(memory: Any, attempt_id: str, status: str) -> None:
    """Replace one optimization attempt status while preserving its history context."""

    if not hasattr(memory, "get_all") or not hasattr(memory, "log"):
        return

    for attempt in memory.get_all():
        if attempt.attempt_id != attempt_id:
            continue
        memory.log(
            OptimizationAttempt(
                attempt_id=attempt.attempt_id,
                timestamp=attempt.timestamp,
                change_description=attempt.change_description,
                config_diff=attempt.config_diff,
                status=status,
                config_section=attempt.config_section,
                score_before=attempt.score_before,
                score_after=attempt.score_after,
                significance_p_value=attempt.significance_p_value,
                significance_delta=attempt.significance_delta,
                significance_n=attempt.significance_n,
                health_context=attempt.health_context,
                skills_applied=attempt.skills_applied,
            )
        )
        return


@router.post("/run", response_model=OptimizeResponse, status_code=202)
async def start_optimization(body: OptimizeRequest, request: Request) -> OptimizeResponse:
    """Start an optimization cycle as a background task."""
    from optimizer.mode_router import ModeConfig, ModeRouter, OptimizationMode

    task_manager = request.app.state.task_manager
    ws_manager = request.app.state.ws_manager
    event_log = getattr(request.app.state, "event_log", None)
    observer = request.app.state.observer
    optimizer = request.app.state.optimizer
    deployer = request.app.state.deployer
    eval_runner = request.app.state.eval_runner
    store = request.app.state.conversation_store
    pending_review_store = getattr(request.app.state, "pending_review_store", None)
    optimization_memory = request.app.state.optimization_memory

    window = body.window
    force = body.force
    mode_config = ModeConfig(
        mode=OptimizationMode(body.mode),
        objective=body.objective,
        guardrails=body.guardrails,
        budget_per_cycle=body.budget_dollars,
        budget_daily=body.budget_dollars,
    )
    resolved_mode = ModeRouter().resolve(mode_config)

    def run_optimize(task: Task) -> dict:
        import asyncio

        original_strategy = optimizer.search_strategy
        original_max_candidates = optimizer.search_budget.max_candidates
        original_max_eval_budget = optimizer.search_budget.max_eval_budget
        original_max_cost = optimizer.search_budget.max_cost_dollars

        optimizer.search_strategy = resolved_mode.search_strategy
        optimizer.search_budget.max_candidates = resolved_mode.max_candidates
        optimizer.search_budget.max_eval_budget = resolved_mode.max_eval_budget
        optimizer.search_budget.max_cost_dollars = body.budget_dollars

        task.progress = 10
        try:
            if body.eval_run_id:
                report, failure_samples = _build_scoped_optimization_context(
                    request,
                    eval_run_id=body.eval_run_id,
                    limit=window,
                )
            else:
                report = observer.observe(window=window)
                failure_samples = _build_failure_samples(store)
            task.progress = 20

            if not report.needs_optimization and not force:
                diagnostics = optimizer.get_strategy_diagnostics()
                result = OptimizeCycleResult(
                    accepted=False,
                    status_message=f"System healthy; no optimization needed (mode={body.mode})",
                    strategy=diagnostics.strategy,
                    search_strategy=diagnostics.strategy,
                    selected_operator_family=diagnostics.selected_operator_family,
                    pareto_front=diagnostics.pareto_front,
                    pareto_recommendation_id=diagnostics.pareto_recommendation_id,
                    governance_notes=diagnostics.governance_notes,
                    global_dimensions=diagnostics.global_dimensions,
                ).model_dump()
                task.result = result
                return result

            task.progress = 30
            if body.config_path:
                config_path = Path(body.config_path)
                if not config_path.exists():
                    raise HTTPException(status_code=404, detail=f"Config file not found: {body.config_path}")
                with config_path.open("r", encoding="utf-8") as handle:
                    current_config = yaml.safe_load(handle) or {}
            else:
                current_config = _ensure_active_config(deployer)

            task.progress = 40
            new_config, status_msg = optimizer.optimize(
                report,
                current_config,
                failure_samples=failure_samples,
            )
            task.progress = 70

            deploy_msg: str | None = None
            score_before: float | None = None
            score_after: float | None = None
            pending_review: PendingReview | None = None
            broadcast_type = "optimize_complete"

            if new_config is not None:
                baseline = eval_runner.run(config=current_config)
                score_before = baseline.composite
                score = eval_runner.run(config=new_config)
                score_after = score.composite

                scores_dict = {
                    "quality": score.quality,
                    "safety": score.safety,
                    "latency": score.latency,
                    "cost": score.cost,
                    "composite": score.composite,
                    "global_dimensions": score.global_dimensions,
                    "per_agent_dimensions": score.per_agent_dimensions,
                }
                diagnostics = optimizer.get_strategy_diagnostics()
                deploy_strategy = "immediate"
                recent_attempt = None
                recent_attempts = optimization_memory.recent(limit=1)
                if recent_attempts:
                    recent_attempt = recent_attempts[0]

                if body.require_human_approval:
                    if pending_review_store is None:
                        raise HTTPException(status_code=500, detail="Pending review store is not configured")
                    attempt_id = recent_attempt.attempt_id if recent_attempt is not None else task.task_id
                    pending_review = PendingReview(
                        attempt_id=attempt_id,
                        proposed_config=new_config,
                        current_config=current_config,
                        config_diff=recent_attempt.config_diff if recent_attempt is not None else "",
                        score_before=score_before or 0.0,
                        score_after=score_after or 0.0,
                        change_description=recent_attempt.change_description if recent_attempt is not None else "",
                        reasoning=diagnostics.proposal_reasoning or "",
                        created_at=datetime.now(timezone.utc),
                        strategy=diagnostics.strategy,
                        selected_operator_family=diagnostics.selected_operator_family,
                        governance_notes=diagnostics.governance_notes,
                        deploy_scores=scores_dict,
                        deploy_strategy=deploy_strategy,
                    )
                    pending_review_store.save_review(pending_review)
                    if recent_attempt is not None:
                        _update_attempt_status(optimization_memory, recent_attempt.attempt_id, "pending_review")
                    broadcast_type = "optimize_pending_review"
                    task.progress = 90
                    status_msg = "Pending human review"
                else:
                    deploy_msg = deployer.deploy(new_config, scores_dict, strategy=deploy_strategy)
                    task.progress = 90

            # Get the latest attempt for details
            change_desc: str | None = None
            config_diff: str | None = None
            recent = optimization_memory.recent(limit=1)
            if recent:
                change_desc = recent[0].change_description
                config_diff = recent[0].config_diff

            diagnostics = optimizer.get_strategy_diagnostics()
            result = OptimizeCycleResult(
                accepted=new_config is not None,
                pending_review=pending_review is not None,
                status_message=status_msg if pending_review is not None else f"{status_msg} (mode={body.mode})",
                change_description=change_desc,
                config_diff=config_diff,
                score_before=score_before,
                score_after=score_after,
                deploy_message=deploy_msg,
                strategy=diagnostics.strategy,
                search_strategy=diagnostics.strategy,
                selected_operator_family=diagnostics.selected_operator_family,
                pareto_front=diagnostics.pareto_front,
                pareto_recommendation_id=diagnostics.pareto_recommendation_id,
                governance_notes=diagnostics.governance_notes,
                global_dimensions=diagnostics.global_dimensions,
            ).model_dump()
            task.result = result

            # Best-effort websocket broadcast
            broadcast_payload = {
                "type": broadcast_type,
                "task_id": task.task_id,
                "attempt_id": pending_review.attempt_id if pending_review is not None else None,
                "accepted": new_config is not None,
                "status": result["status_message"],
            }
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(ws_manager.broadcast(broadcast_payload))
                loop.close()
            except Exception:
                pass

            # Bridge to system event log for unified observability
            if event_log is not None:
                try:
                    log_event_type = (
                        "optimize_pending_review_broadcast"
                        if broadcast_type == "optimize_pending_review"
                        else "optimize_completed_broadcast"
                    )
                    event_log.append(
                        event_type=log_event_type,
                        payload=broadcast_payload,
                    )
                except Exception:
                    LOG.debug("Failed to bridge optimize broadcast to event log", exc_info=True)

            return result
        finally:
            optimizer.search_strategy = original_strategy
            optimizer.search_budget.max_candidates = original_max_candidates
            optimizer.search_budget.max_eval_budget = original_max_eval_budget
            optimizer.search_budget.max_cost_dollars = original_max_cost

    task = task_manager.create_task("optimize", run_optimize)
    return OptimizeResponse(task_id=task.task_id, message="Optimization started")


@router.get("/history", response_model=list[dict[str, Any]])
async def list_optimization_history(
    request: Request,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """List recent optimization attempts from memory."""
    memory = request.app.state.optimization_memory
    attempts = memory.recent(limit=limit)
    return [
        {
            "attempt_id": a.attempt_id,
            "timestamp": a.timestamp,
            "change_description": a.change_description,
            "config_diff": a.config_diff,
            "config_section": a.config_section,
            "status": a.status,
            "score_before": a.score_before,
            "score_after": a.score_after,
            "significance_p_value": a.significance_p_value,
            "significance_delta": a.significance_delta,
            "significance_n": a.significance_n,
            "health_context": a.health_context,
        }
        for a in attempts
    ]


@router.get("/surfaces")
async def get_optimization_surfaces() -> dict[str, Any]:
    """Return structured coverage for optimization component surfaces."""

    return build_surface_inventory()


@router.get("/history/{attempt_id}")
async def get_optimization_attempt(attempt_id: str, request: Request) -> dict[str, Any]:
    """Get a specific optimization attempt by ID."""
    memory = request.app.state.optimization_memory
    attempts = memory.get_all()
    for a in attempts:
        if a.attempt_id == attempt_id:
            return {
                "attempt_id": a.attempt_id,
                "timestamp": a.timestamp,
                "change_description": a.change_description,
                "config_diff": a.config_diff,
                "config_section": a.config_section,
                "status": a.status,
                "score_before": a.score_before,
                "score_after": a.score_after,
                "significance_p_value": a.significance_p_value,
                "significance_delta": a.significance_delta,
                "significance_n": a.significance_n,
                "health_context": a.health_context,
            }
    raise HTTPException(status_code=404, detail=f"Attempt not found: {attempt_id}")


@router.get("/pending", response_model=list[PendingReview])
async def list_pending_reviews(
    request: Request,
    limit: int = 20,
) -> list[PendingReview]:
    """List optimizer proposals waiting for human approval."""

    review_store = request.app.state.pending_review_store
    return [_coerce_pending_review(review) for review in review_store.list_pending(limit=limit)]


@router.post(
    "/pending/{attempt_id}/approve",
    response_model=PendingReviewActionResponse,
)
async def approve_pending_review(attempt_id: str, request: Request) -> PendingReviewActionResponse:
    """Approve a pending proposal and deploy it using the captured deploy path."""

    review_store = request.app.state.pending_review_store
    deployer = request.app.state.deployer
    memory = request.app.state.optimization_memory

    raw_review = review_store.get_review(attempt_id)
    if raw_review is None:
        raise HTTPException(status_code=404, detail=f"Pending review not found: {attempt_id}")

    review = _coerce_pending_review(raw_review)
    deploy_message = deployer.deploy(
        review.proposed_config,
        review.deploy_scores,
        strategy=review.deploy_strategy,
    )
    review_store.delete_review(attempt_id)
    _update_attempt_status(memory, attempt_id, "accepted")

    return PendingReviewActionResponse(
        status="approved",
        attempt_id=attempt_id,
        message="Pending review approved and deployed",
        deploy_message=deploy_message,
    )


@router.post(
    "/pending/{attempt_id}/reject",
    response_model=PendingReviewActionResponse,
)
async def reject_pending_review(attempt_id: str, request: Request) -> PendingReviewActionResponse:
    """Reject a pending proposal and discard it from the review queue."""

    review_store = request.app.state.pending_review_store
    memory = request.app.state.optimization_memory

    raw_review = review_store.get_review(attempt_id)
    if raw_review is None:
        raise HTTPException(status_code=404, detail=f"Pending review not found: {attempt_id}")

    review_store.delete_review(attempt_id)
    _update_attempt_status(memory, attempt_id, "rejected_human")

    return PendingReviewActionResponse(
        status="rejected",
        attempt_id=attempt_id,
        message="Pending review rejected and discarded",
    )


@router.get("/pareto")
async def get_pareto_snapshot(request: Request) -> dict[str, Any]:
    """Return constrained Pareto archive snapshot for full-mode detail views."""
    optimizer = request.app.state.optimizer
    return optimizer.get_pareto_snapshot()
