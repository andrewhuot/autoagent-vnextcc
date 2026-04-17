"""Improvements API — unified view of optimizer proposals and their lineage.

An *improvement* is one optimizer-proposed change, keyed by ``attempt_id``.
This router joins data that already lives in the platform:

* :class:`OptimizationMemory` — the proposal, its config diff, and the
  accepted/rejected verdict.
* :class:`PendingReviewStore` — human-approval items awaiting review.
* :class:`ImprovementLineageStore` — deploy/rollback/measurement events after
  the proposal is accepted.

and exposes them under a single noun. See ``docs/GLOSSARY.md`` for the
terminology rationale — every existing "proposal", "opportunity", and "change
card" surfaces the same record through this API.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from api.models import PendingReview
from evals.runner import TestCase

router = APIRouter(prefix="/api/improvements", tags=["improvements"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


ImprovementStatus = Literal[
    "proposed",
    "pending_review",
    "accepted",
    "rejected",
    "verified",
    "deployed_canary",
    "promoted",
    "rolled_back",
    "measured",
]


class LineageEventOut(BaseModel):
    event_id: str
    event_type: str
    timestamp: float
    version: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ImprovementRecord(BaseModel):
    attempt_id: str
    status: ImprovementStatus
    raw_status: str
    change_description: str
    config_section: str
    timestamp: float
    score_before: float | None = None
    score_after: float | None = None
    score_delta: float | None = None
    significance_p_value: float | None = None
    pending_review: bool = False
    eval_run_id: str | None = None
    eval_result_run_id: str | None = None
    deployment_id: str | None = None
    deployed_version: int | None = None
    verification: dict[str, Any] | None = None
    measurement: dict[str, Any] | None = None
    lineage: list[LineageEventOut] = Field(default_factory=list)
    rejection_reason: str | None = None


class ImprovementsResponse(BaseModel):
    total: int
    filtered: int
    items: list[ImprovementRecord]


class MeasureRequest(BaseModel):
    eval_run_id: str | None = None
    score_before: float | None = None
    score_after: float | None = None
    notes: str | None = None


class VerifyRequest(BaseModel):
    strict_live: bool = False
    config_path: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _classify(attempt_status: str, has_pending_review: bool, lineage_types: list[str]) -> ImprovementStatus:
    if "promote" in lineage_types:
        if "measurement" in lineage_types:
            return "measured"
        return "promoted"
    if "rollback" in lineage_types:
        return "rolled_back"
    if "deploy_canary" in lineage_types:
        return "deployed_canary"
    if has_pending_review:
        return "pending_review"
    if "verification" in lineage_types:
        return "verified"
    if attempt_status.startswith("rejected"):
        return "rejected"
    if attempt_status == "accepted":
        return "accepted"
    return "proposed"


def _rejection_reason(status: str) -> str | None:
    if not status.startswith("rejected"):
        return None
    return status.replace("rejected_", "").replace("_", " ") or None


def _coerce_pending_review(review: Any) -> PendingReview:
    if isinstance(review, PendingReview):
        return review
    if hasattr(review, "model_dump"):
        return PendingReview.model_validate(review.model_dump(mode="python"))
    if isinstance(review, dict):
        return PendingReview.model_validate(review)
    if hasattr(review, "__dict__"):
        return PendingReview.model_validate(vars(review))
    raise TypeError(f"Unsupported pending review payload: {type(review)!r}")


def _build_test_cases_from_result_set(result_set: Any) -> list[TestCase]:
    cases: list[TestCase] = []
    for example in list(getattr(result_set, "examples", []) or []):
        expected = example.expected if isinstance(example.expected, dict) else {}
        input_payload = example.input if isinstance(example.input, dict) else {}
        cases.append(
            TestCase(
                id=str(getattr(example, "example_id", "")),
                category=str(getattr(example, "category", "unknown") or "unknown"),
                user_message=str(input_payload.get("user_message", "")),
                expected_specialist=str(expected.get("expected_specialist", "")),
                expected_behavior=str(expected.get("expected_behavior", "answer")),
                safety_probe=bool(
                    expected.get("safety_probe", False)
                    or getattr(example, "category", "") == "safety"
                ),
                expected_keywords=[str(item) for item in list(expected.get("expected_keywords", []) or [])],
                expected_tool=expected.get("expected_tool"),
                split=str(expected.get("split")) if expected.get("split") is not None else None,
                reference_answer=str(expected.get("reference_answer", "")),
            )
        )
    return cases


def _build_test_cases_from_eval_payload(eval_payload: dict[str, Any]) -> list[TestCase]:
    cases: list[TestCase] = []
    for item in list(eval_payload.get("cases", []) or []):
        if not isinstance(item, dict):
            continue
        input_payload = dict(item.get("input_payload") or {})
        expected = dict(item.get("expected_payload") or {})
        user_message = str(item.get("user_message") or input_payload.get("user_message") or "")
        cases.append(
            TestCase(
                id=str(item.get("case_id") or ""),
                category=str(item.get("category") or "unknown"),
                user_message=user_message,
                expected_specialist=str(expected.get("expected_specialist", "")),
                expected_behavior=str(expected.get("expected_behavior", "answer")),
                safety_probe=bool(expected.get("safety_probe", False) or item.get("category") == "safety"),
                expected_keywords=[str(part) for part in list(expected.get("expected_keywords", []) or [])],
                expected_tool=expected.get("expected_tool"),
                split=str(expected.get("split")) if expected.get("split") is not None else None,
                reference_answer=str(expected.get("reference_answer", "")),
            )
        )
    return cases


def _record_from(attempt: Any, view: Any | None, pending_ids: set[str]) -> ImprovementRecord:
    lineage = list(getattr(view, "events", []) or [])
    lineage_out = [
        LineageEventOut(
            event_id=ev.event_id,
            event_type=ev.event_type,
            timestamp=ev.timestamp,
            version=ev.version,
            payload=ev.payload,
        )
        for ev in lineage
    ]
    lineage_types = [ev.event_type for ev in lineage_out]
    status = _classify(attempt.status, attempt.attempt_id in pending_ids, lineage_types)
    deployed_version = getattr(view, "deployed_version", None)
    deployment_id = getattr(view, "deployment_id", None)

    measurement: dict[str, Any] | None = None
    for ev in reversed(lineage_out):
        if ev.event_type == "measurement":
            measurement = ev.payload
            break

    verification: dict[str, Any] | None = None
    if getattr(view, "verification_id", None) is not None:
        verification = {
            "verification_id": view.verification_id,
            "status": view.verification_status,
            "eval_run_id": view.verification_eval_run_id,
            "phase": view.verification_phase,
            "score_before": view.verification_score_before,
            "score_after": view.verification_score_after,
            "composite_delta": view.verification_composite_delta,
        }

    score_before = float(attempt.score_before) if attempt.score_before is not None else None
    score_after = float(attempt.score_after) if attempt.score_after is not None else None
    delta: float | None
    if score_before is not None and score_after is not None:
        delta = round(score_after - score_before, 4)
    else:
        delta = None

    return ImprovementRecord(
        attempt_id=attempt.attempt_id,
        status=status,
        raw_status=attempt.status,
        change_description=attempt.change_description or "",
        config_section=attempt.config_section or "",
        timestamp=float(attempt.timestamp),
        score_before=score_before,
        score_after=score_after,
        score_delta=delta,
        significance_p_value=(
            float(attempt.significance_p_value)
            if attempt.significance_p_value is not None
            else None
        ),
        pending_review=attempt.attempt_id in pending_ids,
        eval_run_id=getattr(view, "eval_run_id", None),
        eval_result_run_id=getattr(view, "eval_result_run_id", None),
        deployment_id=deployment_id,
        deployed_version=deployed_version,
        verification=verification,
        measurement=measurement,
        lineage=lineage_out,
        rejection_reason=_rejection_reason(attempt.status),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=ImprovementsResponse)
async def list_improvements(
    request: Request,
    status: ImprovementStatus | None = None,
    limit: int = 50,
) -> ImprovementsResponse:
    """List improvements, newest first. Filter by classified status when given."""
    memory = request.app.state.optimization_memory
    lineage = getattr(request.app.state, "improvement_lineage", None)
    pending_store = getattr(request.app.state, "pending_review_store", None)

    attempts = list(memory.get_all())
    attempts.sort(key=lambda a: a.timestamp, reverse=True)

    pending_ids: set[str] = set()
    if pending_store is not None:
        try:
            pending_ids = {r.attempt_id for r in pending_store.list_pending(limit=500)}
        except Exception:
            pending_ids = set()

    records: list[ImprovementRecord] = []
    for attempt in attempts:
        view = lineage.view_attempt(attempt.attempt_id) if lineage is not None else None
        records.append(_record_from(attempt, view, pending_ids))

    filtered = [r for r in records if status is None or r.status == status]
    return ImprovementsResponse(
        total=len(records),
        filtered=len(filtered),
        items=filtered[:limit],
    )


@router.get("/{attempt_id}", response_model=ImprovementRecord)
async def get_improvement(attempt_id: str, request: Request) -> ImprovementRecord:
    memory = request.app.state.optimization_memory
    lineage = getattr(request.app.state, "improvement_lineage", None)
    pending_store = getattr(request.app.state, "pending_review_store", None)

    for attempt in memory.get_all():
        if attempt.attempt_id == attempt_id:
            pending_ids: set[str] = set()
            if pending_store is not None:
                try:
                    pending_ids = {
                        r.attempt_id for r in pending_store.list_pending(limit=500)
                    }
                except Exception:
                    pending_ids = set()
            view = lineage.view_attempt(attempt_id) if lineage is not None else None
            return _record_from(attempt, view, pending_ids)
    raise HTTPException(status_code=404, detail=f"No improvement with attempt_id={attempt_id}")


@router.post("/{attempt_id}/measure", response_model=ImprovementRecord)
async def measure_improvement(
    attempt_id: str,
    body: MeasureRequest,
    request: Request,
) -> ImprovementRecord:
    """Record a post-deploy measurement against an improvement."""
    memory = request.app.state.optimization_memory
    lineage = getattr(request.app.state, "improvement_lineage", None)
    if lineage is None:
        raise HTTPException(status_code=500, detail="improvement_lineage not configured")

    # Verify attempt exists
    if not any(a.attempt_id == attempt_id for a in memory.get_all()):
        raise HTTPException(status_code=404, detail=f"No improvement with attempt_id={attempt_id}")

    delta: float | None
    if body.score_before is not None and body.score_after is not None:
        delta = body.score_after - body.score_before
    else:
        delta = None

    lineage.record_measurement(
        attempt_id=attempt_id,
        measurement_id=body.eval_run_id or f"measurement-{attempt_id}",
        composite_delta=delta,
        eval_run_id=body.eval_run_id,
        score_before=body.score_before,
        score_after=body.score_after,
        delta=delta,
        notes=body.notes,
    )
    return await get_improvement(attempt_id, request)


@router.post("/{attempt_id}/verify", response_model=ImprovementRecord)
async def verify_improvement(
    attempt_id: str,
    request: Request,
    body: VerifyRequest | None = None,
) -> ImprovementRecord:
    """Rerun the baseline cases against the candidate or active config."""

    memory = request.app.state.optimization_memory
    lineage = getattr(request.app.state, "improvement_lineage", None)
    if lineage is None:
        raise HTTPException(status_code=500, detail="improvement_lineage not configured")

    attempt = next((item for item in memory.get_all() if item.attempt_id == attempt_id), None)
    if attempt is None:
        raise HTTPException(status_code=404, detail=f"No improvement with attempt_id={attempt_id}")

    pending_store = getattr(request.app.state, "pending_review_store", None)
    raw_review = pending_store.get_review(attempt_id) if pending_store is not None else None
    review = _coerce_pending_review(raw_review) if raw_review is not None else None
    view = lineage.view_attempt(attempt_id)

    config: dict[str, Any]
    phase = "post_deploy"
    if body is not None and body.config_path:
        config_path = Path(body.config_path)
        if not config_path.exists():
            raise HTTPException(status_code=404, detail=f"Config file not found: {body.config_path}")
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    elif review is not None:
        config = dict(review.proposed_config or {})
        phase = "pre_deploy"
    else:
        deployer = getattr(request.app.state, "deployer", None)
        if deployer is None:
            raise HTTPException(status_code=500, detail="deployer not configured")
        active = deployer.get_active_config()
        if active is None:
            raise HTTPException(status_code=409, detail="No active config available for verification")
        config = dict(active or {})

    baseline_eval_run_id = view.eval_run_id or (review.baseline_eval_run_id if review is not None else None)
    baseline_result_run_id = view.eval_result_run_id or (review.baseline_result_run_id if review is not None else None)

    results_store = getattr(request.app.state, "results_store", None)
    result_set = (
        results_store.get_run(baseline_result_run_id)
        if results_store is not None and baseline_result_run_id
        else None
    )
    if result_set is not None:
        cases = _build_test_cases_from_result_set(result_set)
    else:
        task_manager = getattr(request.app.state, "task_manager", None)
        eval_task = task_manager.get_task(baseline_eval_run_id) if task_manager is not None and baseline_eval_run_id else None
        task_result = eval_task.result if eval_task is not None and isinstance(eval_task.result, dict) else {}
        cases = _build_test_cases_from_eval_payload(task_result)
    if not cases:
        raise HTTPException(
            status_code=409,
            detail="Verification requires baseline eval cases from structured results or eval task payloads",
        )

    eval_runner = getattr(request.app.state, "eval_runner", None)
    if eval_runner is None:
        raise HTTPException(status_code=500, detail="eval_runner not configured")

    score = eval_runner.run_cases(cases, config=config, split="all")
    score_before = None
    if attempt.score_before is not None:
        score_before = float(attempt.score_before)
    elif review is not None:
        score_before = float(review.score_before)
    score_after = float(score.composite)

    verification_eval_run_id = str(getattr(score, "run_id", "") or f"verify-{attempt_id}")
    verification_status = "passed"
    if score.total_cases > 0 and (score.passed_cases < score.total_cases or score.safety_failures > 0):
        verification_status = "failed"

    lineage.record_verification(
        attempt_id=attempt_id,
        verification_id=verification_eval_run_id,
        status=verification_status,
        eval_run_id=verification_eval_run_id,
        baseline_eval_run_id=baseline_eval_run_id,
        baseline_result_run_id=baseline_result_run_id,
        score_before=score_before,
        score_after=score_after,
        phase=phase,
        target="candidate" if review is not None else "active",
        total_cases=score.total_cases,
        passed_cases=score.passed_cases,
        safety_failures=score.safety_failures,
    )
    return await get_improvement(attempt_id, request)
