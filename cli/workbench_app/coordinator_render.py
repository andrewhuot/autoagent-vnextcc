"""Render coordinator-worker events for the terminal transcript."""

from __future__ import annotations

import click

from builder.events import BuilderEvent, BuilderEventType
from builder.types import now_ts


_RUNNING_GLYPH = "●"
_BRANCH_GLYPH = "├─"
_END_GLYPH = "└─"
_DETAIL_GLYPH = "⎿"


def _role_label(event: BuilderEvent) -> str:
    """Return the readable worker/coordinator role label for an event."""
    role = str(event.payload.get("worker_role") or "").replace("_", " ").strip()
    return role or "worker"


def _truncate(text: str, *, width: int = 140) -> str:
    """Keep streaming worker notes from pushing the input chrome around."""
    clean = " ".join(str(text or "").split())
    if len(clean) <= width:
        return clean
    return clean[: width - 1].rstrip() + "…"


def _dim(text: str) -> str:
    return click.style(text, dim=True)


def _success(text: str) -> str:
    return click.style(text, fg="green")


def _error(text: str) -> str:
    return click.style(text, fg="red", bold=True)


def _warn(text: str) -> str:
    return click.style(text, fg="yellow")


def _worker_line(role: str, status: str, *, terminal: bool = False) -> str:
    glyph = _END_GLYPH if terminal else _BRANCH_GLYPH
    return _dim(f"  {glyph} ") + f"{role} {status}"


def _detail_line(text: str) -> str:
    return _dim(f"  │  {_DETAIL_GLYPH} {_truncate(text)}")


def format_coordinator_event(event: BuilderEvent) -> str | None:
    """Return one Claude-Code-style transcript line for a coordinator event.

    Worker state is rendered as a compact tree rather than a raw log stream,
    matching Claude Code's progress blocks while staying native to the
    Python terminal renderer.
    """
    payload = event.payload
    event_type = event.event_type
    role = _role_label(event)
    if event_type == BuilderEventType.COORDINATOR_EXECUTION_STARTED:
        return click.style(
            f"{_RUNNING_GLYPH} Coordinator started {payload.get('worker_count', 0)} worker(s)",
            fg="cyan",
            bold=True,
        )
    if event_type == BuilderEventType.WORKER_GATHERING_CONTEXT:
        return _worker_line(role, "gathering context")
    if event_type == BuilderEventType.WORKER_ACTING:
        return _worker_line(role, "acting")
    if event_type == BuilderEventType.WORKER_VERIFYING:
        return _worker_line(role, "verifying artifacts")
    if event_type == BuilderEventType.WORKER_MESSAGE_DELTA:
        text = _truncate(str(payload.get("text") or ""), width=120)
        if not text:
            return None
        return _detail_line(text)
    if event_type == BuilderEventType.WORKER_COMPLETED:
        summary = str(payload.get("summary") or "").strip()
        suffix = f": {summary}" if summary else ""
        return _success(_worker_line(role, f"completed{suffix}", terminal=True))
    if event_type == BuilderEventType.WORKER_FAILED:
        return _error(
            f"  {_END_GLYPH} ! {role} failed: {payload.get('error') or 'unknown error'}"
        )
    if event_type == BuilderEventType.WORKER_BLOCKED:
        return _warn(
            f"  {_END_GLYPH} ! {role} blocked: {payload.get('reason') or 'needs approval'}"
        )
    if event_type == BuilderEventType.COORDINATOR_SYNTHESIS_COMPLETED:
        summary = str(payload.get("summary") or "").strip()
        text = f"Synthesis complete: {summary}" if summary else "Synthesis complete"
        return _detail_line(text)
    if event_type == BuilderEventType.COORDINATOR_EXECUTION_COMPLETED:
        return _success(f"  {_END_GLYPH} ✓ Coordinator run completed")
    if event_type == BuilderEventType.COORDINATOR_EXECUTION_FAILED:
        return _error(
            f"  {_END_GLYPH} ! Coordinator run failed: {payload.get('error') or 'unknown error'}"
        )
    if event_type == BuilderEventType.COORDINATOR_EXECUTION_BLOCKED:
        return _warn(f"  {_END_GLYPH} ! Coordinator run blocked")
    return None


def render_progress_line(
    event: BuilderEvent,
    start_ts: float,
    *,
    now: float | None = None,
) -> str | None:
    """Return a Claude-style live transcript line for ``event``.

    The elapsed time is preserved as compact dim metadata at the end of the
    line instead of a noisy ``[Ns]`` log prefix, which keeps the transcript
    visually close to Claude Code's agent progress blocks.
    """
    line = format_coordinator_event(event)
    if line is None:
        return None
    reference = event.timestamp if event.timestamp else (now if now is not None else now_ts())
    elapsed = max(0, int(reference - start_ts))
    return f"{line}{_dim(f' · {elapsed}s')}"


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
