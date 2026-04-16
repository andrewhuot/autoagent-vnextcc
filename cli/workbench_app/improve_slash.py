"""`/improve` slash command — streams ``agentlab improve <sub>`` into the transcript.

Slice D.1 of AgentLab R2 wires the unified improvement loop surface into the
workbench. `/improve` is a thin passthrough group: the first positional
argument selects the ``improve`` subcommand (``run``, ``accept``,
``measure``, ``diff``, ``lineage``, ``list``, ``show``) and the rest of the
argv is forwarded verbatim. The subprocess emits ``stream-json`` events that
are piped through :func:`cli.workbench_render.format_workbench_event` into
the transcript, exactly like ``/eval`` and ``/optimize``.

The subprocess runner is an injectable seam (:data:`StreamRunner`) so tests
can hand in a generator of pre-baked events rather than spawning a real
process. The default runner uses :mod:`subprocess` with ``sys.executable -m
runner`` so the child picks up the same interpreter + venv as the workbench.

Slice R4 will grow richer widgets on top of this passthrough (an interactive
attempt picker, inline diff rendering, etc.). For Slice D.1 the goal is
parity: every CLI subcommand reachable from the TUI, nothing more.
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

Raise :class:`ImproveCommandError` for non-zero exits or parse failures.
Tests inject a generator in place of the real subprocess.
"""


# Subcommands we recognise. Kept in sync with ``cli/commands/improve.py``.
# Mismatched entries surface the parse error at dispatch time (cheap, loud)
# rather than shelling out to ``agentlab improve <typo>`` which would spawn a
# process and surface a less-obvious Click error several seconds later.
_KNOWN_SUBCOMMANDS: frozenset[str] = frozenset(
    {"run", "accept", "measure", "diff", "lineage", "list", "show"}
)


class ImproveCommandError(RuntimeError):
    """Raised by a :data:`StreamRunner` when the subprocess fails.

    Also raised by :func:`_parse_args` when the user invokes ``/improve``
    with a missing or unknown subcommand — the handler catches and renders
    a usage line rather than letting the error bubble to dispatch.
    """


@dataclass(frozen=True)
class ImproveSummary:
    """Counters the `/improve` handler uses to build the `onDone` result line."""

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
    stall_timeout_s: float = DEFAULT_STALL_TIMEOUT_S,
) -> Iterator[StreamEvent]:
    """Spawn ``agentlab improve <sub>`` and yield stream-json events.

    Delegates transport to :func:`stream_subprocess`; this function only owns
    the argv layout (``runner improve <sub> --output-format stream-json
    <rest>``) and error translation to :class:`ImproveCommandError`.
    """
    if not args:
        raise ImproveCommandError("improve: missing subcommand")
    sub, *rest = args
    cmd: list[str] = [
        sys.executable,
        "-m",
        "runner",
        "improve",
        sub,
        "--output-format",
        "stream-json",
        *rest,
    ]
    try:
        yield from stream_subprocess(
            cmd,
            stall_timeout_s=stall_timeout_s,
            cancellation=cancellation,
            on_nonjson=lambda line: {"event": "warning", "message": line},
        )
    except SubprocessStreamError as exc:
        raise ImproveCommandError(f"improve {sub}: {exc}") from exc


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


def _advance_phase(spin: Any, event: StreamEvent) -> None:
    """Update the spinner phase label on notable events."""
    name = str(event.get("event", ""))
    data = {k: v for k, v in event.items() if k != "event"}
    if name == "phase_started":
        spin.update(str(data.get("phase") or "improving"))
    elif name == "llm.fallback":
        spin.update(f"fallback ({data.get('reason', 'unknown')})")
    elif name == "llm.retry":
        spin.update("retrying JSON parse")


def _summarise(events: Iterable[StreamEvent]) -> Iterator[tuple[StreamEvent, ImproveSummary]]:
    """Iterate events yielding ``(event, running_summary)`` tuples."""
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
        yield event, ImproveSummary(
            events=counters["events"],
            phases_completed=counters["phases_completed"],
            artifacts=tuple(artifacts),
            warnings=counters["warnings"],
            errors=counters["errors"],
            next_action=next_action,
        )


