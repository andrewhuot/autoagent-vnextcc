"""Compatibility bridge for coordinator events and stream-json envelopes."""

from __future__ import annotations

from typing import Any

from builder.events import BuilderEvent


def bridge_coordinator_event(event: BuilderEvent) -> dict[str, Any]:
    """Convert a :class:`BuilderEvent` into the legacy event envelope shape."""
    return {
        "event": event.event_type.value,
        "data": {
            "event_id": event.event_id,
            "session_id": event.session_id,
            "task_id": event.task_id,
            "timestamp": event.timestamp,
            **event.payload,
        },
    }


__all__ = ["bridge_coordinator_event"]
