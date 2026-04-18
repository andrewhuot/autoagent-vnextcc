"""Proactive guidance endpoints for the web UI.

Thin wrapper over :mod:`cli.guidance`. Kept ignorant of the CLI status
screen so the web response is exactly a JSON projection of the engine's
output — no terminal escape codes, no slash-command flavour text.
"""

from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from cli.guidance import (
    build_context_from_workspace,
    history_path_for_workspace,
    select_suggestions,
)
from cli.guidance.engine import SuggestionHistory, evaluate_rules
from cli.workspace import discover_workspace


router = APIRouter(prefix="/api/guidance", tags=["guidance"])


class SuggestionPayload(BaseModel):
    """JSON projection of :class:`cli.guidance.Suggestion`."""

    id: str
    title: str
    body: str
    severity: str
    priority: int
    command: str | None = None
    href: str | None = None
    cooldown_seconds: float


class GuidanceResponse(BaseModel):
    """Shape returned by ``GET /api/guidance``."""

    workspace_valid: bool
    suggestions: list[SuggestionPayload]


def _suggestion_to_payload(suggestion: Any) -> SuggestionPayload:
    return SuggestionPayload(**{k: v for k, v in asdict(suggestion).items()})


def _load_workspace(request: Request) -> Any | None:
    """Prefer the app.state workspace resolved at startup; fall back to CWD."""
    ws_state = getattr(request.app.state, "workspace_state", None)
    workspace_root = getattr(ws_state, "workspace_root", None) if ws_state else None
    if workspace_root:
        ws = discover_workspace()
        if ws is not None and str(ws.root) == str(workspace_root):
            return ws
    return discover_workspace()


@router.get("", response_model=GuidanceResponse)
async def list_guidance(
    request: Request,
    include_suppressed: bool = False,
) -> GuidanceResponse:
    """Return active suggestions for the current workspace.

    ``include_suppressed=true`` bypasses cooldown / dismissal state so the
    web UI can offer a "show everything" reveal. Default behaviour mirrors
    the CLI status line.
    """
    workspace = _load_workspace(request)
    ctx = build_context_from_workspace(workspace)
    history = SuggestionHistory.load(history_path_for_workspace(workspace))
    if include_suppressed:
        suggestions = evaluate_rules(ctx)
    else:
        suggestions = select_suggestions(ctx, history=history, limit=5)
    return GuidanceResponse(
        workspace_valid=ctx.workspace_valid,
        suggestions=[_suggestion_to_payload(s) for s in suggestions],
    )


class DismissRequest(BaseModel):
    suggestion_id: str


@router.post("/dismiss", response_model=dict)
async def dismiss(request: Request, payload: DismissRequest) -> dict:
    """Mark a suggestion as dismissed so its cooldown kicks in."""
    workspace = _load_workspace(request)
    if workspace is None:
        raise HTTPException(status_code=400, detail="No workspace resolved.")
    history = SuggestionHistory.load(history_path_for_workspace(workspace))
    history.mark_dismissed(payload.suggestion_id, time.time())
    history.save()
    return {"dismissed": payload.suggestion_id}


@router.post("/accept", response_model=dict)
async def accept(request: Request, payload: DismissRequest) -> dict:
    """Record an accept — applies a longer cooldown than a dismiss."""
    workspace = _load_workspace(request)
    if workspace is None:
        raise HTTPException(status_code=400, detail="No workspace resolved.")
    history = SuggestionHistory.load(history_path_for_workspace(workspace))
    history.mark_accepted(payload.suggestion_id, time.time())
    history.save()
    return {"accepted": payload.suggestion_id}


@router.post("/reset", response_model=dict)
async def reset(request: Request) -> dict:
    """Wipe guidance history — useful for debugging the suggestion feed."""
    workspace = _load_workspace(request)
    if workspace is None:
        raise HTTPException(status_code=400, detail="No workspace resolved.")
    history = SuggestionHistory.load(history_path_for_workspace(workspace))
    history.shown_at.clear()
    history.dismissed_at.clear()
    history.accepted_at.clear()
    history.save()
    return {"status": "ok"}
