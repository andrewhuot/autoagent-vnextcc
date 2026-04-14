"""`/optimize` slash command — streams ``agentlab optimize`` into the transcript.

T10 adds a streaming slash command that shells out to the existing
``agentlab optimize`` Click command, pipes its ``--output-format stream-json``
output through :func:`cli.workbench_render.format_workbench_event`, and
surfaces a per-cycle summary when the run finishes.

The subprocess runner is an injectable seam (:data:`StreamRunner`) so tests
don't need to spawn a real process — they hand in a callable that yields
pre-baked event dicts. The default runner uses :mod:`subprocess` with a
line-buffered pipe and ``sys.executable -m`` so the child picks up the same
interpreter + venv as the workbench.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator, Sequence

import click

from cli.workbench_app.cancellation import CancellationToken
from cli.workbench_app.commands import LocalCommand, OnDoneResult, on_done
from cli.workbench_app.slash import SlashContext
from cli.workbench_render import format_workbench_event


StreamEvent = dict[str, Any]
"""One JSON event emitted by a stream-json subprocess."""

StreamRunner = Callable[..., Iterator[StreamEvent]]
"""Given ``(args,)`` yield parsed JSON events until the process exits.

Raise :class:`OptimizeCommandError` for non-zero exits or parse failures.
Tests inject a generator in place of the real subprocess.
"""


class OptimizeCommandError(RuntimeError):
    """Raised by a :data:`StreamRunner` when the subprocess fails."""


@dataclass(frozen=True)
class OptimizeSummary:
    """Counters the `/optimize` handler uses to build the `onDone` result line."""

    events: int = 0
    cycles_completed: int = 0
    phases_completed: int = 0
    artifacts: tuple[str, ...] = ()
    warnings: int = 0
    errors: int = 0
    next_action: str | None = None
    exit_code: int | None = None


# The phase label ``optimize`` uses for per-cycle ``phase_completed`` events.
# See ``runner.optimize`` (~line 4426) — every completed cycle emits one of
# these with a "Cycle N <status>" message. Tracking this gives us a cycle
# counter in the summary without re-implementing cycle bookkeeping.
_CYCLE_PHASE = "optimize-cycle"


# ---------------------------------------------------------------------------
# Default subprocess runner
# ---------------------------------------------------------------------------


def _default_stream_runner(
    args: Sequence[str],
    *,
    cancellation: CancellationToken | None = None,
) -> Iterator[StreamEvent]:
    """Spawn ``agentlab optimize`` and yield stream-json events line by line.

    ``args`` are the extra CLI args after ``optimize`` (e.g. ``["--cycles",
    "3"]``). ``--output-format stream-json`` is appended automatically so
    callers don't need to remember the flag. When ``cancellation`` is
    provided, ctrl-c at the app level kills the subprocess via
    :class:`CancellationToken` and the reader breaks out cleanly.
    """
    cmd: list[str] = [
        sys.executable,
        "-m",
        "runner",
        "optimize",
        "--output-format",
        "stream-json",
        *args,
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    exit_code = 0
    if cancellation is not None:
        cancellation.register_process(proc)
    try:
        for raw in proc.stdout:
            if cancellation is not None and cancellation.cancelled:
                break
            line = raw.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                yield {"event": "warning", "message": line}
        exit_code = proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        if cancellation is not None:
            cancellation.unregister_process(proc)
    if exit_code != 0 and not (cancellation is not None and cancellation.cancelled):
        raise OptimizeCommandError(
            f"optimize exited with status {exit_code}"
        )


# ---------------------------------------------------------------------------
# Event → transcript line rendering
# ---------------------------------------------------------------------------


def _render_event(event: StreamEvent) -> str | None:
    """Map a stream-json event onto a transcript line."""
    event_name = str(event.get("event", ""))
    if not event_name:
        return None
    payload = {k: v for k, v in event.items() if k != "event"}
    return format_workbench_event(event_name, payload)


def _summarise(events: Iterable[StreamEvent]) -> Iterator[tuple[StreamEvent, OptimizeSummary]]:
    """Iterate events yielding ``(event, running_summary)`` tuples."""
    counters = {
        "events": 0,
        "cycles_completed": 0,
        "phases_completed": 0,
        "warnings": 0,
        "errors": 0,
    }
    artifacts: list[str] = []
    next_action: str | None = None
    for event in events:
        counters["events"] += 1
        name = event.get("event")
        if name == "phase_completed":
            counters["phases_completed"] += 1
            if event.get("phase") == _CYCLE_PHASE:
                counters["cycles_completed"] += 1
        elif name == "artifact_written":
            path = event.get("path") or event.get("message")
            if path:
                artifacts.append(str(path))
        elif name == "warning":
            counters["warnings"] += 1
        elif name == "error":
            counters["errors"] += 1
        elif name == "next_action":
            message = event.get("message")
            if message:
                next_action = str(message)
        yield event, OptimizeSummary(
            events=counters["events"],
            cycles_completed=counters["cycles_completed"],
            phases_completed=counters["phases_completed"],
            artifacts=tuple(artifacts),
            warnings=counters["warnings"],
            errors=counters["errors"],
            next_action=next_action,
        )


def _format_summary(summary: OptimizeSummary) -> str:
    """Build the ``onDone`` result line from final counters."""
    parts: list[str] = [f"{summary.events} events"]
    if summary.cycles_completed:
        label = "cycle" if summary.cycles_completed == 1 else "cycles"
        parts.append(f"{summary.cycles_completed} {label}")
    if summary.artifacts:
        parts.append(f"{len(summary.artifacts)} artifacts")
    if summary.warnings:
        parts.append(f"{summary.warnings} warnings")
    if summary.errors:
        parts.append(click.style(f"{summary.errors} errors", fg="red"))
    status = "failed" if summary.errors else "complete"
    return click.style(
        f"  /optimize {status} — {', '.join(parts)}",
        fg=("red" if summary.errors else "green"),
        bold=True,
    )


# ---------------------------------------------------------------------------
# Handler + registration
# ---------------------------------------------------------------------------


def make_optimize_handler(
    runner: StreamRunner | None = None,
) -> Callable[..., OnDoneResult]:
    """Return a slash handler closed over ``runner`` (defaults to real subprocess)."""
    active_runner = runner or _default_stream_runner

    def _handle_optimize(ctx: SlashContext, *args: str) -> OnDoneResult:
        stream_args = _parse_args(args)
        echo = ctx.echo
        echo(click.style(
            f"  /optimize starting — agentlab optimize {shlex.join(stream_args)}".rstrip(),
            fg="cyan",
        ))

        cancellation = ctx.cancellation
        cancelled = False
        try:
            final_summary = OptimizeSummary()
            stream = _invoke_runner(active_runner, stream_args, cancellation)
            for event, summary in _summarise(stream):
                final_summary = summary
                line = _render_event(event)
                if line is not None:
                    echo(line)
                if cancellation is not None and cancellation.cancelled:
                    cancelled = True
                    break
        except KeyboardInterrupt:
            cancelled = True
            if cancellation is not None:
                cancellation.cancel()
        except OptimizeCommandError as exc:
            if cancellation is not None and cancellation.cancelled:
                cancelled = True
            else:
                echo(click.style(f"  /optimize failed: {exc}", fg="red", bold=True))
                return on_done(
                    result=f"  /optimize failed: {exc}",
                    display="skip",
                    meta_messages=(str(exc),),
                )
        except FileNotFoundError as exc:
            echo(click.style(f"  /optimize failed: {exc}", fg="red", bold=True))
            return on_done(result=None, display="skip")

        if cancelled:
            message = "  /optimize cancelled — ctrl-c; no changes persisted."
            echo(click.style(message, fg="yellow"))
            return on_done(result=message, display="skip")

        summary_line = _format_summary(final_summary)
        meta: list[str] = []
        if final_summary.next_action:
            meta.append(f"Suggested next: {final_summary.next_action}")
        for path in final_summary.artifacts[-3:]:
            meta.append(f"Artifact: {path}")
        return on_done(
            result=summary_line,
            display="user",
            meta_messages=tuple(meta),
        )

    return _handle_optimize


def _invoke_runner(
    runner: StreamRunner,
    args: Sequence[str],
    cancellation: CancellationToken | None,
) -> Iterator[StreamEvent]:
    """Call ``runner`` with or without the cancellation kwarg.

    Legacy runners accept a single positional ``args`` parameter; the
    default runner gained a keyword-only ``cancellation`` parameter in T16.
    Probe at call time so existing tests keep working.
    """
    if cancellation is None:
        return iter(runner(args))
    try:
        return iter(runner(args, cancellation=cancellation))
    except TypeError:
        return iter(runner(args))


def _parse_args(args: Sequence[str]) -> list[str]:
    """Normalise `/optimize` args for the subprocess.

    Currently pass-through — ``optimize`` already accepts ``--cycles``,
    ``--mode``, ``--continuous``, ``--config`` natively, so no aliasing is
    required. Future alias handling (e.g. a shorter ``--run-id``) lives here.
    """
    return list(args)


def build_optimize_command(
    runner: StreamRunner | None = None,
    *,
    description: str = "Run optimization cycles against the active config",
) -> LocalCommand:
    """Build the :class:`LocalCommand` for `/optimize`."""
    return LocalCommand(
        name="optimize",
        description=description,
        handler=make_optimize_handler(runner),
        source="builtin",
    )


__all__ = [
    "OptimizeCommandError",
    "OptimizeSummary",
    "StreamEvent",
    "StreamRunner",
    "build_optimize_command",
    "make_optimize_handler",
]
