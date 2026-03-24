"""Optimization endpoints — trigger optimization, view history."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from api.models import (
    OptimizeCycleResult,
    OptimizeRequest,
    OptimizeResponse,
    TaskStatus,
    TaskStatusEnum,
)
from api.tasks import Task

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


@router.post("/run", response_model=OptimizeResponse, status_code=202)
async def start_optimization(body: OptimizeRequest, request: Request) -> OptimizeResponse:
    """Start an optimization cycle as a background task."""
    task_manager = request.app.state.task_manager
    ws_manager = request.app.state.ws_manager
    observer = request.app.state.observer
    optimizer = request.app.state.optimizer
    deployer = request.app.state.deployer
    eval_runner = request.app.state.eval_runner
    store = request.app.state.conversation_store

    window = body.window
    force = body.force

    def run_optimize(task: Task) -> dict:
        import asyncio

        task.progress = 10
        report = observer.observe(window=window)
        task.progress = 20

        if not report.needs_optimization and not force:
            result = OptimizeCycleResult(
                accepted=False,
                status_message="System healthy; no optimization needed",
            ).model_dump()
            task.result = result
            return result

        task.progress = 30
        current_config = _ensure_active_config(deployer)
        failure_samples = _build_failure_samples(store)

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

        if new_config is not None:
            score = eval_runner.run(config=new_config)
            score_after = score.composite
            # Get baseline score
            baseline = eval_runner.run(config=current_config)
            score_before = baseline.composite

            scores_dict = {
                "quality": score.quality,
                "safety": score.safety,
                "latency": score.latency,
                "cost": score.cost,
                "composite": score.composite,
            }
            deploy_msg = deployer.deploy(new_config, scores_dict)
            task.progress = 90

        # Get the latest attempt for details
        change_desc: str | None = None
        config_diff: str | None = None
        recent = request.app.state.optimization_memory.recent(limit=1)
        if recent:
            change_desc = recent[0].change_description
            config_diff = recent[0].config_diff

        result = OptimizeCycleResult(
            accepted=new_config is not None,
            status_message=status_msg,
            change_description=change_desc,
            config_diff=config_diff,
            score_before=score_before,
            score_after=score_after,
            deploy_message=deploy_msg,
        ).model_dump()
        task.result = result

        # Best-effort websocket broadcast
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(
                ws_manager.broadcast({
                    "type": "optimize_complete",
                    "task_id": task.task_id,
                    "accepted": new_config is not None,
                    "status": status_msg,
                })
            )
            loop.close()
        except Exception:
            pass

        return result

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
