"""What-If replay API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/what-if", tags=["what-if"])


class ReplayRequest(BaseModel):
    """Request to replay conversations through candidate config."""

    conversation_ids: list[str]
    candidate_config_label: str


class ProjectRequest(BaseModel):
    """Request to project impact to full traffic."""

    job_id: str
    total_population: int


@router.post("/replay")
async def start_replay(request: Request, body: ReplayRequest) -> dict:
    """Start a what-if replay job.

    Replays historical conversations through a candidate configuration
    and compares outcomes with the original results.
    """
    what_if_engine = request.app.state.what_if_engine

    try:
        result = what_if_engine.replay_with_config(
            conversation_ids=body.conversation_ids,
            candidate_config_label=body.candidate_config_label,
        )

        return {
            "job_id": result.job_id,
            "status": "complete",
            "total_conversations": result.total_conversations,
            "improved_count": result.improved_count,
            "degraded_count": result.degraded_count,
            "unchanged_count": result.unchanged_count,
            "avg_delta_score": result.avg_delta_score,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/results/{job_id}")
async def get_results(request: Request, job_id: str) -> dict:
    """Get results of a what-if replay job.

    Returns detailed outcomes for each replayed conversation,
    including score deltas and comparison metrics.
    """
    what_if_engine = request.app.state.what_if_engine
    result = what_if_engine.what_if_store.get_result(job_id)

    if not result:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    return {
        "job_id": result.job_id,
        "candidate_config_label": result.candidate_config_label,
        "total_conversations": result.total_conversations,
        "improved_count": result.improved_count,
        "degraded_count": result.degraded_count,
        "unchanged_count": result.unchanged_count,
        "avg_delta_score": result.avg_delta_score,
        "created_at": result.created_at,
        "outcomes": [
            {
                "conversation_id": o.conversation_id,
                "original_outcome": o.original_outcome,
                "replay_outcome": o.replay_outcome,
                "original_score": o.original_score,
                "replay_score": o.replay_score,
                "delta_score": o.delta_score,
                "improved": o.improved,
                "original_latency_ms": o.original_latency_ms,
                "replay_latency_ms": o.replay_latency_ms,
                "original_cost": o.original_cost,
                "replay_cost": o.replay_cost,
                "tool_calls_matched": o.tool_calls_matched,
            }
            for o in result.outcomes
        ],
    }


@router.post("/project")
async def project_impact(request: Request, body: ProjectRequest) -> dict:
    """Project impact of candidate config to full traffic.

    Extrapolates sample replay results to estimate the impact
    on the entire conversation population.
    """
    what_if_engine = request.app.state.what_if_engine

    try:
        projection = what_if_engine.project_impact(
            job_id=body.job_id, total_population=body.total_population
        )

        return {
            "job_id": projection.job_id,
            "sample_size": projection.sample_size,
            "total_population": projection.total_population,
            "improved_count": projection.improved_count,
            "degraded_count": projection.degraded_count,
            "projected_improvement_rate": projection.projected_improvement_rate,
            "projected_improvement_absolute": projection.projected_improvement_absolute,
            "confidence_interval_95": {
                "lower": projection.confidence_interval_95[0],
                "upper": projection.confidence_interval_95[1],
            },
            "recommendation": projection.recommendation,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs")
async def list_jobs(
    request: Request, limit: int = Query(10, ge=1, le=100)
) -> dict:
    """List recent what-if replay jobs."""
    what_if_engine = request.app.state.what_if_engine
    jobs = what_if_engine.what_if_store.list_recent(limit=limit)

    return {"jobs": jobs}
