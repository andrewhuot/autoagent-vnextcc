"""Eval endpoints — run evals, list runs, inspect results, auto-generate."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException, Request

from agent.config.runtime import load_runtime_config
from agent.eval_agent import LIVE_REQUIRED_CONFIG_KEY
from evals.auto_generator import AutoEvalGenerator
from evals.execution_mode import requested_live_mode, resolve_eval_execution_mode
from evals.runner import TestCase
from evals.scorer import composite_breakdown
from api.models import (
    AcceptSuiteResponse,
    AutoEvalGenerateRequest,
    AutoEvalGenerateResponse,
    EvalCaseResult,
    EvalRunRequest,
    EvalRunResponse,
    EvalResultsResponse,
    GeneratedCaseResponse,
    GeneratedSuiteResponse,
    TaskStatus,
    UpdateCaseRequest,
)
from api.tasks import Task

router = APIRouter(prefix="/api/eval", tags=["eval"])
LOG = logging.getLogger(__name__)


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
        "mode": "mock",
        "quality": score.quality,
        "safety": score.safety,
        "latency": score.latency,
        "cost": score.cost,
        "composite": score.composite,
        "confidence_intervals": getattr(score, "confidence_intervals", {}),
        "composite_breakdown": composite_breakdown(score),
        "safety_failures": score.safety_failures,
        "total_cases": score.total_cases,
        "passed_cases": score.passed_cases,
        "total_tokens": getattr(score, "total_tokens", 0),
        "estimated_cost_usd": getattr(score, "estimated_cost_usd", 0.0),
        "warnings": getattr(score, "warnings", []),
        "cases": cases,
        "completed_at": completed_at.isoformat() if completed_at else None,
    }


def _resolve_generated_eval_generator(request: Request | None) -> AutoEvalGenerator:
    """Return the shared generated-eval generator when one is configured.

    WHY: `/api/eval/*` and `/api/evals/*` must read and write the same
    generated-suite state instead of drifting between private stores.
    """

    if request is not None:
        generator = getattr(request.app.state, "auto_eval_generator", None)
        if generator is not None:
            return generator
    return _auto_eval_generator


def _resolve_generated_eval_store(request: Request | None) -> Any | None:
    """Return the shared generated-suite store when one is configured."""

    if request is None:
        return None
    return getattr(request.app.state, "generated_eval_store", None)


@router.post("/run", response_model=EvalRunResponse, status_code=202)
async def start_eval_run(body: EvalRunRequest, request: Request) -> EvalRunResponse:
    """Start an eval run as a background task."""
    task_manager = request.app.state.task_manager
    ws_manager = request.app.state.ws_manager
    eval_runner = request.app.state.eval_runner
    event_log = getattr(request.app.state, "event_log", None)
    runtime = getattr(request.app.state, "runtime_config", load_runtime_config())
    requested_live = requested_live_mode(runtime, require_live=body.require_live)

    config: dict | None = None
    if body.config_path:
        config_path = Path(body.config_path)
        if not config_path.exists():
            raise HTTPException(status_code=404, detail=f"Config file not found: {body.config_path}")
        with config_path.open("r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

    category = body.category
    dataset_path = body.dataset_path
    generated_suite_id = body.generated_suite_id
    split = body.split
    if dataset_path and not Path(dataset_path).exists():
        raise HTTPException(status_code=404, detail=f"Dataset file not found: {dataset_path}")

    generated_suite = None
    generated_cases: list[TestCase] | None = None
    if generated_suite_id:
        generated_store = getattr(request.app.state, "generated_eval_store", None)
        if generated_store is None:
            raise HTTPException(status_code=503, detail="Generated eval store not configured")
        generated_suite = generated_store.get_suite(generated_suite_id)
        if generated_suite is None:
            raise HTTPException(
                status_code=404,
                detail=f"Generated eval suite not found: {generated_suite_id}",
            )
        dataset_path = generated_suite.accepted_eval_path or f"generated_suite:{generated_suite_id}"
        generated_cases = [
            TestCase(
                id=case["id"],
                category=case.get("category", "unknown"),
                user_message=case["user_message"],
                expected_specialist=case.get("expected_specialist", ""),
                expected_behavior=case.get("expected_behavior", "answer"),
                safety_probe=bool(case.get("safety_probe", False)),
                expected_keywords=case.get("expected_keywords", []) or [],
                expected_tool=case.get("expected_tool"),
                split=case.get("split"),
                reference_answer=case.get("reference_answer", ""),
            )
            for case in generated_suite.to_test_cases()
            if not category or case.get("category") == category
        ]

    eval_config = dict(config or {})
    if body.require_live:
        eval_config[LIVE_REQUIRED_CONFIG_KEY] = True
    runner_config = eval_config or None

    def run_eval(task: Task) -> dict:
        import asyncio

        task.progress = 10

        def report_case_progress(completed: int, total: int) -> None:
            if total <= 0:
                return
            progress = min(90, 10 + int((completed / total) * 80))
            task.progress = progress
            task_manager.update_task(task.task_id, progress=progress)

        if generated_cases is not None:
            score = eval_runner.run_cases(
                generated_cases,
                config=runner_config,
                category=category,
                split=split,
                progress_callback=report_case_progress,
            )
            score.provenance = {
                "dataset_path": f"generated_suite:{generated_suite_id}",
                "split": split,
                "category": category or "all",
                "source_kind": generated_suite.source_kind if generated_suite is not None else "generated",
            }
        elif category:
            score = eval_runner.run_category(
                category,
                config=runner_config,
                dataset_path=dataset_path,
                split=split,
                progress_callback=report_case_progress,
            )
        else:
            score = eval_runner.run(
                config=runner_config,
                dataset_path=dataset_path,
                split=split,
                progress_callback=report_case_progress,
            )
        task.progress = 90

        result = _score_to_response(task.task_id, score, datetime.now(timezone.utc))
        result["run_id"] = score.run_id or task.task_id
        result["mode"] = resolve_eval_execution_mode(
            requested_live=requested_live,
            eval_agent=getattr(eval_runner, "eval_agent", None),
        )
        if result["mode"] == "mixed":
            live_fallback_warnings = list(getattr(eval_runner, "mock_mode_messages", []) or [])
            live_fallback_warnings.extend(
                list(getattr(getattr(eval_runner, "eval_agent", None), "mock_mode_messages", []) or [])
            )
            for warning in live_fallback_warnings:
                if warning not in result["warnings"]:
                    result["warnings"].append(warning)
                LOG.warning("api.eval_run.live_fallback_to_mock: %s", warning)
        result["provenance"] = score.provenance
        result["dataset_path"] = dataset_path
        result["split"] = split
        task.result = result

        # Best-effort websocket broadcast
        broadcast_payload = {
            "type": "eval_complete",
            "task_id": task.task_id,
            "composite": score.composite,
            "passed": score.passed_cases,
            "total": score.total_cases,
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
                event_log.append(
                    event_type="eval_completed_broadcast",
                    payload=broadcast_payload,
                )
            except Exception:
                LOG.debug("Failed to bridge eval broadcast to event log", exc_info=True)

        return result

    task = task_manager.create_task("eval", run_eval)
    return EvalRunResponse(task_id=task.task_id, message="Eval run started")


@router.get("/runs", response_model=list[TaskStatus])
async def list_eval_runs(request: Request) -> list[TaskStatus]:
    """List all eval run tasks."""
    task_manager = request.app.state.task_manager
    tasks = task_manager.list_tasks(task_type="eval")
    return [TaskStatus(**t.to_dict()) for t in tasks]


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


@router.get("/history")
async def list_eval_history(request: Request, limit: int = 20) -> list[dict]:
    """List persisted eval history runs with provenance metadata."""
    history_store = request.app.state.eval_runner.history_store
    if history_store is None:
        return []
    return history_store.list_runs(limit=limit)


@router.get("/history/{run_id}")
async def get_eval_history_run(run_id: str, request: Request) -> dict:
    """Fetch one persisted eval history run by run_id."""
    history_store = request.app.state.eval_runner.history_store
    if history_store is None:
        raise HTTPException(status_code=404, detail="Eval history is not enabled")
    run = history_store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Eval run not found: {run_id}")
    return run


# ---------------------------------------------------------------------------
# Auto-eval generation endpoints
# ---------------------------------------------------------------------------

# Module-level generator instance (shared across requests)
_auto_eval_generator = AutoEvalGenerator()


@router.post("/generate", response_model=AutoEvalGenerateResponse, status_code=201)
async def generate_eval_suite(
    body: AutoEvalGenerateRequest,
    request: Request,
) -> AutoEvalGenerateResponse:
    """Analyze an agent config and generate a comprehensive eval suite."""
    suite = _resolve_generated_eval_generator(request).generate(
        agent_config=body.agent_config,
        agent_name=body.agent_name,
    )
    return AutoEvalGenerateResponse(
        suite_id=suite.suite_id,
        status=suite.status,
        total_cases=suite.total_cases,
        message=f"Generated {suite.total_cases} eval cases across {len(suite.categories)} categories",
    )


@router.get("/generated/{suite_id}", response_model=GeneratedSuiteResponse)
async def get_generated_suite(
    suite_id: str,
    request: Request,
) -> GeneratedSuiteResponse:
    """Fetch a previously generated eval suite."""
    store = _resolve_generated_eval_store(request)
    if store is not None:
        suite = store.get_suite(suite_id)
    else:
        suite = _resolve_generated_eval_generator(request).get_suite(suite_id)
    if suite is None:
        raise HTTPException(status_code=404, detail=f"Generated suite not found: {suite_id}")
    suite_dict = suite.to_dict()
    return GeneratedSuiteResponse(**suite_dict)


@router.post("/generated/{suite_id}/accept", response_model=AcceptSuiteResponse)
async def accept_generated_suite(
    suite_id: str,
    request: Request,
) -> AcceptSuiteResponse:
    """Accept a generated eval suite, making it available for eval runs."""
    store = _resolve_generated_eval_store(request)
    if store is not None:
        try:
            suite = store.accept_suite(suite_id)
        except KeyError:
            suite = None
    else:
        suite = _resolve_generated_eval_generator(request).accept_suite(suite_id)
    if suite is None:
        raise HTTPException(status_code=404, detail=f"Generated suite not found: {suite_id}")
    return AcceptSuiteResponse(
        suite_id=suite.suite_id,
        status=suite.status,
        total_cases=suite.total_cases,
        message=f"Accepted suite with {suite.total_cases} cases",
    )


@router.patch("/generated/{suite_id}/cases/{case_id}", response_model=GeneratedCaseResponse)
async def update_generated_case(
    suite_id: str,
    case_id: str,
    body: UpdateCaseRequest,
    request: Request,
) -> GeneratedCaseResponse:
    """Edit a specific case within a generated suite."""
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")
    store = _resolve_generated_eval_store(request)
    if store is not None:
        try:
            suite = store.update_case(suite_id, case_id, updates)
        except KeyError:
            suite = None
        if suite is None:
            raise HTTPException(
                status_code=404,
                detail=f"Case {case_id} not found in suite {suite_id}",
            )
        for case in suite.cases:
            if case.case_id == case_id:
                return GeneratedCaseResponse(**case.to_dict())
        raise HTTPException(
            status_code=404,
            detail=f"Case {case_id} not found in suite {suite_id}",
        )

    case = _resolve_generated_eval_generator(request).update_case(suite_id, case_id, updates)
    if case is None:
        raise HTTPException(
            status_code=404,
            detail=f"Case {case_id} not found in suite {suite_id}",
        )
    return GeneratedCaseResponse(**case.to_dict())


@router.delete("/generated/{suite_id}/cases/{case_id}", status_code=204)
async def delete_generated_case(
    suite_id: str,
    case_id: str,
    request: Request,
) -> None:
    """Delete a specific case from a generated suite."""
    store = _resolve_generated_eval_store(request)
    if store is not None:
        try:
            store.delete_case(suite_id, case_id)
            return
        except KeyError:
            deleted = False
    else:
        deleted = _resolve_generated_eval_generator(request).delete_case(suite_id, case_id)

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Case {case_id} not found in suite {suite_id}",
        )