def _format_summary(summary: ImproveSummary) -> str:
    """Build the ``onDone`` result line from final counters."""
    parts: list[str] = [f"{summary.events} events"]
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
    line = f"  /improve {status} — {', '.join(parts)}"
    return theme.error(line) if summary.errors else theme.success(line, bold=True)


# ---------------------------------------------------------------------------
# Argument normalisation
# ---------------------------------------------------------------------------


_USAGE = (
    "usage: /improve <run|accept|measure|diff|lineage|list|show> [args]"
)


def _parse_args(args: Sequence[str]) -> list[str]:
    """Validate ``/improve`` args and return the subprocess argv tail.

    Raises :class:`ImproveCommandError` when no subcommand is supplied or an
    unknown one is used. The handler catches and renders a usage line rather
    than shelling out to ``runner improve <typo>``.
    """
    if not args:
        raise ImproveCommandError(_USAGE)
    sub = args[0]
    if sub not in _KNOWN_SUBCOMMANDS:
        raise ImproveCommandError(f"unknown subcommand {sub!r}. {_USAGE}")
    return list(args)


# ---------------------------------------------------------------------------
# Handler + registration
# ---------------------------------------------------------------------------


def make_improve_handler(
    runner: StreamRunner | None = None,
) -> Callable[..., OnDoneResult]:
    """Return a slash handler closed over ``runner``.

    Defaults to the real subprocess runner; tests inject a generator fixture.
    """
    active_runner = runner or _default_stream_runner

    def _handle_improve(ctx: SlashContext, *args: str) -> OnDoneResult:
        echo = ctx.echo
        try:
            stream_args = _parse_args(args)
        except ImproveCommandError as exc:
            # Surface the usage hint on its own line — ``on_done`` with
            # ``display="skip"`` keeps the enclosing loop from quoting the
            # message back to the model.
            message = f"  /improve — {exc}"
            echo(theme.error(message))
            return on_done(result=message, display="skip")

        echo(theme.command_name(
            f"  /improve starting — agentlab improve {shlex.join(stream_args)}".rstrip(),
        ))

        cancellation = ctx.cancellation
        cancelled = False
        final_summary = ImproveSummary()
        try:
            stream = _invoke_runner(active_runner, stream_args, cancellation)
            with ctx.spinner("improving") as spin:
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
        except ImproveCommandError as exc:
            if cancellation is not None and cancellation.cancelled:
                cancelled = True
            else:
                echo(theme.error(f"  /improve failed: {exc}"))
                return on_done(
                    result=f"  /improve failed: {exc}",
                    display="skip",
                    meta_messages=(str(exc),),
                )
        except FileNotFoundError as exc:  # missing binary / wrong cwd
            echo(theme.error(f"  /improve failed: {exc}"))
            return on_done(result=None, display="skip")

        if cancelled:
            message = "  /improve cancelled — ctrl-c; no changes persisted."
            echo(theme.warning(message))
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

    return _handle_improve


def _invoke_runner(
    runner: StreamRunner,
    args: Sequence[str],
    cancellation: CancellationToken | None,
) -> Iterator[StreamEvent]:
    """Call ``runner`` with or without the cancellation kwarg.

    Matches the probe-first pattern used by ``eval_slash._invoke_runner`` so
    legacy positional-only runners (including the repo's test fixtures) keep
    working alongside the real subprocess runner.
    """
    if cancellation is None:
        return iter(runner(args))
    try:
        return iter(runner(args, cancellation=cancellation))
    except TypeError:
        return iter(runner(args))


def build_improve_command(
    runner: StreamRunner | None = None,
    *,
    description: str = "Run the unified improve loop and manage attempts",
) -> LocalCommand:
    """Build the :class:`LocalCommand` for `/improve`."""
    return LocalCommand(
        name="improve",
        description=description,
        handler=make_improve_handler(runner),
        source="builtin",
        argument_hint="<subcommand> [args]",
        when_to_use=(
            "Use to drive the unified improvement loop — run, accept, "
            "measure, diff, lineage, list, show — without leaving the "
            "workbench."
        ),
        effort="medium",
        allowed_tools=("subprocess",),
    )


__all__ = [
    "ImproveCommandError",
    "ImproveSummary",
    "StreamEvent",
    "StreamRunner",
    "build_improve_command",
    "make_improve_handler",
]
