"""Server-Sent Events (SSE) endpoint for live optimization progress.

The stream has two modes:

* ``GET /api/optimize/stream?task_id=<id>`` — **real** events emitted by a
  running optimize task. Subscribe to the in-memory ``OptimizeEventBus``
  attached to ``app.state.optimize_event_bus`` and forward events 1:1 until
  the task closes. This is the default and what the UI should use.
* ``GET /api/optimize/stream?simulated=1&cycles=N`` — the legacy hard-coded
  demo stream. Preserved only for docs/demos. Every ``data`` payload carries
  ``"source": "simulated"`` so the UI can clearly label it.

Requests with neither ``task_id`` nor ``simulated=1`` return 400 so we never
silently fall back into fake data.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncGenerator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from api.optimize_event_bus import CLOSE_SENTINEL

router = APIRouter(prefix="/api/optimize", tags=["optimize"])


_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _format_sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.get("/stream")
async def optimize_stream(
    request: Request,
    task_id: str | None = None,
    simulated: int = 0,
    cycles: int = 3,
) -> StreamingResponse:
    """Stream optimization events.

    Args:
        task_id: the optimize task to follow. Events are emitted by
            ``run_optimize`` into ``app.state.optimize_event_bus`` and
            forwarded here 1:1.
        simulated: when 1, serve the legacy hard-coded demo stream.
        cycles: number of cycles when ``simulated=1`` (ignored otherwise).
    """

    if task_id:
        return StreamingResponse(
            _real_event_stream(request, task_id),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )

    if simulated:
        return StreamingResponse(
            _simulated_event_stream(cycles=cycles),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )

    raise HTTPException(
        status_code=400,
        detail=(
            "Provide task_id=<optimize_task_id> to stream real events, or "
            "simulated=1 to serve the demo stream."
        ),
    )


async def _real_event_stream(request: Request, task_id: str) -> AsyncGenerator[str, None]:
    bus = getattr(request.app.state, "optimize_event_bus", None)
    task_manager = getattr(request.app.state, "task_manager", None)
    if bus is None:
        yield _format_sse(
            "error",
            {"task_id": task_id, "error": "optimize_event_bus not configured"},
        )
        return

    # If the bus has never heard of this task_id, require the task_manager to
    # confirm it exists — otherwise clients stream forever against nothing.
    if task_manager is not None and not bus.is_known(task_id):
        task = task_manager.get_task(task_id)
        if task is None:
            yield _format_sse(
                "error",
                {"task_id": task_id, "error": "unknown optimize task"},
            )
            return

    queue = await bus.subscribe(task_id)
    heartbeat_interval = 15.0
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=heartbeat_interval)
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
                continue
            if payload is CLOSE_SENTINEL or payload.get("event") == "__close__":
                break
            event_name = str(payload.get("event") or "message")
            data = payload.get("data") or {}
            if isinstance(data, dict):
                data.setdefault("task_id", task_id)
                data.setdefault("source", "optimizer")
            yield _format_sse(event_name, data)
    finally:
        bus.unsubscribe(task_id, queue)


async def _simulated_event_stream(cycles: int) -> AsyncGenerator[str, None]:
    """Legacy demo stream. Every payload is labeled source=simulated."""
    baseline_score = 0.72
    current_score = baseline_score

    proposals = [
        {
            "change_description": "Enhance routing rules with semantic disambiguation patterns",
            "config_section": "router.disambiguation_strategy",
            "reasoning": "Failures show ambiguous intent classification; adding semantic patterns should improve routing accuracy by 8-12%",
        },
        {
            "change_description": "Tighten safety guardrails for PII handling",
            "config_section": "safety.pii_detection",
            "reasoning": "Safety violations concentrated in personal data scenarios; stricter guardrails will reduce violations by 40%",
        },
        {
            "change_description": "Add few-shot examples for edge cases",
            "config_section": "prompts.few_shot_examples",
            "reasoning": "Quality issues stem from unfamiliar user patterns; targeted examples should boost coverage",
        },
    ]

    for cycle in range(1, cycles + 1):
        yield _format_sse(
            "cycle_start",
            {"cycle": cycle, "total": cycles, "source": "simulated"},
        )
        await asyncio.sleep(0.1)

        yield _format_sse(
            "diagnosis",
            {
                "failure_buckets": {
                    "routing_error": 15,
                    "safety_violation": 8,
                    "quality_issue": 12,
                    "tool_error": 5,
                },
                "dominant": "routing_error",
                "total_failures": 40,
                "source": "simulated",
            },
        )
        await asyncio.sleep(0.5)

        proposal_result = {**proposals[(cycle - 1) % len(proposals)], "source": "simulated"}
        yield _format_sse("proposal", proposal_result)
        await asyncio.sleep(0.5)

        score_before = current_score
        improvement = 0.03 + (0.02 * (cycles - cycle))
        score_after = min(score_before + improvement, 0.95)
        yield _format_sse(
            "evaluation",
            {
                "score_before": round(score_before, 4),
                "score_after": round(score_after, 4),
                "improvement": round(improvement, 4),
                "source": "simulated",
            },
        )
        await asyncio.sleep(0.5)

        accepted = improvement > 0.01
        yield _format_sse(
            "decision",
            {
                "accepted": accepted,
                "p_value": 0.02 if accepted else 0.15,
                "effect_size": round(improvement / 0.02, 2) if accepted else 0.5,
                "source": "simulated",
            },
        )
        await asyncio.sleep(0.5)

        if accepted:
            current_score = score_after

        yield _format_sse(
            "cycle_complete",
            {
                "cycle": cycle,
                "best_score": round(current_score, 4),
                "change_description": proposal_result["change_description"],
                "score_delta": round(score_after - score_before, 4),
                "accepted": accepted,
                "source": "simulated",
            },
        )
        await asyncio.sleep(0.3)

    yield _format_sse(
        "optimization_complete",
        {
            "cycles": cycles,
            "baseline": round(baseline_score, 4),
            "final": round(current_score, 4),
            "improvement": round(current_score - baseline_score, 4),
            "source": "simulated",
        },
    )
