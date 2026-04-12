"""AutoFix Copilot API endpoints."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from optimizer.autofix import AutoFixProposal

router = APIRouter(prefix="/api/autofix", tags=["autofix"])


def _proposal_rationale(proposal: AutoFixProposal) -> str:
    """Build human-readable rationale copy for proposal cards."""
    if proposal.affected_eval_slices:
        slices = ", ".join(proposal.affected_eval_slices)
        return f"Target {proposal.surface} to improve failures across {slices}."
    return f"Target {proposal.surface} with a constrained {proposal.mutation_name} mutation."


def _serialize_proposal(proposal: AutoFixProposal) -> dict[str, Any]:
    """Return the proposal shape expected by the frontend review cards."""
    return {
        "proposal_id": proposal.proposal_id,
        "created_at": proposal.created_at,
        "proposer_name": "AutoFix Engine",
        "opportunity_id": proposal.surface,
        "operator_name": proposal.mutation_name,
        "operator_params": proposal.params,
        "expected_lift": proposal.expected_lift,
        "affected_eval_slices": proposal.affected_eval_slices,
        "risk_class": proposal.risk_class,
        "cost_impact_estimate": proposal.cost_impact_estimate,
        "diff_preview": proposal.diff_preview,
        "status": proposal.status,
        "rationale": _proposal_rationale(proposal),
    }


def _serialize_history_entry(proposal: AutoFixProposal) -> dict[str, Any]:
    """Return a stable history row even when richer eval metadata is unavailable."""
    eval_result = proposal.eval_result if isinstance(proposal.eval_result, dict) else {}
    applied_at = proposal.applied_at or proposal.evaluated_at or proposal.created_at or time.time()
    status = proposal.status
    message = f"{status.replace('_', ' ').capitalize()}: {proposal.mutation_name}"

    return {
        "history_id": proposal.proposal_id,
        "proposal_id": proposal.proposal_id,
        "applied_at": applied_at,
        "status": status,
        "message": message,
        "baseline_composite": float(eval_result.get("baseline_composite", 0.0) or 0.0),
        "candidate_composite": float(eval_result.get("candidate_composite", 0.0) or 0.0),
        "significance_p_value": float(eval_result.get("significance_p_value", 1.0) or 1.0),
        "significance_delta": float(eval_result.get("significance_delta", 0.0) or 0.0),
        "canary_verdict": str(eval_result.get("canary_verdict", "") or ""),
        "deploy_message": str(eval_result.get("deploy_message", "") or ""),
    }


@router.post("/suggest")
async def suggest(request: Request) -> dict[str, Any]:
    """Generate AutoFix proposals without applying them."""
    engine = request.app.state.autofix_engine
    deployer = request.app.state.deployer
    current_config = deployer.get_active_config() or {}

    body = await request.json() if request.headers.get("content-length", "0") != "0" else {}
    failures = body.get("failures", [])

    proposals = engine.suggest(failures, current_config)
    return {
        "proposals": [_serialize_proposal(p) for p in proposals],
        "count": len(proposals),
    }


@router.get("/proposals")
async def list_proposals(
    request: Request,
    status: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """List AutoFix proposals, optionally filtered by status."""
    engine = request.app.state.autofix_engine
    proposals = engine.history(limit=limit)
    if status:
        proposals = [p for p in proposals if p.status == status]
    return {
        "proposals": [_serialize_proposal(p) for p in proposals],
        "count": len(proposals),
    }


@router.post("/apply/{proposal_id}")
async def apply_proposal(proposal_id: str, request: Request) -> dict[str, Any]:
    """Apply a specific AutoFix proposal."""
    engine = request.app.state.autofix_engine
    deployer = request.app.state.deployer
    current_config = deployer.get_active_config() or {}

    try:
        new_config, status_message = engine.apply(proposal_id, current_config)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    event_log = request.app.state.event_log
    event_log.append(
        event_type="autofix_applied",
        payload={"proposal_id": proposal_id, "status": status_message},
    )

    return {
        "proposal_id": proposal_id,
        "status": "applied",
        "message": status_message,
        "config_applied": new_config is not None,
        "next_steps": [
            "Run eval to validate: POST /api/eval/run",
            "Deploy via canary if improved: POST /api/deploy/canary",
        ],
    }


@router.post("/reject/{proposal_id}")
async def reject_proposal(proposal_id: str, request: Request) -> dict[str, Any]:
    """Reject a specific AutoFix proposal without applying it."""
    engine = request.app.state.autofix_engine

    try:
        status_message = engine.reject(proposal_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    event_log = request.app.state.event_log
    event_log.append(
        event_type="autofix_rejected",
        payload={"proposal_id": proposal_id, "status": status_message},
    )

    return {
        "proposal_id": proposal_id,
        "status": "rejected",
        "message": status_message,
    }


@router.get("/history")
async def history(request: Request, limit: int = 50) -> dict[str, Any]:
    """Get past AutoFix proposals with outcomes."""
    engine = request.app.state.autofix_engine
    proposals = engine.history(limit=limit)
    history_entries = [_serialize_history_entry(p) for p in proposals]
    return {
        "history": history_entries,
        "proposals": history_entries,
        "count": len(history_entries),
    }
