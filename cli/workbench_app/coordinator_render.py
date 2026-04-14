"""Render coordinator-worker events for the terminal transcript."""

from __future__ import annotations

from builder.events import BuilderEvent, BuilderEventType


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


__all__ = ["format_coordinator_event"]
