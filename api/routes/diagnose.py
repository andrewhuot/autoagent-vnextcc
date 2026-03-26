"""Conversational diagnosis API endpoints."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from observer import Observer
from optimizer.diagnose_session import DiagnoseSession
from optimizer.memory import OptimizationAttempt
from optimizer.nl_editor import NLEditor

router = APIRouter(prefix="/api/diagnose", tags=["diagnose"])


def _ensure_sessions(request: Request) -> dict[str, DiagnoseSession]:
    sessions = getattr(request.app.state, "diagnose_sessions", None)
    if sessions is None:
        sessions = {}
        request.app.state.diagnose_sessions = sessions
    return sessions


def _build_session(request: Request) -> DiagnoseSession:
    store = request.app.state.conversation_store
    observer = getattr(request.app.state, "observer", Observer(store))
    proposer = getattr(request.app.state, "optimizer", None)
    eval_runner = request.app.state.eval_runner
    deployer = request.app.state.deployer
    editor = NLEditor(use_mock=True)
    return DiagnoseSession(
        store=store,
        observer=observer,
        proposer=proposer,
        eval_runner=eval_runner,
        deployer=deployer,
        nl_editor=editor,
    )


def _cluster_payload(session: DiagnoseSession) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, cluster in enumerate(session.clusters):
        rows.append(
            {
                "index": idx + 1,
                "bucket": cluster.failure_type,
                "count": cluster.count,
                "focused": idx == session.focused_index,
            }
        )
    return rows


def _actions_payload(session: DiagnoseSession) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    if session.pending_change is not None:
        actions.append({"label": "Apply Fix", "action": "apply"})
    actions.extend(
        [
            {"label": "Show Examples", "action": "show examples"},
            {"label": "Next Issue", "action": "next"},
            {"label": "Skip", "action": "skip"},
        ]
    )
    return actions


def _record_applied_change(request: Request, session: DiagnoseSession, payload: dict[str, Any]) -> None:
    memory = getattr(request.app.state, "optimization_memory", None)
    observer = getattr(request.app.state, "observer", None)
    if memory is None or observer is None:
        return

    report = observer.observe()
    attempt = OptimizationAttempt(
        attempt_id=str(uuid.uuid4())[:8],
        timestamp=time.time(),
        change_description=str(payload.get("description", "diagnose fix")),
        config_diff=str(payload.get("diff", "")),
        status="accepted",
        config_section=f"diagnose:{payload.get('bucket', 'unknown')}",
        score_before=float(payload.get("score_before", 0.0)),
        score_after=float(payload.get("score_after", 0.0)),
        significance_p_value=1.0,
        significance_delta=float(payload.get("score_after", 0.0)) - float(payload.get("score_before", 0.0)),
        significance_n=0,
        health_context=json.dumps(report.metrics.to_dict()),
    )
    memory.log(attempt)

    project_memory = getattr(request.app.state, "project_memory", None)
    if project_memory is not None:
        try:
            project_memory.update_with_intelligence(
                report=report,
                eval_score=float(payload.get("score_after", 0.0)),
                recent_changes=[attempt],
                skill_gaps=[],
            )
        except Exception:
            pass


@router.post("")
async def diagnose_overview(request: Request) -> dict[str, Any]:
    """Run diagnosis once and return clustered summary."""
    session = _build_session(request)
    summary = session.start()
    return {
        "summary": summary,
        "clusters": _cluster_payload(session),
    }


@router.post("/chat")
async def diagnose_chat(request: Request) -> dict[str, Any]:
    """Route one chat turn through a persistent DiagnoseSession."""
    body = await request.json()
    message = str(body.get("message", "")).strip()
    session_id = str(body.get("session_id", "")).strip()

    sessions = _ensure_sessions(request)
    if session_id:
        session = sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"Unknown session_id: {session_id}")
    else:
        session = _build_session(request)
        session_id = str(uuid.uuid4())
        sessions[session_id] = session
        intro = session.start()
        if not message:
            return {
                "response": intro,
                "actions": _actions_payload(session),
                "clusters": _cluster_payload(session),
                "session_id": session_id,
            }

    had_pending_change = session.pending_change is not None
    pending_description = session.pending_description
    focused_bucket = session.focused_cluster.failure_type if session.focused_cluster is not None else "unknown"
    response = session.handle_input(message)
    if had_pending_change and session.pending_change is None and response.lower().startswith("applied"):
        _record_applied_change(
            request,
            session,
            {
                "description": pending_description or "diagnose fix",
                "diff": pending_description or "diagnose fix",
                "bucket": focused_bucket,
                "score_before": 0.0,
                "score_after": 0.0,
            },
        )

    return {
        "response": response,
        "actions": _actions_payload(session),
        "clusters": _cluster_payload(session),
        "session_id": session_id,
    }
