"""Render coordinator-worker events for the terminal transcript."""

from __future__ import annotations

from builder.events import BuilderEvent, BuilderEventType
from builder.types import now_ts


def format_coordinator_event(event: BuilderEvent) -> str | None:
    """Return one compact transcript line for a coordinator event.

    The renderer intentionally keeps events terse: the Workbench transcript
    should feel live without flooding the screen with raw JSON payloads.
    """
    payload = event.payload
    event_type = event.event_type
    role = str(payload.get("worker_role") or "").replace("_", " ")
    if event_type == BuilderEventType.COORDINATOR_EXECUTION_STARTED:
        return f"  Coordinator started {payload.get('worker_count', 0)} worker(s)."
    if event_type == BuilderEventType.WORKER_GATHERING_CONTEXT:
        return f"  [{role}] gathering context"
    if event_type == BuilderEventType.WORKER_ACTING:
        return f"  [{role}] acting"
    if event_type == BuilderEventType.WORKER_VERIFYING:
        return f"  [{role}] verifying artifacts"
    if event_type == BuilderEventType.WORKER_MESSAGE_DELTA:
        text = " ".join(str(payload.get("text") or "").split())
        if not text:
            return None
        clipped = text[:160] + ("..." if len(text) > 160 else "")
        return f"  [{role}] {clipped}"
    if event_type == BuilderEventType.WORKER_COMPLETED:
        summary = str(payload.get("summary") or "").strip()
        suffix = f": {summary}" if summary else ""
        return f"  [{role}] completed{suffix}"
    if event_type == BuilderEventType.WORKER_FAILED:
        return f"  [{role}] failed: {payload.get('error') or 'unknown error'}"
    if event_type == BuilderEventType.WORKER_BLOCKED:
        return f"  [{role}] blocked: {payload.get('reason') or 'needs approval'}"
    if event_type == BuilderEventType.COORDINATOR_SYNTHESIS_COMPLETED:
        summary = str(payload.get("summary") or "").strip()
        return f"  Synthesis complete: {summary}" if summary else "  Synthesis complete."
    if event_type == BuilderEventType.COORDINATOR_EXECUTION_COMPLETED:
        return "  Coordinator run completed."
    if event_type == BuilderEventType.COORDINATOR_EXECUTION_FAILED:
        return f"  Coordinator run failed: {payload.get('error') or 'unknown error'}"
    if event_type == BuilderEventType.COORDINATOR_EXECUTION_BLOCKED:
        return "  Coordinator run blocked."
    return None


def render_progress_line(
    event: BuilderEvent,
    start_ts: float,
    *,
    now: float | None = None,
) -> str | None:
    """Return a transcript line for ``event`` prefixed with elapsed seconds.

    Used by the live REPL loop to echo each coordinator event as it arrives,
    with a short ``[Ns]`` hint so the operator can feel the turn's progress
    instead of watching a dead prompt. Returns ``None`` for events that
    :func:`format_coordinator_event` chooses to skip (e.g. noisy deltas).
    """
    line = format_coordinator_event(event)
    if line is None:
        return None
    reference = event.timestamp if event.timestamp else (now if now is not None else now_ts())
    elapsed = max(0, int(reference - start_ts))
    return f"  [{elapsed}s]{line[1:] if line.startswith(' ') else ' ' + line}"


def worker_phase_verb(event: BuilderEvent) -> str | None:
    """Map a worker-phase event to an ``EffortIndicator.set_verb`` string.

    Returns ``None`` for events that don't imply a phase change so callers
    can leave the spinner verb untouched. The shape — ``"<role> <phase>"``
    — matches what the Workbench footer renders beside the spinner frame.
    """
    payload = event.payload
    role = str(payload.get("worker_role") or "").replace("_", " ").strip()
    role_prefix = f"{role} " if role else ""
    event_type = event.event_type
    if event_type == BuilderEventType.WORKER_GATHERING_CONTEXT:
        return f"{role_prefix}gathering context".strip()
    if event_type == BuilderEventType.WORKER_ACTING:
        return f"{role_prefix}acting".strip()
    if event_type == BuilderEventType.WORKER_VERIFYING:
        return f"{role_prefix}verifying".strip()
    if event_type == BuilderEventType.WORKER_COMPLETED:
        return f"{role_prefix}completed".strip()
    if event_type == BuilderEventType.WORKER_FAILED:
        return f"{role_prefix}failed".strip()
    if event_type == BuilderEventType.WORKER_BLOCKED:
        return f"{role_prefix}blocked".strip()
    if event_type == BuilderEventType.COORDINATOR_SYNTHESIS_COMPLETED:
        return "synthesizing"
    if event_type == BuilderEventType.COORDINATOR_EXECUTION_STARTED:
        return "coordinator starting"
    if event_type == BuilderEventType.COORDINATOR_EXECUTION_COMPLETED:
        return "coordinator completed"
    return None


__all__ = [
    "format_coordinator_event",
    "render_progress_line",
    "worker_phase_verb",
]
