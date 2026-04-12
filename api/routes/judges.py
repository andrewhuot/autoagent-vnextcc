"""Judge Ops API endpoints — versioning, drift, and human feedback."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request

router = APIRouter(prefix="/api/judges", tags=["judges"])


@router.get("")
async def list_judges(request: Request) -> dict[str, Any]:
    """List judges with version and agreement stats."""
    version_store = request.app.state.grader_version_store
    feedback_store = request.app.state.human_feedback_store

    # Get all grader IDs from version store
    all_versions = version_store.list_all_graders()
    judges = []
    for grader_id in all_versions:
        latest = version_store.get_latest(grader_id)
        agreement = feedback_store.agreement_rate(judge_id=grader_id)
        judges.append({
            "grader_id": grader_id,
            "latest_version": latest.version if latest else 0,
            "config": latest.config if latest else {},
            "agreement_rate": agreement,
        })

    return {"judges": judges, "count": len(judges)}


@router.post("/feedback")
async def submit_feedback(
    request: Request,
    body: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Submit a human correction on a judgment."""
    from judges.human_feedback import HumanFeedback
    import time
    import uuid

    required = {"case_id", "judge_id", "judge_score", "human_score"}
    missing = required - set(body.keys())
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing fields: {missing}")

    feedback = HumanFeedback(
        feedback_id=uuid.uuid4().hex[:12],
        case_id=body["case_id"],
        judge_id=body["judge_id"],
        judge_score=float(body["judge_score"]),
        human_score=float(body["human_score"]),
        human_notes=body.get("human_notes", ""),
        created_at=time.time(),
    )

    store = request.app.state.human_feedback_store
    store.record(feedback)

    event_log = request.app.state.event_log
    event_log.append(
        event_type="judge_feedback_recorded",
        payload={"case_id": body["case_id"], "judge_id": body["judge_id"]},
    )

    return feedback.to_dict()


@router.get("/calibration")
async def calibration(request: Request, judge_id: str | None = None) -> dict[str, Any]:
    """Calibration dashboard data — agreement rates and disagreements."""
    feedback_store = request.app.state.human_feedback_store

    agreement = feedback_store.agreement_rate(judge_id=judge_id)
    disagreements = feedback_store.disagreements(judge_id=judge_id, limit=20)

    return {
        "agreement_rate": agreement,
        "disagreements": [d.to_dict() for d in disagreements],
        "total_feedback": len(feedback_store.list_feedback(judge_id=judge_id)),
    }


@router.get("/drift")
async def drift(request: Request) -> dict[str, Any]:
    """Drift metrics from the drift monitor.

    Note: Drift detection requires judge verdicts to be collected over time.
    When no verdicts are available, the response will show zero alerts.
    Use /api/judges/feedback to submit verdicts that feed drift analysis.
    """
    drift_monitor = request.app.state.drift_monitor
    alerts = drift_monitor.run_all_checks(verdicts=[])
    return {
        "alerts": [a.to_dict() for a in alerts],
        "count": len(alerts),
        "configured_threshold": drift_monitor.drift_threshold,
        "note": "Drift detection requires accumulated judge verdicts. Submit verdicts via /api/judges/feedback to enable drift analysis." if not alerts else None,
    }
