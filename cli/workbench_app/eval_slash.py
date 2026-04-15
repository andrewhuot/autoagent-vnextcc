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

import shlex
import sys
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator, Sequence

from cli.workbench_app import theme
from cli.workbench_app._subprocess import (
    DEFAULT_STALL_TIMEOUT_S,
    SubprocessStreamError,
    stream_subprocess,
)
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
    cases_completed: int = 0
    cases_total: int = 0
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
    stall_timeout_s: float = DEFAULT_STALL_TIMEOUT_S,
) -> Iterator[StreamEvent]:
    """Spawn ``agentlab eval run`` and yield stream-json events line by line.

    Delegates to :func:`cli.workbench_app._subprocess.stream_subprocess` for
    the transport layer: line-buffered pipe, stall-timeout detection, and
    cancellation-aware cleanup. This handler keeps ownership of:

    - the ``eval run`` argv (including the ``--output-format stream-json``
      suffix the helper does not know about),
    - the flat ``{"event": "warning", "message": ...}`` synthetic envelope
      used for lines that fail JSON parsing,
    - translating :class:`SubprocessStreamError` into ``EvalCommandError`` so
      the handler's existing ``except EvalCommandError:`` catch still fires.
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
    try:
        yield from stream_subprocess(
            cmd,
            stall_timeout_s=stall_timeout_s,
            cancellation=cancellation,
            on_nonjson=lambda line: {"event": "warning", "message": line},
        )
    except SubprocessStreamError as exc:
        # Keep the error class runners expect while preserving kind/tail
        # so higher layers can tell a stall apart from a non-zero exit.
        raise EvalCommandError(f"eval run: {exc}") from exc


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


def _advance_phase(spin: Any, event: StreamEvent) -> None:
    """Update the spinner phase on ``phase_started`` / LLM fallback events."""
    name = str(event.get("event", ""))
    data = {k: v for k, v in event.items() if k != "event"}
    if name == "phase_started":
        spin.update(str(data.get("phase") or "evaluating"))
    elif name == "task_progress":
        current = data.get("current")
        total = data.get("total")
        if current is not None and total is not None:
            spin.update(f"evaluating cases {current}/{total}")
        else:
            spin.update(str(data.get("title") or "evaluating cases"))
    elif name == "task_completed":
        spin.update(str(data.get("title") or "eval cases complete"))
    elif name == "llm.fallback":
        spin.update(f"fallback ({data.get('reason', 'unknown')})")
    elif name == "llm.retry":
        spin.update("retrying JSON parse")


def _summarise(events: Iterable[StreamEvent]) -> Iterator[tuple[StreamEvent, EvalSummary]]:
    """Iterate events yielding ``(event, running_summary)`` tuples.

    The running summary lets the caller build a final report without a
    second pass. Each tuple reflects the state *after* absorbing the event.
    """
    counters = {
        "events": 0,
        "cases_completed": 0,
        "cases_total": 0,
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
        elif name in {"task_progress", "task_completed"} and event.get("task_id") == "eval-cases":
            current = event.get("current")
            total = event.get("total")
            try:
                if current is not None:
                    counters["cases_completed"] = max(counters["cases_completed"], int(current))
                if total is not None:
                    counters["cases_total"] = max(counters["cases_total"], int(total))
            except (TypeError, ValueError):
                pass
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
            cases_completed=counters["cases_completed"],
            cases_total=counters["cases_total"],
            phases_completed=counters["phases_completed"],
            artifacts=tuple(artifacts),
            warnings=counters["warnings"],
            errors=counters["errors"],
            next_action=next_action,
        )


def _format_summary(summary: EvalSummary) -> str:
    """Build the ``onDone`` result line from final counters."""
    parts: list[str] = []
    if summary.cases_total:
        label = "case" if summary.cases_total == 1 else "cases"
        parts.append(f"{summary.cases_completed} {label}")
    parts.append(f"{summary.events} events")
    if summary.phases_completed:
        parts.append(f"{summary.phases_completed} phases")
    if summary.artifacts:
        artifact_count = len(summary.artifacts)
        artifact_label = "artifact" if artifact_count == 1 else "artifacts"
        parts.append(f"{artifact_count} {artifact_label}")
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
            with ctx.spinner("evaluating") as spin:
                for event, summary in _summarise(stream):
                    final_summary = summary
                    _advance_phase(spin, event)
                    line = _render_event(event)
                    if line is not None:
                        spin.echo(line)
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
