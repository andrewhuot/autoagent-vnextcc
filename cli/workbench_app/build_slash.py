"""`/build` slash command — runs ``agentlab workbench build`` **in-process** (R4.3).

R4.3: the handler no longer spawns a subprocess. It calls
:func:`cli.workbench.run_build_in_process` on a background thread and
bridges its ``on_event`` callback into a :class:`queue.Queue` so the
existing synchronous-generator renderer + spinner machinery keeps its
shape. On a successful build, ``ctx.meta["workbench_session"]``'s session
is updated with ``current_config_path`` so downstream slash commands
(``/eval``, ``/optimize``) can auto-resolve the candidate artifact.

Two design points still apply:

- **Positional argument.** ``workbench build`` requires a ``<brief>``
  argument. The handler rejects empty input with a transcript error
  rather than letting the underlying parser raise a confusing message.
- **Nested payload shape.** Workbench stream events are shaped
  ``{"event": "name", "data": {...}}``, unlike the flat progress-event
  envelope ``eval run`` emits. :func:`_render_event` unwraps ``data``
  before handing it to the renderer.

The runner remains an injectable seam (:data:`StreamRunner`) so tests can
hand in a callable that yields pre-baked event dicts without touching
the real workbench stack.
"""

from __future__ import annotations

import queue
import shlex
import threading
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator, Sequence

from cli.workbench_app import theme
from cli.workbench_app._subprocess import DEFAULT_STALL_TIMEOUT_S
from cli.workbench_app.cancellation import CancellationToken
from cli.workbench_app.commands import LocalCommand, OnDoneResult, on_done
from cli.workbench_app.slash import SlashContext
from cli.workbench_render import fallback_badge, format_workbench_event


_SENTINEL: Any = object()


StreamEvent = dict[str, Any]
"""One JSON event emitted by a stream-json source."""

StreamRunner = Callable[..., Iterator[StreamEvent]]
"""Given ``(args,)`` yield parsed JSON events until the run exits.

Raise :class:`BuildCommandError` on failures. Tests inject a generator
in place of the real in-process runner.
"""


class BuildCommandError(RuntimeError):
    """Raised by a :data:`StreamRunner` when the build run fails."""


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
    config_path: str | None = None
    fallback_count: int = 0
    fallback_reasons: tuple[str, ...] = ()
    retry_count: int = 0


# ---------------------------------------------------------------------------
# Argv parser + in-process runner (R4.3)
# ---------------------------------------------------------------------------


def _args_to_kwargs(args: Sequence[str]) -> dict[str, Any]:
    """Translate the ``/build`` argv shape into ``run_build_in_process`` kwargs.

    Mirrors the Click wrapper's argument spec so the slash handler can
    drive the exact same business logic. Unknown flags are dropped — the
    slash command surface is deliberately narrower than the full CLI.

    Raises :class:`ValueError` when no brief is provided (the caller
    surfaces a transcript error).
    """
    tokens = list(args)
    if not tokens:
        raise ValueError("/build requires a brief")

    kwargs: dict[str, Any] = {
        "brief": "",
        "project_id": None,
        "start_new": False,
        "target": "portable",
        "environment": "draft",
        "mock": False,
        "require_live": False,
        "auto_iterate": True,
        "max_iterations": 3,
        "max_seconds": None,
        "max_tokens": None,
        "max_cost_usd": None,
    }

    # The brief is the first positional that isn't a flag. Flags consume their
    # value where applicable.
    brief_parts: list[str] = []
    it = iter(tokens)
    for token in it:
        if not token.startswith("--"):
            brief_parts.append(token)
            continue
        if token == "--project-id":
            kwargs["project_id"] = next(it, None)
        elif token == "--new":
            kwargs["start_new"] = True
        elif token == "--target":
            value = next(it, None)
            if value is not None:
                kwargs["target"] = value
        elif token == "--environment":
            value = next(it, None)
            if value is not None:
                kwargs["environment"] = value
        elif token == "--mock":
            kwargs["mock"] = True
        elif token == "--require-live":
            kwargs["require_live"] = True
        elif token == "--auto-iterate":
            kwargs["auto_iterate"] = True
        elif token == "--no-auto-iterate":
            kwargs["auto_iterate"] = False
        elif token == "--max-iterations":
            value = next(it, None)
            if value is not None:
                try:
                    kwargs["max_iterations"] = int(value)
                except ValueError:
                    pass
        elif token == "--max-seconds":
            value = next(it, None)
            if value is not None:
                try:
                    kwargs["max_seconds"] = int(value)
                except ValueError:
                    pass
        elif token == "--max-tokens":
            value = next(it, None)
            if value is not None:
                try:
                    kwargs["max_tokens"] = int(value)
                except ValueError:
                    pass
        elif token == "--max-cost-usd":
            value = next(it, None)
            if value is not None:
                try:
                    kwargs["max_cost_usd"] = float(value)
                except ValueError:
                    pass
        # Unknown flags are intentionally ignored for the slash surface.

    if not brief_parts:
        raise ValueError("/build requires a brief")
    kwargs["brief"] = " ".join(brief_parts).strip()
    if not kwargs["brief"]:
        raise ValueError("/build requires a brief")
    return kwargs


