"""One-click fix endpoint: apply runbook + run optimization cycle."""

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["quickfix"])


class QuickfixRequest(BaseModel):
    failure_family: str


RUNBOOK_MAP = {
    "routing_error": "fix-retrieval-grounding",
    "safety_violation": "tighten-safety-policy",
    "quality_issue": "enhance-few-shot-examples",
    "latency_problem": "reduce-tool-latency",
    "cost_overrun": "optimize-cost-efficiency",
    "tool_error": "reduce-tool-latency",
    "hallucination": "fix-retrieval-grounding",
}


@router.post("/quickfix")
async def quickfix(request: Request, body: QuickfixRequest):
    """One-click fix: apply runbook + run 1 optimization cycle."""
    runbook_name = RUNBOOK_MAP.get(body.failure_family)
    if not runbook_name:
        raise HTTPException(
            status_code=400, 
            detail=f"Unknown failure family: {body.failure_family}"
        )

    runbook_store = request.app.state.runbook_store
    runbook = runbook_store.get(runbook_name)
    if not runbook:
        raise HTTPException(
            status_code=404, 
            detail=f"Runbook not found: {runbook_name}"
        )

    # For now, return success with mock data
    # Full implementation would:
    # 1. Load active config
    # 2. Merge runbook surfaces into config
    # 3. Save as experiment
    # 4. Run 1 optimization cycle targeting those surfaces
    # 5. Return actual results

    # Mock response for UI integration
    return {
        "success": True,
        "applied": False,
        "runbook": runbook_name,
        "score_before": 0.72,
        "score_after": 0.78,
        "improvement": 0.06,
        "source": "mock",
        "warning": "Preview only: this quick fix is simulated and does not change the live config yet.",
    }
