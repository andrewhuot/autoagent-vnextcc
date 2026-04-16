"""`/optimize` slash command — runs ``agentlab optimize`` **in-process** (R4.4).

The handler no longer spawns a subprocess. It calls
:func:`cli.commands.optimize.run_optimize_in_process` on a background
thread and bridges its ``on_event`` callback into a :class:`queue.Queue`
so the existing synchronous-generator renderer + spinner machinery keeps
its shape. On a successful run, ``ctx.meta["workbench_session"]``'s
session is updated with ``last_attempt_id``, ``last_eval_run_id`` and
``current_config_path``.

The R4.4 extra wrinkle: ``/optimize`` auto-injects
``session.last_eval_run_id`` into the runner kwargs when the user omits
``--eval-run-id``. If neither source provides one, the handler renders a
transcript error (``"run /eval first"``) rather than letting the run
start without evidence.

The runner remains an injectable seam (:data:`StreamRunner`) so tests
can hand in a callable that yields pre-baked event dicts without
touching the real optimizer stack.
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
from cli.workbench_render import format_workbench_event


_SENTINEL: Any = object()


StreamEvent = dict[str, Any]
"""One JSON event emitted by a stream-json source."""

StreamRunner = Callable[..., Iterator[StreamEvent]]
"""Given ``(args,)`` yield parsed JSON events until the run exits.