def _default_stream_runner(
    args: Sequence[str],
    *,
    cancellation: CancellationToken | None = None,
    stall_timeout_s: float = DEFAULT_STALL_TIMEOUT_S,
) -> Iterator[StreamEvent]:
    """Run the workbench build in-process on a worker thread; yield events.

    Parses ``args`` into :func:`cli.workbench.run_build_in_process`
    kwargs, spins up a worker thread, and bridges the worker's
    ``on_event`` callback into this generator via a :class:`queue.Queue`.
    Domain exceptions (``LiveBuildRequiredError``, ``BuildCommandError``,
    anything else) are captured and re-raised as :class:`BuildCommandError`
    at the boundary — matching the prior subprocess runner's failure class
    so existing ``except BuildCommandError:`` catches still fire.
    """
    from cli.workbench import run_build_in_process

    kwargs = _args_to_kwargs(args)
    q: queue.Queue = queue.Queue()
    error_holder: dict[str, BaseException] = {}

    def _worker() -> None:
        try:
            run_build_in_process(**kwargs, on_event=q.put)
        except BaseException as exc:  # capture domain + unexpected errors
            error_holder["value"] = exc
        finally:
            q.put(_SENTINEL)

    t = threading.Thread(target=_worker, daemon=True, name="build-in-process")
    t.start()
    try:
        while True:
            item = q.get()
            if item is _SENTINEL:
                break
            yield item
    finally:
        t.join(timeout=5.0)

    if "value" in error_holder:
        exc = error_holder["value"]
        # Cancellation is NOT an error — the worker will have raised
        # KeyboardInterrupt, which is handled in the outer layer. Every
        # other failure class is translated to BuildCommandError so the
        # handler's existing except clause renders a transcript error.
        raise BuildCommandError(f"workbench build: {exc}") from exc


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
        "fallback_count": 0,
        "retry_count": 0,
    }
    artifacts: list[str] = []
    run_status: str | None = None
    run_version: str | None = None
    failure_reason: str | None = None
    project_id: str | None = None
    config_path: str | None = None
    fallback_reasons: list[str] = []

    for event in events:
        counters["events"] += 1
        name = event.get("event")
        data = _event_payload(event)

        # Capture project_id from any event that carries it — the newest wins.
        # The R4.3 ``build_complete`` terminal event uses a flat shape, so
        # also check the event envelope itself.
        pid = data.get("project_id") or event.get("project_id")
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
        elif name == "llm.fallback":
            counters["fallback_count"] += 1
            reason = data.get("reason")
            if reason:
                fallback_reasons.append(str(reason))
        elif name == "llm.retry":
            counters["retry_count"] += 1
        elif name == "build_complete":
            # R4.3 terminal event: flat-shape metadata the slash handler
            # uses to update the shared WorkbenchSession.
            cfg = event.get("config_path")
            if cfg:
                config_path = str(cfg)

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
            config_path=config_path,
            fallback_count=counters["fallback_count"],
            fallback_reasons=tuple(fallback_reasons),
            retry_count=counters["retry_count"],
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
    if summary.fallback_count:
        label = "fallback" if summary.fallback_count == 1 else "fallbacks"
        parts.append(f"{summary.fallback_count} {label}")

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
    if summary.fallback_count:
        reason = summary.fallback_reasons[0] if summary.fallback_reasons else None
        line = f"{line} {fallback_badge(reason)}"
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
            with ctx.spinner("building candidate") as spin:
                for event, summary in _summarise(stream):
                    final_summary = summary
                    _update_spinner_phase(spin, event)
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
        except Exception as exc:  # error boundary — must come AFTER domain catches
            # R4.3 §1.6 — an in-process handler must never crash the TUI.
            echo(theme.error(f"  /build crashed: {type(exc).__name__}: {exc}"))
            return on_done(
                result=f"  /build crashed: {exc}",
                display="skip",
                meta_messages=(str(exc),),
            )

        if cancelled:
            message = "  /build cancelled — ctrl-c; candidate not materialized."
            echo(theme.warning(message))
            return on_done(result=message, display="skip")

        # R4.3 — propagate build identifiers to the shared WorkbenchSession so
        # downstream slash commands (e.g. /eval, /optimize) can auto-inject
        # the active config path.
        session = ctx.meta.get("workbench_session") if isinstance(ctx.meta, dict) else None
        if session is not None:
            updates: dict[str, Any] = {}
            if final_summary.config_path:
                updates["current_config_path"] = final_summary.config_path
            if updates:
                try:
                    session.update(**updates)
                except Exception as exc:  # don't let a session error crash /build
                    echo(theme.warning(f"  /build: session update failed: {exc}"))

        summary_line = _format_summary(final_summary)
        meta: list[str] = []
        if final_summary.failure_reason:
            meta.append(f"Reason: {final_summary.failure_reason}")
        if final_summary.fallback_count:
            reasons = ", ".join(sorted(set(final_summary.fallback_reasons))) or "unknown"
            meta.append(
                f"LLM fallback x{final_summary.fallback_count} — reasons: {reasons}. "
                "Artifacts are placeholders; retry with a valid provider key."
            )
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


