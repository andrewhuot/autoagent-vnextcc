"""`/eval` slash command — runs ``agentlab eval run`` **in-process** (R4.2).

The handler no longer spawns a subprocess. Instead it calls
:func:`cli.commands.eval.run_eval_in_process` on a background thread and
bridges its ``on_event`` callback into a :class:`queue.Queue` so the
existing synchronous-generator renderer + spinner machinery keeps its
shape. On a successful run, ``ctx.meta["workbench_session"]``'s session
is updated with the run's ``run_id`` and ``config_path``.

The runner remains an injectable seam (:data:`StreamRunner`) so tests
can hand in a callable that yields pre-baked event dicts without
touching the real eval stack.
"""

from __future__ import annotations

import queue
import shlex
import threading
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator, Protocol, Sequence

from cli.workbench_app import theme
from cli.workbench_app._subprocess import DEFAULT_STALL_TIMEOUT_S
from cli.workbench_app.cancellation import CancellationToken
from cli.workbench_app.commands import LocalCommand, OnDoneResult, on_done
from cli.workbench_app.slash import SlashContext
from cli.workbench_render import format_workbench_event


_SENTINEL: Any = object()


StreamEvent = dict[str, Any]
"""One JSON event emitted by a stream-json subprocess."""

StreamRunner = Callable[..., Iterator[StreamEvent]]
"""Given ``(args,)`` yield parsed JSON events until the process exits.

Raise :class:`EvalCommandError` for non-zero exits or parse failures. Tests
inject a generator in place of the real subprocess.
"""


class EvalCommandError(RuntimeError):
    """Raised by a :data:`StreamRunner` when the subprocess fails."""


class GridObserver(Protocol):
    """Optional sink for progress events fed to a case-grid widget.

    Implemented by :class:`cli.workbench_app.eval_progress_grid.EvalProgressGrid`
    (R4.7). The handler forwards **every** stream event it sees; the observer
    is responsible for filtering by ``event``/``task_id``. Keeping the
    Protocol here (rather than importing the widget directly) avoids coupling
    the non-TUI slash handler to Textual.
    """

    def on_progress_event(self, event: "StreamEvent") -> None: ...


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
    run_id: str | None = None
    config_path: str | None = None


# ---------------------------------------------------------------------------
# Default subprocess runner
# ---------------------------------------------------------------------------


def _args_to_kwargs(args: Sequence[str]) -> dict[str, Any]:
    """Translate the ``/eval`` argv shape into ``run_eval_in_process`` kwargs.

    Mirrors the Click wrapper's argument spec so the slash handler can
    drive the exact same business logic. Unknown flags are dropped — the
    slash command surface is deliberately narrower than the full CLI.
    """
    kwargs: dict[str, Any] = {
        "config_path": None,
        "suite": None,
        "category": None,
        "dataset": None,
        "dataset_split": "all",
        "output_path": None,
        "instruction_overrides_path": None,
        "real_agent": False,
        "force_mock": False,
        "require_live": False,
        "strict_live": False,
    }
    it = iter(args)
    for token in it:
        if token == "--config":
            try:
                kwargs["config_path"] = next(it)
            except StopIteration:
                break
        elif token == "--suite":
            try:
                kwargs["suite"] = next(it)
            except StopIteration:
                break
        elif token == "--category":
            try:
                kwargs["category"] = next(it)
            except StopIteration:
                break
        elif token == "--dataset":
            try:
                kwargs["dataset"] = next(it)
            except StopIteration:
                break
        elif token == "--split":
            try:
                kwargs["dataset_split"] = next(it)
            except StopIteration:
                break
        elif token == "--output":
            try:
                kwargs["output_path"] = next(it)
            except StopIteration:
                break
        elif token == "--instruction-overrides":
            try:
                kwargs["instruction_overrides_path"] = next(it)
            except StopIteration:
                break
        elif token == "--real-agent":
            kwargs["real_agent"] = True
        elif token == "--mock":
            kwargs["force_mock"] = True
        elif token == "--require-live":
            kwargs["require_live"] = True
        elif token == "--strict-live":
            kwargs["strict_live"] = True
        elif token == "--no-strict-live":
            kwargs["strict_live"] = False
        # Unknown flags are intentionally ignored for the slash surface.
    return kwargs


