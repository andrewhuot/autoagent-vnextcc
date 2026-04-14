"""`/eval` slash command — streams ``agentlab eval run`` into the transcript.

T09 adds a streaming slash command that shells out to the existing
``agentlab eval run`` Click subcommand, pipes its ``--output-format stream-json``
output through :func:`cli.workbench_render.format_workbench_event`, and
surfaces a one-line summary when the run finishes.

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

from cli.workbench_app import theme
from cli.workbench_app.cancellation import CancellationToken
from cli.workbench_app.commands import LocalCommand, OnDoneResult, on_done
from cli.workbench_app.slash import SlashContext
from cli.workbench_render import format_workbench_event


StreamEvent = dict[str, Any]
"""One JSON event emitted by a stream-json subprocess."""

StreamRunner = Callable[..., Iterator[StreamEvent]]
"""Given ``(args,)`` yield parsed JSON events until the process exits.

Raise :class:`EvalCommandError` for non-zero exits or parse failures. Tests
inject a generator in place of the real subprocess.
"""


class EvalCommandError(RuntimeError):
    """Raised by a :data:`StreamRunner` when the subprocess fails."""


@dataclass(frozen=True)
class EvalSummary:
    """Counters the `/eval` handler uses to build the `onDone` result line."""

    events: int = 0
    phases_completed: int = 0
    artifacts: tuple[str, ...] = ()
    warnings: int = 0
    errors: int = 0
    next_action: str | None = None
    exit_code: int | None = None


# ---------------------------------------------------------------------------
# Default subprocess runner
# ---------------------------------------------------------------------------


def _default_stream_runner(
    args: Sequence[str],
    *,
    cancellation: CancellationToken | None = None,
) -> Iterator[StreamEvent]:
    """Spawn ``agentlab eval run`` and yield stream-json events line by line.

    ``args`` are the extra CLI args after ``eval run`` (e.g. ``["--config",
    "configs/v003.yaml"]``). ``--output-format stream-json`` is appended
    automatically so callers don't need to remember the flag.

    When ``cancellation`` is supplied, the subprocess is registered so a
    ctrl-c at the app level terminates it, and the reader breaks out as
    soon as ``cancellation.cancelled`` flips. The process is always killed
    in the ``finally`` block so we never leak orphans.
    """
    cmd: list[str] = [
        sys.executable,
        "-m",
        "runner",
        "eval",
        "run",
        "--output-format",
        "stream-json",
        *args,
    ]
    # bufsize=1 gives line-buffered text pipes so we can stream events as they
    # arrive instead of waiting for the child to fill its pipe buffer.
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    # Register immediately so any exception before the try-block still
    # sees the process cleaned up on ctrl-c.
    if cancellation is not None:
        cancellation.register_process(proc)
    assert proc.stdout is not None  # subprocess.PIPE guarantees a stream.
    exit_code = 0
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
                # Non-JSON output (e.g. a warning from an inner tool)
                # should still appear in the transcript rather than be
                # silently dropped. Emit a synthetic ``warning`` event.
                yield {"event": "warning", "message": line}
        exit_code = proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        if cancellation is not None:
            cancellation.unregister_process(proc)
    if exit_code != 0 and not (cancellation is not None and cancellation.cancelled):
        raise EvalCommandError(
            f"eval run exited with status {exit_code}"
        )


# ---------------------------------------------------------------------------
# Event → transcript line rendering
# ---------------------------------------------------------------------------


def _render_event(event: StreamEvent) -> str | None:
    """Map a stream-json event onto a transcript line."""
    event_name = str(event.get("event", ""))
    if not event_name:
        return None
    # ``format_workbench_event`` doesn't know about the ``event`` key itself,
    # so pass the remaining payload (which is what the renderers read).
    payload = {k: v for k, v in event.items() if k != "event"}
    return format_workbench_event(event_name, payload)


def _summarise(events: Iterable[StreamEvent]) -> Iterator[tuple[StreamEvent, EvalSummary]]:
    """Iterate events yielding ``(event, running_summary)`` tuples.

    The running summary lets the caller build a final report without a
    second pass. Each tuple reflects the state *after* absorbing the event.
    """
    counters = {
        "events": 0,
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
        yield event, EvalSummary(
            events=counters["events"],
            phases_completed=counters["phases_completed"],
            artifacts=tuple(artifacts),
            warnings=counters["warnings"],
            errors=counters["errors"],
            next_action=next_action,
        )


def _format_summary(summary: EvalSummary) -> str:
    """Build the ``onDone`` result line from final counters."""
    parts: list[str] = [f"{summary.events} events"]
    if summary.phases_completed:
        parts.append(f"{summary.phases_completed} phases")
    if summary.artifacts:
        parts.append(f"{len(summary.artifacts)} artifacts")
    if summary.warnings:
        parts.append(f"{summary.warnings} warnings")
    if summary.errors:
        parts.append(theme.error(f"{summary.errors} errors", bold=False))
    status = "failed" if summary.errors else "complete"
    line = f"  /eval {status} — {', '.join(parts)}"
    return theme.error(line) if summary.errors else theme.success(line, bold=True)


# ---------------------------------------------------------------------------
# Handler + registration
# ---------------------------------------------------------------------------


def make_eval_handler(
    runner: StreamRunner | None = None,
) -> Callable[..., OnDoneResult]:
    """Return a slash handler closed over ``runner`` (defaults to real subprocess)."""
    active_runner = runner or _default_stream_runner

    def _handle_eval(ctx: SlashContext, *args: str) -> OnDoneResult:
        stream_args = _parse_args(args)
        echo = ctx.echo
        echo(theme.command_name(
            f"  /eval starting — agentlab eval run {shlex.join(stream_args)}".rstrip(),
        ))

        cancellation = ctx.cancellation
        cancelled = False
        try:
            final_summary = EvalSummary()
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
        except EvalCommandError as exc:
            if cancellation is not None and cancellation.cancelled:
                cancelled = True  # subprocess exit is a consequence of cancel.
            else:
                echo(theme.error(f"  /eval failed: {exc}"))
                return on_done(
                    result=f"  /eval failed: {exc}",
                    display="skip",
                    meta_messages=(str(exc),),
                )
        except FileNotFoundError as exc:  # missing binary / wrong cwd
            echo(theme.error(f"  /eval failed: {exc}"))
            return on_done(result=None, display="skip")

        if cancelled:
            message = "  /eval cancelled — ctrl-c; no changes persisted."
            echo(theme.warning(message))
            return on_done(result=message, display="skip")

        summary_line = _format_summary(final_summary)
        meta: list[str] = []
        if final_summary.next_action:
            meta.append(f"Suggested next: {final_summary.next_action}")
        for path in final_summary.artifacts[-3:]:  # last few for brevity
            meta.append(f"Artifact: {path}")
        return on_done(
            result=summary_line,
            display="user",
            meta_messages=tuple(meta),
        )

    return _handle_eval


def _invoke_runner(
    runner: StreamRunner,
    args: Sequence[str],
    cancellation: CancellationToken | None,
) -> Iterator[StreamEvent]:
    """Call ``runner`` with or without the cancellation kwarg.

    Legacy runners (and the test fixtures in this repo) accept a single
    positional ``args`` parameter. The default runner gained a keyword-only
    ``cancellation`` parameter in T16. Probe at call time so both shapes
    work without forcing every test to accept the new seam.
    """
    if cancellation is None:
        return iter(runner(args))
    try:
        return iter(runner(args, cancellation=cancellation))
    except TypeError:
        return iter(runner(args))


def _parse_args(args: Sequence[str]) -> list[str]:
    """Normalise `/eval` args for the subprocess.

    Currently pass-through with ``--run-id`` translated to ``--config`` alias
    handling: if the user types ``/eval --run-id v003`` we forward as-is so
    ``eval run`` can resolve the flag. Any future aliasing lives here.
    """
    out: list[str] = []
    it = iter(args)
    for token in it:
        if token == "--run-id":
            # ``eval run`` accepts ``--config``; ``--run-id`` is syntactic sugar
            # users already request in the plan. Translate so the subprocess
            # call is valid CLI.
            try:
                value = next(it)
            except StopIteration:
                out.append("--run-id")  # Let the subprocess error loudly.
                continue
            out.extend(["--config", value])
            continue
        out.append(token)
    return out


def build_eval_command(
    runner: StreamRunner | None = None,
    *,
    description: str = "Run eval suite against the active config",
) -> LocalCommand:
    """Build the :class:`LocalCommand` for `/eval` (useful for tests + registries)."""
    return LocalCommand(
        name="eval",
        description=description,
        handler=make_eval_handler(runner),
        source="builtin",
        argument_hint="[--config VERSION | --run-id ID]",
        when_to_use="Use after changing prompts, configs, or evaluators.",
        effort="medium",
        allowed_tools=("subprocess",),
    )


__all__ = [
    "EvalCommandError",
    "EvalSummary",
    "StreamEvent",
    "StreamRunner",
    "build_eval_command",
    "make_eval_handler",
]
