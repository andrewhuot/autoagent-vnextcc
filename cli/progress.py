"""Shared progress event renderer for Stream B CLI workflows."""

from __future__ import annotations

import itertools
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import click

from cli.output import emit_stream_json


EventWriter = Callable[[str], None]


_SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
_SPINNER_ASCII_FRAMES = ("|", "/", "-", "\\")


def _spinner_enabled(output_format: str) -> bool:
    """Only animate when emitting text to a real TTY (not JSON, not CI, not pipes)."""
    if output_format != "text":
        return False
    if os.environ.get("AGENTLAB_NO_SPINNER"):
        return False
    if os.environ.get("CI"):
        return False
    stream = sys.stdout
    try:
        return bool(stream.isatty())
    except Exception:  # noqa: BLE001 - defensive against exotic streams
        return False


def _select_frames() -> tuple[str, ...]:
    """Pick unicode braille frames when the environment supports them, else ASCII."""
    encoding = (getattr(sys.stdout, "encoding", "") or "").lower()
    if "utf" in encoding:
        return _SPINNER_FRAMES
    return _SPINNER_ASCII_FRAMES


class PhaseSpinner:
    """TTY spinner that advertises the current long-running phase.

    Use as a context manager. `update(label)` swaps the visible phase without
    breaking the animation; `echo(text)` temporarily pauses frames so an
    external message prints cleanly.

    Silent no-op when stdout isn't a TTY or the output format is JSON.
    """

    def __init__(self, label: str, *, output_format: str = "text") -> None:
        self._label = label
        self._enabled = _spinner_enabled(output_format)
        self._frames = _select_frames()
        self._started_at = 0.0
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_width = 0

    @property
    def enabled(self) -> bool:
        """Whether the animation thread will actually render frames."""
        return self._enabled

    def __enter__(self) -> "PhaseSpinner":
        self._started_at = time.monotonic()
        if self._enabled:
            # Hide cursor for a cleaner animation; restore on exit.
            sys.stdout.write("\x1b[?25l")
            sys.stdout.flush()
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        elapsed = max(0.0, time.monotonic() - self._started_at)
        if self._thread is not None:
            self._stop_event.set()
            self._thread.join(timeout=1.0)
            self._thread = None
        if self._enabled:
            with self._lock:
                self._clear_line()
                marker = "✓" if exc is None else "✗"
                color = "green" if exc is None else "red"
                sys.stdout.write(click.style(f"{marker} {self._label} ({elapsed:.1f}s)\n", fg=color))
                sys.stdout.write("\x1b[?25h")  # restore cursor
                sys.stdout.flush()

    def update(self, label: str) -> None:
        """Swap the visible phase label mid-run."""
        with self._lock:
            self._label = label
            if self._enabled:
                self._clear_line()

    def echo(self, message: str) -> None:
        """Emit a message without the spinner frame interleaving."""
        with self._lock:
            if self._enabled:
                self._clear_line()
            click.echo(message)

    def _run(self) -> None:
        for frame in itertools.cycle(self._frames):
            if self._stop_event.is_set():
                return
            with self._lock:
                elapsed = time.monotonic() - self._started_at
                line = f"{frame} {self._label} ({elapsed:.1f}s)"
                self._clear_line()
                sys.stdout.write(line)
                sys.stdout.flush()
                self._last_width = len(line)
            if self._stop_event.wait(0.1):
                return

    def _clear_line(self) -> None:
        if self._last_width:
            sys.stdout.write("\r" + " " * self._last_width + "\r")
        else:
            sys.stdout.write("\r")
        sys.stdout.flush()
        self._last_width = 0


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

    def checkpoint(
        self,
        phase: str,
        *,
        path: str,
        next_cycle: int | None = None,
        completed_cycles: int | None = None,
    ) -> dict[str, Any]:
        """Emit a checkpoint event so operators can resume long-running work."""
        return self._emit(
            "checkpoint",
            phase=phase,
            path=path,
            next_cycle=next_cycle,
            completed_cycles=completed_cycles,
            message=path,
        )

    def recovery_hint(self, phase: str, *, message: str, command: str) -> dict[str, Any]:
        """Emit a recovery hint with a concrete command after interruptions or failures."""
        return self._emit("recovery_hint", phase=phase, message=message, command=command)

    def task_started(
        self,
        task_id: str,
        title: str,
        *,
        message: str | None = None,
        total: int | None = None,
    ) -> dict[str, Any]:
        """Emit a task-started event for a long-running unit of work."""
        return self._emit(
            "task_started",
            task_id=task_id,
            title=title,
            message=message or title,
            total=total,
        )

    def task_progress(
        self,
        task_id: str,
        title: str,
        note: str,
        *,
        current: int | None = None,
        total: int | None = None,
        progress: float | None = None,
    ) -> dict[str, Any]:
        """Emit structured task progress with normalized progress when possible."""
        resolved_progress = self._resolve_progress(current=current, total=total, progress=progress)
        return self._emit(
            "task_progress",
            task_id=task_id,
            title=title,
            note=note,
            message=note,
            current=current,
            total=total,
            progress=resolved_progress,
        )

    def task_completed(
        self,
        task_id: str,
        title: str,
        *,
        message: str | None = None,
        current: int | None = None,
        total: int | None = None,
        progress: float | None = None,
    ) -> dict[str, Any]:
        """Emit a task-completed event with final progress details."""
        resolved_progress = self._resolve_progress(current=current, total=total, progress=progress)
        return self._emit(
            "task_completed",
            task_id=task_id,
            title=title,
            message=message or title,
            current=current,
            total=total,
            progress=resolved_progress,
        )

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
    def _resolve_progress(
        *,
        current: int | None,
        total: int | None,
        progress: float | None,
    ) -> float | None:
        """Normalize explicit progress or derive it from current/total."""
        if progress is not None:
            try:
                value = float(progress)
            except (TypeError, ValueError):
                return None
            if value > 1.0 and value <= 100.0:
                value = value / 100.0
            return round(min(1.0, max(0.0, value)), 4)
        if current is None or total is None:
            return None
        try:
            total_value = int(total)
            current_value = int(current)
        except (TypeError, ValueError):
            return None
        if total_value <= 0:
            return None
        return round(min(1.0, max(0.0, current_value / total_value)), 4)

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
        if event_type == "checkpoint":
            next_cycle = event.get("next_cycle")
            suffix = f" (next cycle {next_cycle})" if next_cycle is not None else ""
            return f"[checkpoint] {phase}: {path}{suffix}"
        if event_type == "recovery_hint":
            command = event.get("command")
            return f"[recover] {message}: {command}"
        if event_type == "task_started":
            total = event.get("total")
            suffix = f" ({total} total)" if total is not None else ""
            return f"[task] {event.get('title', 'task')} started{suffix}"
        if event_type == "task_progress":
            title = event.get("title", "task")
            current = event.get("current")
            total = event.get("total")
            count = f" {current}/{total}" if current is not None and total is not None else ""
            return f"[task] {title}{count}: {message}"
        if event_type == "task_completed":
            title = event.get("title", "task")
            current = event.get("current")
            total = event.get("total")
            count = f" {current}/{total}" if current is not None and total is not None else ""
            return f"[task] {title}{count} done"
        if event_type == "warning":
            return f"[warning] {message}"
        if event_type == "error":
            return f"[error] {message}"
        if event_type == "next_action":
            return f"[next] {message}"
        return f"[{event_type}] {message}"