def _update_spinner_phase(spin: Any, event: StreamEvent) -> None:
    """Advance the spinner phase when a meaningful lifecycle event arrives.

    Chosen event set keeps the on-screen label readable (one swap every few
    seconds) without showing every ``task.progress`` note. Unknown events
    leave the current phase untouched so the spinner keeps spinning on the
    last known label.
    """
    name = str(event.get("event", ""))
    data = _event_payload(event)
    if name == "iteration.started":
        iteration = data.get("iteration")
        suffix = f" {iteration}" if iteration not in (None, "", 0) else ""
        spin.update(f"iterating{suffix}")
    elif name == "task.started":
        title = data.get("title") or data.get("task_id") or "task"
        spin.update(f"running {title}")
    elif name == "llm.fallback":
        reason = data.get("reason") or "unknown"
        spin.update(f"fallback ({reason})")
    elif name == "llm.retry":
        spin.update("retrying JSON parse")


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
        argument_hint="<brief> [--target NAME] [--auto-iterate]",
        when_to_use="Use when you want the Workbench to generate or refine a candidate.",
        effort="high",
        allowed_tools=("in-process",),
    )


__all__ = [
    "BuildCommandError",
    "BuildSummary",
    "StreamEvent",
    "StreamRunner",
    "build_build_command",
    "make_build_handler",
]