Raise :class:`OptimizeCommandError` for non-zero exits or parse failures.
Tests inject a generator in place of the real in-process runner.
"""


class OptimizeCommandError(RuntimeError):
    """Raised by a :data:`StreamRunner` (or session resolver) on failure."""


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
    eval_run_id: str | None = None
    attempt_id: str | None = None
    config_path: str | None = None
    status: str | None = None


# The phase label ``optimize`` uses for per-cycle ``phase_completed`` events.
# See ``runner.optimize`` — every completed cycle emits one of these with a
# "Cycle N <status>" message. Tracking this gives us a cycle counter in the
# summary without re-implementing cycle bookkeeping.
_CYCLE_PHASE = "optimize-cycle"


# ---------------------------------------------------------------------------
# Argv parser + session resolver
# ---------------------------------------------------------------------------


def _args_to_kwargs(args: Sequence[str]) -> dict[str, Any]:
    """Translate the ``/optimize`` argv shape into ``run_optimize_in_process`` kwargs.

    Mirrors the Click wrapper's argument spec so the slash handler can
    drive the exact same business logic. Unknown flags are dropped — the
    slash command surface is deliberately narrower than the full CLI.
    """
    kwargs: dict[str, Any] = {
        "cycles": 1,
        "continuous": False,
        "mode": None,
        "strategy": None,
        "config_path": None,
        "eval_run_id": None,
        "require_eval_evidence": False,
        "full_auto": False,
        "dry_run": False,
        "explain_strategy": False,
        "max_budget_usd": None,
        "strict_live": False,
        "force_mock": False,
    }
    it = iter(args)
    for token in it:
        if token == "--cycles":
            value = next(it, None)
            if value is not None:
                try:
                    kwargs["cycles"] = int(value)
                except ValueError:
                    pass
        elif token == "--continuous":
            kwargs["continuous"] = True
        elif token == "--mode":
            value = next(it, None)
            if value is not None:
                kwargs["mode"] = value
        elif token == "--strategy":
            value = next(it, None)
            if value is not None:
                kwargs["strategy"] = value
        elif token == "--config":
            value = next(it, None)
            if value is not None:
                kwargs["config_path"] = value
        elif token == "--eval-run-id":
            value = next(it, None)
            if value is not None:
                kwargs["eval_run_id"] = value
        elif token == "--require-eval-evidence":
            kwargs["require_eval_evidence"] = True
        elif token == "--full-auto":
            kwargs["full_auto"] = True
        elif token == "--dry-run":
            kwargs["dry_run"] = True
        elif token == "--explain-strategy":
            kwargs["explain_strategy"] = True
        elif token == "--max-budget-usd":
            value = next(it, None)
            if value is not None:
                try:
                    kwargs["max_budget_usd"] = float(value)
                except ValueError:
                    pass
        elif token == "--strict-live":
            kwargs["strict_live"] = True
        elif token == "--no-strict-live":
            kwargs["strict_live"] = False
        elif token == "--mock":
            kwargs["force_mock"] = True
        # Unknown flags are intentionally ignored for the slash surface.
    return kwargs


def _resolve_session_eval_run_id(
    kwargs: dict[str, Any],
    session: Any,
) -> dict[str, Any]:
    """Inject ``session.last_eval_run_id`` into kwargs when user omitted it.

    User-provided ``eval_run_id`` in ``kwargs`` always wins. Raises
    :class:`OptimizeCommandError` when neither the user nor the session
    supplies one — ``/optimize`` without eval evidence is a command-shape
    error, surfaced via transcript rather than an opaque run failure.
    """
    out = dict(kwargs)
    if out.get("eval_run_id"):
        return out
    session_value = getattr(session, "last_eval_run_id", None) if session is not None else None
    if not session_value:
        raise OptimizeCommandError(
            "/optimize needs an eval run — run /eval first or pass --eval-run-id <id>."
        )
    out["eval_run_id"] = session_value
    return out


# ---------------------------------------------------------------------------
# Default in-process runner (R4.4) — thread + queue bridge
# ---------------------------------------------------------------------------


def _default_stream_runner(
    args: Sequence[str],
    *,
    cancellation: CancellationToken | None = None,
    stall_timeout_s: float = DEFAULT_STALL_TIMEOUT_S,
) -> Iterator[StreamEvent]:
    """Run ``optimize`` in-process on a background thread; yield events.

    Parses ``args`` into :func:`cli.commands.optimize.run_optimize_in_process`
    kwargs, spins up a worker thread, and bridges the worker's
    ``on_event`` callback into this generator via a :class:`queue.Queue`.
    Domain exceptions (``MockFallbackError``,
    ``LiveOptimizeRequiredError``, anything else) are captured and re-
    raised as :class:`OptimizeCommandError` at the boundary — matching
    the prior subprocess runner's failure class so existing ``except``
    clauses continue to work.

    The ``cancellation`` and ``stall_timeout_s`` kwargs are preserved for
    ``_invoke_runner`` API compatibility; ``stall_timeout_s`` is a no-op
    in-process. Cancellation is observed by KeyboardInterrupt in the
    worker (the outer handler wires ctx.cancellation to a ctrl-c signal).
    """
    from cli.commands.optimize import run_optimize_in_process

    kwargs = _args_to_kwargs(args)
    q: queue.Queue = queue.Queue()
    error_holder: dict[str, BaseException] = {}

    def _worker() -> None:
        try:
            run_optimize_in_process(**kwargs, on_event=q.put)
        except BaseException as exc:  # capture domain + unexpected errors
            error_holder["value"] = exc
        finally:
            q.put(_SENTINEL)

    t = threading.Thread(target=_worker, daemon=True, name="optimize-in-process")
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
        raise OptimizeCommandError(f"optimize: {exc}") from exc


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
    """Update the spinner's phase label when a meaningful event arrives."""
    name = str(event.get("event", ""))
    data = {k: v for k, v in event.items() if k != "event"}
    if name == "phase_started":
        phase = data.get("phase") or "optimizing"
        spin.update(str(phase))
    elif name == "llm.fallback":
        spin.update(f"fallback ({data.get('reason', 'unknown')})")
    elif name == "llm.retry":
        spin.update("retrying JSON parse")


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
    eval_run_id: str | None = None
    attempt_id: str | None = None
    config_path: str | None = None
    status: str | None = None
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
        elif name == "optimize_complete":
            # R4.4 terminal event: flat-shape metadata the slash handler
            # uses to update the shared WorkbenchSession.
            candidate_eval = event.get("eval_run_id")
            if candidate_eval:
                eval_run_id = str(candidate_eval)
            candidate_attempt = event.get("attempt_id")
            if candidate_attempt:
                attempt_id = str(candidate_attempt)
            candidate_cfg = event.get("config_path")
            if candidate_cfg:
                config_path = str(candidate_cfg)
            candidate_status = event.get("status")
            if candidate_status:
                status = str(candidate_status)
        yield event, OptimizeSummary(
            events=counters["events"],
            cycles_completed=counters["cycles_completed"],
            phases_completed=counters["phases_completed"],
            artifacts=tuple(artifacts),
            warnings=counters["warnings"],
            errors=counters["errors"],
            next_action=next_action,
            eval_run_id=eval_run_id,
            attempt_id=attempt_id,
            config_path=config_path,
            status=status,
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
        parts.append(theme.error(f"{summary.errors} errors", bold=False))
    status = "failed" if summary.errors else "complete"
    line = f"  /optimize {status} — {', '.join(parts)}"
    return theme.error(line) if summary.errors else theme.success(line, bold=True)


# ---------------------------------------------------------------------------
# Handler + registration
# ---------------------------------------------------------------------------


def make_optimize_handler(
    runner: StreamRunner | None = None,
) -> Callable[..., OnDoneResult]:
    """Return a slash handler closed over ``runner`` (defaults to real in-process)."""
    active_runner = runner or _default_stream_runner

    def _handle_optimize(ctx: SlashContext, *args: str) -> OnDoneResult:
        echo = ctx.echo

        # Session-resolve eval_run_id BEFORE any runner invocation so a
        # missing eval evidence signal never spawns a run.
        session = (
            ctx.meta.get("workbench_session") if isinstance(ctx.meta, dict) else None
        )
        parsed_kwargs = _args_to_kwargs(args)
        try:
            resolved_kwargs = _resolve_session_eval_run_id(parsed_kwargs, session)
        except OptimizeCommandError as exc:
            echo(theme.error(f"  /optimize failed: {exc}"))
            return on_done(
                result=f"  /optimize failed: {exc}",
                display="skip",
                meta_messages=(str(exc),),
            )

        # Thread the resolved eval_run_id back into argv so the stream
        # runner (real + fake) sees the canonical invocation. User flags
        # are preserved — _args_to_kwargs already captured the override.
        stream_args = _build_stream_args(args, resolved_kwargs)
        echo(theme.command_name(
            f"  /optimize starting — agentlab optimize {shlex.join(stream_args)}".rstrip(),
        ))

        cancellation = ctx.cancellation
        cancelled = False
        final_summary = OptimizeSummary()
        try:
            stream = _invoke_runner(active_runner, stream_args, cancellation)
            with ctx.spinner("optimizing") as spin:
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
        except OptimizeCommandError as exc:
            if cancellation is not None and cancellation.cancelled:
                cancelled = True
            else:
                echo(theme.error(f"  /optimize failed: {exc}"))
                return on_done(
                    result=f"  /optimize failed: {exc}",
                    display="skip",
                    meta_messages=(str(exc),),
                )
        except FileNotFoundError as exc:
            echo(theme.error(f"  /optimize failed: {exc}"))
            return on_done(result=None, display="skip")
        except Exception as exc:  # error boundary — must come AFTER domain catches
            # R4.4 §1.6 — an in-process handler must never crash the TUI.
            echo(theme.error(f"  /optimize crashed: {type(exc).__name__}: {exc}"))
            return on_done(
                result=f"  /optimize crashed: {exc}",
                display="skip",
                meta_messages=(str(exc),),
            )

        if cancelled:
            message = "  /optimize cancelled — ctrl-c; no changes persisted."
            echo(theme.warning(message))
            return on_done(result=message, display="skip")

        # R4.4 — propagate attempt/eval identifiers to the shared
        # WorkbenchSession so downstream slash commands (e.g. /deploy)
        # can auto-inject them.
        if session is not None:
            updates: dict[str, Any] = {}
            if final_summary.attempt_id:
                updates["last_attempt_id"] = final_summary.attempt_id
            if final_summary.eval_run_id:
                updates["last_eval_run_id"] = final_summary.eval_run_id
            if final_summary.config_path:
                updates["current_config_path"] = final_summary.config_path
            if updates:
                try:
                    session.update(**updates)
                except Exception as exc:  # don't let a session error crash /optimize
                    echo(theme.warning(f"  /optimize: session update failed: {exc}"))

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


def _build_stream_args(
    original_args: Sequence[str], resolved_kwargs: dict[str, Any]
) -> list[str]:
    """Append session-injected ``--eval-run-id`` to argv when absent.

    Preserves the user's original argv order. If the user already passed
    ``--eval-run-id``, argv is returned unchanged. Otherwise the resolver-
    provided value is appended.
    """
    out = list(original_args)
    if any(tok == "--eval-run-id" for tok in out):
        return out
    injected = resolved_kwargs.get("eval_run_id")
    if injected:
        out.extend(["--eval-run-id", str(injected)])
    return out


def _invoke_runner(
    runner: StreamRunner,
    args: Sequence[str],
    cancellation: CancellationToken | None,
) -> Iterator[StreamEvent]:
    """Call ``runner`` with or without the cancellation kwarg."""
    if cancellation is None:
        return iter(runner(args))
    try:
        return iter(runner(args, cancellation=cancellation))
    except TypeError:
        return iter(runner(args))


def _parse_args(args: Sequence[str]) -> list[str]:
    """Normalise `/optimize` args for the runner.

    Currently pass-through — ``optimize`` already accepts ``--cycles``,
    ``--mode``, ``--continuous``, ``--config`` natively. Future alias
    handling lives here.
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
        argument_hint="[--cycles N] [--mode MODE] [--eval-run-id ID]",
        when_to_use="Use when a config needs automated improvement cycles.",
        effort="high",
        allowed_tools=("in-process",),
    )


__all__ = [
    "OptimizeCommandError",
    "OptimizeSummary",
    "StreamEvent",
    "StreamRunner",
    "build_optimize_command",
    "make_optimize_handler",
]
