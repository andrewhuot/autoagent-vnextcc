"""`/build` slash command — streams ``agentlab workbench build`` into the transcript.

T11 mirrors the `/eval` (T09) and `/optimize` (T10) streaming pattern: shell
out to the existing Click subcommand with ``--output-format stream-json``,
route each event through :func:`cli.workbench_render.format_workbench_event`,
and surface an ``onDone`` summary when the run finishes.

Two design points differ from the other streaming handlers:

- **Positional argument.** ``workbench build`` requires a ``<brief>`` argument
  (the natural-language description of what to build). The handler rejects
  empty input with a transcript error rather than letting the subprocess fail
  with a confusing Click usage message.
- **Nested payload shape.** Workbench stream-json events are shaped
  ``{"event": "name", "data": {...}}`` (see ``builder/workbench_agent.py``),
  unlike the flat progress-event envelope ``eval run`` / ``optimize`` emit.
  :func:`_render_event` unwraps ``data`` before handing it to the renderer.

The subprocess runner is an injectable seam (:data:`StreamRunner`) so tests
don't spawn a real process — they hand in a callable that yields pre-baked
event dicts.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator, Sequence

from cli.workbench_app import theme
from cli.workbench_app.cancellation import CancellationToken
from cli.workbench_app.commands import LocalCommand, OnDoneResult, on_done
from cli.workbench_app.slash import SlashContext
from cli.workbench_render import format_workbench_event


StreamEvent = dict[str, Any]
"""One JSON event emitted by a stream-json subprocess."""

StreamRunner = Callable[..., Iterator[StreamEvent]]
"""Given ``(args,)`` yield parsed JSON events until the process exits.

