"""Shared progress event renderer for Stream B CLI workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import click

from cli.output import emit_stream_json


EventWriter = Callable[[str], None]


@dataclass
class ProgressRenderer:
    """Emit standard progress events in text, JSON, or stream-json form."""

    output_format: str = "text"
    writer: EventWriter | None = None
    render_text: bool = True
    events: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.writer is None:
            self.writer = click.echo

    def phase_started(self, phase: str, *, message: str) -> dict[str, Any]:
        """Emit a `phase_started` event."""
        return self._emit("phase_started", phase=phase, message=message)

    def phase_completed(self, phase: str, *, message: str) -> dict[str, Any]:
        """Emit a `phase_completed` event."""
        return self._emit("phase_completed", phase=phase, message=message)

    def artifact_written(self, artifact: str, *, path: str) -> dict[str, Any]:
        """Emit an `artifact_written` event."""
        return self._emit("artifact_written", artifact=artifact, path=path, message=path)

    def warning(self, *, message: str, phase: str | None = None) -> dict[str, Any]:
        """Emit a `warning` event."""
        return self._emit("warning", phase=phase, message=message)

    def error(self, *, message: str, phase: str | None = None) -> dict[str, Any]:
        """Emit an `error` event."""
        return self._emit("error", phase=phase, message=message)

    def next_action(self, message: str) -> dict[str, Any]:
        """Emit a `next_action` event."""
        return self._emit("next_action", message=message)

    def _emit(self, event: str, **payload: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "event": event,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        base.update({key: value for key, value in payload.items() if value is not None})
        self.events.append(base)

        if self.output_format == "stream-json":
            emit_stream_json(base, writer=self.writer)
        elif self.output_format == "text" and self.render_text:
            self.writer(self._render_text(base))
        return base

    @staticmethod
    def _render_text(event: dict[str, Any]) -> str:
        event_type = event.get("event", "event")
        message = str(event.get("message", "")).strip()
        phase = event.get("phase")
        artifact = event.get("artifact")
        path = event.get("path")

        if event_type == "phase_started":
            return f"[{phase}] starting: {message}"
        if event_type == "phase_completed":
            return f"[{phase}] done: {message}"
        if event_type == "artifact_written":
            return f"[artifact] {artifact}: {path}"
        if event_type == "warning":
            return f"[warning] {message}"
        if event_type == "error":
            return f"[error] {message}"
        if event_type == "next_action":
            return f"[next] {message}"
        return f"[{event_type}] {message}"