def _default_stream_runner(
    args: Sequence[str],
    *,
    cancellation: CancellationToken | None = None,
    stall_timeout_s: float = DEFAULT_STALL_TIMEOUT_S,
) -> Iterator[StreamEvent]:
    """Run ``eval run`` in-process on a background thread; yield events.

    Parses ``args`` into :func:`cli.commands.eval.run_eval_in_process`
    kwargs, spins up a worker thread, and bridges the worker's
    ``on_event`` callback into this generator via a :class:`queue.Queue`.
    Domain exceptions (``MockFallbackError``, ``LiveEvalRequiredError``,
    anything else) are captured and re-raised as :class:`EvalCommandError`
    at the boundary — matching the subprocess runner's failure class so
    the handler's existing ``except EvalCommandError:`` catch still fires.
    """
    from cli.commands.eval import run_eval_in_process

    kwargs = _args_to_kwargs(args)
    q: queue.Queue = queue.Queue()
    error_holder: dict[str, BaseException] = {}

    def _worker() -> None:
        try:
            run_eval_in_process(**kwargs, on_event=q.put)
        except BaseException as exc:  # capture domain + unexpected errors
            error_holder["value"] = exc
        finally:
            q.put(_SENTINEL)

    t = threading.Thread(target=_worker, daemon=True, name="eval-in-process")
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
    run_id: str | None = None
    config_path: str | None = None
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
        elif name == "eval_complete":
            # R4.2 — terminal event carrying the run-level identifiers the
            # slash handler uses to update the WorkbenchSession.
            candidate_run_id = event.get("run_id")
            if candidate_run_id:
                run_id = str(candidate_run_id)
            candidate_config_path = event.get("config_path")
            if candidate_config_path:
                config_path = str(candidate_config_path)
        yield event, EvalSummary(
            events=counters["events"],
            cases_completed=counters["cases_completed"],
            cases_total=counters["cases_total"],
            phases_completed=counters["phases_completed"],
            artifacts=tuple(artifacts),
            warnings=counters["warnings"],
            errors=counters["errors"],
            next_action=next_action,
            run_id=run_id,
            config_path=config_path,
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
    *,
    grid_observer: GridObserver | None = None,
) -> Callable[..., OnDoneResult]:
    """Return a slash handler closed over ``runner`` (defaults to real subprocess).

    ``grid_observer`` — optional R4.7 hook: an object with
    ``on_progress_event(event)`` that gets every stream event forwarded to
    it. Used by the :class:`~cli.workbench_app.eval_progress_grid.EvalProgressGrid`
    widget to paint per-case status while the run is in flight. Defaults to
    ``None`` so non-TUI callers are unaffected.
    """
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
                    # R4.7 — forward events to the optional case-grid widget
                    # before rendering the transcript line so the grid is
                    # consistent with whatever the user sees in the log.
                    if grid_observer is not None:
                        try:
                            grid_observer.on_progress_event(event)
                        except Exception:
                            # Grid failures must never crash /eval. The
                            # transcript line is the load-bearing output.
                            pass
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
        except Exception as exc:  # error boundary (to be upgraded in R4.13)
            # R4.2 §1.6 — an in-process handler must never crash the TUI.
            # This catch is placed AFTER the existing domain-error catches
            # so FileNotFoundError / EvalCommandError still take precedence.
            echo(theme.error(f"  /eval crashed: {type(exc).__name__}: {exc}"))
            return on_done(
                result=f"  /eval crashed: {exc}",
                display="skip",
                meta_messages=(str(exc),),
            )

        if cancelled:
            message = "  /eval cancelled — ctrl-c; no changes persisted."
            echo(theme.warning(message))
            return on_done(result=message, display="skip")

        # R4.2 — propagate run identifiers to the shared WorkbenchSession so
        # downstream slash commands (e.g. /optimize) can auto-inject them.
        session = ctx.meta.get("workbench_session") if isinstance(ctx.meta, dict) else None
        if session is not None:
            updates: dict[str, Any] = {}
            if final_summary.run_id:
                updates["last_eval_run_id"] = final_summary.run_id
            if final_summary.config_path:
                updates["current_config_path"] = final_summary.config_path
            if updates:
                try:
                    session.update(**updates)
                except Exception as exc:  # don't let a session error crash /eval
                    echo(theme.warning(f"  /eval: session update failed: {exc}"))

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
        allowed_tools=("in-process",),
    )


__all__ = [
    "EvalCommandError",
    "EvalSummary",
    "StreamEvent",
    "StreamRunner",
    "build_eval_command",
    "make_eval_handler",
]
