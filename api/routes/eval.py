"""Eval endpoints — run evals, list runs, inspect results."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException, Request

from api.models import (
    EvalCaseResult,
    EvalRunRequest,
    EvalRunResponse,
    EvalResultsResponse,
    TaskStatus,
    TaskStatusEnum,
)
from api.tasks import Task

router = APIRouter(prefix="/api/eval", tags=["eval"])


def _score_to_response(run_id: str, score: Any, completed_at: datetime | None = None) -> dict:
    """Convert a CompositeScore to an EvalResultsResponse-compatible dict."""
    cases = []
    for r in getattr(score, "results", []):
        cases.append({
            "case_id": r.case_id,
            "category": r.category,
            "passed": r.passed,
            "quality_score": r.quality_score,
            "safety_passed": r.safety_passed,
            "latency_ms": r.latency_ms,
            "token_count": r.token_count,
            "details": r.details,
        })
    return {
        "run_id": run_id,
        "quality": score.quality,
        "safety": score.safety,
        "latency": score.latency,
        "cost": score.cost,
        "composite": score.composite,
        "safety_failures": score.safety_failures,
        "total_cases": score.total_cases,
        "passed_cases": score.passed_cases,
        "cases": cases,
        "completed_at": completed_at.isoformat() if completed_at else None,
    }


@router.post("/run", response_model=EvalRunResponse, status_code=202)
async def start_eval_run(body: EvalRunRequest, request: Request) -> EvalRunResponse:
    """Start an eval run as a background task."""
    task_manager = request.app.state.task_manager
    ws_manager = request.app.state.ws_manager
    eval_runner = request.app.state.eval_runner

    config: dict | None = None
    if body.config_path:
        config_path = Path(body.config_path)
        if not config_path.exists():
            raise HTTPException(status_code=404, detail=f"Config file not found: {body.config_path}")
        with config_path.open("r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

    category = body.category

    def run_eval(task: Task) -> dict:
        import asyncio

        task.progress = 10
        if category:
            score = eval_runner.run_category(category, config=config)
        else:
            score = eval_runner.run(config=config)
        task.progress = 90

        result = _score_to_response(task.task_id, score, datetime.now(timezone.utc))
        task.result = result

        # Best-effort websocket broadcast
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(
                ws_manager.broadcast({
                    "type": "eval_complete",
                    "task_id": task.task_id,
                    "composite": score.composite,
                    "passed": score.passed_cases,
                    "total": score.total_cases,
                })
            )
            loop.close()
        except Exception:
            pass

        return result

    task = task_manager.create_task("eval", run_eval)
    return EvalRunResponse(task_id=task.task_id, message="Eval run started")


@router.get("/runs", response_model=list[TaskStatus])
async def list_eval_runs(request: Request) -> list[TaskStatus]:
    """List all eval run tasks."""
    task_manager = request.app.state.task_manager
    tasks = task_manager.list_tasks(task_type="eval")
    return [
        TaskStatus(
            task_id=t.task_id,
            task_type=t.task_type,
            status=TaskStatusEnum(t.status),
            progress=t.progress,
            result=t.result,
            error=t.error,
            created_at=t.created_at,
            updated_at=t.updated_at,
        )
        for t in tasks
    ]


@router.get("/runs/{run_id}", response_model=EvalResultsResponse)
async def get_eval_run(run_id: str, request: Request) -> EvalResultsResponse:
    """Get results for a specific eval run."""
    task_manager = request.app.state.task_manager
    task = task_manager.get_task(run_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Eval run not found: {run_id}")
    if task.status != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Eval run {run_id} is {task.status}; results not yet available",
        )
    if task.result is None:
        raise HTTPException(status_code=500, detail="Eval run completed but no results stored")
    return EvalResultsResponse(**task.result)


@router.get("/runs/{run_id}/cases", response_model=list[EvalCaseResult])
async def get_eval_run_cases(run_id: str, request: Request) -> list[EvalCaseResult]:
    """Get per-case results for a specific eval run."""
    task_manager = request.app.state.task_manager
    task = task_manager.get_task(run_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Eval run not found: {run_id}")
    if task.status != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Eval run {run_id} is {task.status}; results not yet available",
        )
    if task.result is None:
        raise HTTPException(status_code=500, detail="Eval run completed but no results stored")
    return [EvalCaseResult(**c) for c in task.result.get("cases", [])]