Raise :class:`BuildCommandError` for non-zero exits. Tests inject a generator
in place of the real subprocess.
"""


class BuildCommandError(RuntimeError):
    """Raised by a :data:`StreamRunner` when the subprocess fails."""


@dataclass(frozen=True)
class BuildSummary:
    """Counters the `/build` handler uses to build the `onDone` result line."""

    events: int = 0
    tasks_completed: int = 0
    iterations: int = 0
    artifacts: tuple[str, ...] = ()
    warnings: int = 0
    errors: int = 0
    run_status: str | None = None  # "completed" | "failed" | "cancelled" | None
    run_version: str | None = None
    failure_reason: str | None = None
    project_id: str | None = None


# ---------------------------------------------------------------------------
# Default subprocess runner
# ---------------------------------------------------------------------------


def _default_stream_runner(
    args: Sequence[str],
    *,
    cancellation: CancellationToken | None = None,
) -> Iterator[StreamEvent]:
    """Spawn ``agentlab workbench build`` and yield stream-json events line by line.

    ``args`` must include the ``brief`` positional argument as the first token
    — the handler guarantees that before calling. ``--output-format stream-json``
    is appended automatically. When ``cancellation`` is provided, ctrl-c kills
    the subprocess and the reader breaks out cleanly without leaking orphans.
    """
    cmd: list[str] = [
        sys.executable,
        "-m",
        "runner",
        "workbench",
        "build",
        *args,
        "--output-format",
        "stream-json",
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
                yield {"event": "warning", "data": {"message": line}}
        exit_code = proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        if cancellation is not None:
            cancellation.unregister_process(proc)
    if exit_code != 0 and not (cancellation is not None and cancellation.cancelled):
        raise BuildCommandError(
            f"workbench build exited with status {exit_code}"
        )


# ---------------------------------------------------------------------------
# Event → transcript line rendering
# ---------------------------------------------------------------------------


def _event_payload(event: StreamEvent) -> dict[str, Any]:
    """Extract the renderer payload from a workbench stream-json event.

    Workbench emits ``{"event": "name", "data": {...}}``; the renderer
    registry keyed by ``event_name`` reads field names directly off the
    payload dict. If ``data`` is missing or non-dict, fall back to the
    top-level envelope (minus ``event``) so malformed events still render
    something sensible.
    """
    data = event.get("data")
    if isinstance(data, dict):
        return data
    return {k: v for k, v in event.items() if k != "event"}


def _render_event(event: StreamEvent) -> str | None:
    """Map a stream-json event onto a transcript line."""
    event_name = str(event.get("event", ""))
    if not event_name:
        return None
    return format_workbench_event(event_name, _event_payload(event))


def _summarise(events: Iterable[StreamEvent]) -> Iterator[tuple[StreamEvent, BuildSummary]]:
    """Iterate events yielding ``(event, running_summary)`` tuples."""
    counters = {
        "events": 0,
        "tasks_completed": 0,
        "iterations": 0,
        "warnings": 0,
        "errors": 0,
    }
    artifacts: list[str] = []
    run_status: str | None = None
    run_version: str | None = None
    failure_reason: str | None = None
    project_id: str | None = None

    for event in events:
        counters["events"] += 1
        name = event.get("event")
        data = _event_payload(event)

        # Capture project_id from any event that carries it — the newest wins.
        pid = data.get("project_id")
        if pid:
            project_id = str(pid)

        if name == "task.completed":
            counters["tasks_completed"] += 1
        elif name == "iteration.started":
            counters["iterations"] += 1
        elif name == "artifact.updated":
            artifact = data.get("artifact")
            # Workbench may emit ``{"artifact": {"name": ..., "path": ...}}``
            # or the payload itself as the artifact object. Prefer ``path``.
            if isinstance(artifact, dict):
                path = artifact.get("path") or artifact.get("name")
            else:
                path = data.get("path") or data.get("name")
            if path:
                artifacts.append(str(path))
        elif name == "run.completed":
            run_status = "completed"
            version = data.get("version")
            if version is not None:
                run_version = str(version)
        elif name == "run.failed":
            run_status = "failed"
            reason = data.get("failure_reason") or data.get("message")
            if reason:
                failure_reason = str(reason)
            counters["errors"] += 1
        elif name == "run.cancelled":
            run_status = "cancelled"
            reason = data.get("cancel_reason") or data.get("message")
            if reason:
                failure_reason = str(reason)
        elif name == "progress.stall":
            counters["warnings"] += 1
        elif name == "error":
            counters["errors"] += 1
        elif name == "warning":
            counters["warnings"] += 1

        yield event, BuildSummary(
            events=counters["events"],
            tasks_completed=counters["tasks_completed"],
            iterations=counters["iterations"],
            artifacts=tuple(artifacts),
            warnings=counters["warnings"],
            errors=counters["errors"],
            run_status=run_status,
            run_version=run_version,
            failure_reason=failure_reason,
            project_id=project_id,
        )


def _format_summary(summary: BuildSummary) -> str:
    """Build the ``onDone`` result line from final counters."""
    parts: list[str] = [f"{summary.events} events"]
    if summary.tasks_completed:
        label = "task" if summary.tasks_completed == 1 else "tasks"
        parts.append(f"{summary.tasks_completed} {label}")
    if summary.iterations:
        label = "iteration" if summary.iterations == 1 else "iterations"
        parts.append(f"{summary.iterations} {label}")
    if summary.artifacts:
        parts.append(f"{len(summary.artifacts)} artifacts")
    if summary.warnings:
        parts.append(f"{summary.warnings} warnings")
    if summary.errors:
        parts.append(theme.error(f"{summary.errors} errors", bold=False))

    failed = summary.run_status in ("failed", "cancelled") or summary.errors > 0
    if summary.run_status == "cancelled":
        status = "cancelled"
    elif failed:
        status = "failed"
    else:
        status = "complete"
    if summary.run_version and not failed:
        status = f"{status} (v{summary.run_version})"

    line = f"  /build {status} — {', '.join(parts)}"
    return theme.error(line) if failed else theme.success(line, bold=True)


# ---------------------------------------------------------------------------
# Handler + registration
# ---------------------------------------------------------------------------


def make_build_handler(
    runner: StreamRunner | None = None,
) -> Callable[..., OnDoneResult]:
    """Return a slash handler closed over ``runner`` (defaults to real subprocess)."""
    active_runner = runner or _default_stream_runner

    def _handle_build(ctx: SlashContext, *args: str) -> OnDoneResult:
        if not args:
            message = (
                "  /build requires a brief, e.g. "
                "/build \"Add a flight status tool\""
            )
            ctx.echo(theme.error(message))
            return on_done(result=message, display="skip")

        stream_args = _parse_args(args)
        echo = ctx.echo
        echo(theme.command_name(
            f"  /build starting — agentlab workbench build {shlex.join(stream_args)}".rstrip(),
        ))

        cancellation = ctx.cancellation
        cancelled = False
        try:
            final_summary = BuildSummary()
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
        except BuildCommandError as exc:
            if cancellation is not None and cancellation.cancelled:
                cancelled = True
            else:
                echo(theme.error(f"  /build failed: {exc}"))
                return on_done(
                    result=f"  /build failed: {exc}",
                    display="skip",
                    meta_messages=(str(exc),),
                )
        except FileNotFoundError as exc:
            echo(theme.error(f"  /build failed: {exc}"))
            return on_done(result=None, display="skip")

        if cancelled:
            message = "  /build cancelled — ctrl-c; candidate not materialized."
            echo(theme.warning(message))
            return on_done(result=message, display="skip")

        summary_line = _format_summary(final_summary)
        meta: list[str] = []
        if final_summary.failure_reason:
            meta.append(f"Reason: {final_summary.failure_reason}")
        if (
            final_summary.run_status == "completed"
            and final_summary.project_id
        ):
            meta.append(
                f"Next: /save to materialize project {final_summary.project_id}"
            )
        elif final_summary.run_status == "completed":
            meta.append("Next: /save to materialize the candidate")
        for path in final_summary.artifacts[-3:]:
            meta.append(f"Artifact: {path}")
        return on_done(
            result=summary_line,
            display="user",
            meta_messages=tuple(meta),
        )

    return _handle_build


def _invoke_runner(
    runner: StreamRunner,
    args: Sequence[str],
    cancellation: CancellationToken | None,
) -> Iterator[StreamEvent]:
    """Call ``runner`` with or without the cancellation kwarg (see T16)."""
    if cancellation is None:
        return iter(runner(args))
    try:
        return iter(runner(args, cancellation=cancellation))
    except TypeError:
        return iter(runner(args))


def _parse_args(args: Sequence[str]) -> list[str]:
    """Normalise `/build` args for the subprocess.

    Pass-through: ``workbench build`` already accepts ``--target``,
    ``--project-id``, ``--new``, ``--auto-iterate``, ``--max-iterations``,
    etc. natively. The brief is forwarded as the first positional arg.
    """
    return list(args)


def build_build_command(
    runner: StreamRunner | None = None,
    *,
    description: str = "Run Workbench build loop from the transcript",
) -> LocalCommand:
    """Build the :class:`LocalCommand` for `/build`."""
    return LocalCommand(
        name="build",
        description=description,
        handler=make_build_handler(runner),
        source="builtin",
    )


__all__ = [
    "BuildCommandError",
    "BuildSummary",
    "StreamEvent",
    "StreamRunner",
    "build_build_command",
    "make_build_handler",
]
