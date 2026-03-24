"""NL Scorer API endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from evals.nl_scorer import NLScorer
from evals.scorer import EvalResult
from evals.scorer_spec import ScorerSpec

router = APIRouter(prefix="/api/scorers", tags=["scorers"])


def _get_scorer(request: Request) -> NLScorer:
    scorer = getattr(request.app.state, "nl_scorer", None)
    if scorer is None:
        raise HTTPException(status_code=503, detail="NL Scorer not configured")
    return scorer


@router.post("/create")
async def create_scorer(
    request: Request,
    body: dict[str, Any],
) -> dict:
    """Create a scorer from a natural language description."""
    scorer = _get_scorer(request)
    description = body.get("description")
    if not description:
        raise HTTPException(status_code=400, detail="description is required")
    name = body.get("name")
    spec = scorer.create(description, name=name)
    return {"scorer": spec.to_dict()}


@router.get("")
async def list_scorers(request: Request) -> dict:
    """List all scorer specs."""
    scorer = _get_scorer(request)
    specs = scorer.list()
    return {"scorers": [s.to_dict() for s in specs]}


@router.get("/{name}")
async def get_scorer(
    request: Request,
    name: str,
) -> dict:
    """Get a scorer spec by name."""
    scorer = _get_scorer(request)
    spec = scorer.get(name)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Scorer '{name}' not found")
    return {"scorer": spec.to_dict()}


@router.post("/{name}/refine")
async def refine_scorer(
    request: Request,
    name: str,
    body: dict[str, Any],
) -> dict:
    """Refine a scorer with additional natural language criteria."""
    scorer = _get_scorer(request)
    description = body.get("description")
    if not description:
        raise HTTPException(status_code=400, detail="description is required")
    try:
        spec = scorer.refine(name, description)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"scorer": spec.to_dict()}


@router.post("/{name}/test")
async def test_scorer(
    request: Request,
    name: str,
    body: dict[str, Any],
) -> dict:
    """Test a scorer against sample eval result data."""
    scorer = _get_scorer(request)
    eval_data = body.get("eval_result")
    if not eval_data:
        raise HTTPException(status_code=400, detail="eval_result is required")

    # Build an EvalResult from the dict
    try:
        eval_result = EvalResult(
            case_id=eval_data.get("case_id", "test"),
            category=eval_data.get("category", "happy_path"),
            passed=eval_data.get("passed", True),
            quality_score=eval_data.get("quality_score", 0.8),
            safety_passed=eval_data.get("safety_passed", True),
            latency_ms=eval_data.get("latency_ms", 500.0),
            token_count=eval_data.get("token_count", 100),
            tool_use_accuracy=eval_data.get("tool_use_accuracy", 1.0),
            satisfaction_proxy=eval_data.get("satisfaction_proxy", 1.0),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid eval_result: {exc}")

    try:
        scores = scorer.test(name, eval_result)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {"scores": {"per_dimension": scores.get("dimensions", {}), "aggregate": scores.get("aggregate_score", 0.0)}}
