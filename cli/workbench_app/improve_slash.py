"""`/improve` slash command — runs ``agentlab improve <sub>`` **in-process** (R4.5).

The handler no longer spawns a subprocess. It dispatches on the first argv
token to one of the ``run_improve_*_in_process`` pure functions extracted
in R4.5 and bridges the worker's ``on_event`` callback into a
:class:`queue.Queue` so the existing renderer + spinner machinery keeps
its shape.

Session-aware argv injection: for ``accept``, ``measure``, and ``diff`` —
subcommands that require ``<attempt_id>`` positionally — when the user
omits the argument we inject ``session.last_attempt_id``. If neither
source supplies one, the handler emits a transcript error and never
calls the runner. On ``improve run`` / ``improve accept`` success the
terminal ``improve_<sub>_complete`` event's ``attempt_id`` is written
back to :class:`~cli.workbench_app.session_state.WorkbenchSession`.

Scope note: the underlying CLI group has 8 subcommands, but
``improve optimize`` is a thin alias for ``/optimize`` (already in-process
via R4.4) so the slash surface remains at the 7 public subcommands.

The runner remains an injectable seam (:data:`StreamRunner`) so tests
can hand in a callable that yields pre-baked event dicts without
touching the real improve stack.
"""

from __future__ import annotations

import queue
import shlex
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Sequence

from cli.workbench_app import theme
from cli.workbench_app._subprocess import DEFAULT_STALL_TIMEOUT_S
from cli.workbench_app.cancellation import CancellationToken
from cli.workbench_app.commands import LocalCommand, OnDoneResult, on_done
from cli.workbench_app.slash import SlashContext
from cli.workbench_render import format_workbench_event

# Re-exported for the --edit flow so the handler and tests share a single
# symbol. The direct import lets tests monkey-patch
# ``cli.workbench_app.improve_slash.run_improve_accept_in_process`` without
# reaching into ``cli.commands.improve``.
from cli.commands.improve import run_improve_accept_in_process  # noqa: F401


_SENTINEL: Any = object()


StreamEvent = dict[str, Any]
"""One JSON event emitted by an in-process improve run."""

StreamRunner = Callable[..., Iterator[StreamEvent]]
"""Given ``(args,)`` yield parsed event dicts until the run exits.

Raise :class:`ImproveCommandError` for domain failures or parse errors.
Tests inject a generator in place of the real in-process runner.
"""


# Subcommands we recognise. Kept in sync with ``cli/commands/improve.py``.
# The CLI also has ``improve optimize``, but that's a thin alias for
# ``optimize`` (already in-process via R4.4) — we exclude it from the slash
# surface rather than duplicate the optimize dispatch here.
_KNOWN_SUBCOMMANDS: frozenset[str] = frozenset(
    {"run", "accept", "measure", "diff", "lineage", "list", "show"}
)

# Subcommands that require ``<attempt_id>`` positionally and are eligible
# for session-based auto-injection when the user omits it.
_ATTEMPT_ID_SUBCOMMANDS: frozenset[str] = frozenset(
    {"accept", "measure", "diff", "lineage", "show"}
)

# Subcommands whose session-based injection is automatic (per the R4.5 spec).
# ``lineage`` + ``show`` use ``last_attempt_id`` when provided but don't raise
# when absent here; the in-process function will raise on empty prefix lookup.
_AUTO_INJECT_ATTEMPT_ID: frozenset[str] = frozenset(
    {"accept", "measure", "diff"}
)


class ImproveCommandError(RuntimeError):
    """Raised by a :data:`StreamRunner` (or session resolver) on failure.

    Also raised by :func:`_parse_args` when the user invokes ``/improve``
    with a missing or unknown subcommand.
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
    attempt_id: str | None = None
    deployment_id: str | None = None
    status: str | None = None
    subcommand: str | None = None


# ---------------------------------------------------------------------------
# Argv parser + session resolver
# ---------------------------------------------------------------------------


_USAGE = (
    "usage: /improve <run|accept|measure|diff|lineage|list|show> [args]"
)


def _parse_args(args: Sequence[str]) -> list[str]:
    """Validate ``/improve`` args and return the subprocess argv tail.

    Raises :class:`ImproveCommandError` when no subcommand is supplied or an
    unknown one is used.
    """
    if not args:
        raise ImproveCommandError(_USAGE)
    sub = args[0]
    if sub not in _KNOWN_SUBCOMMANDS:
        raise ImproveCommandError(f"unknown subcommand {sub!r}. {_USAGE}")
    return list(args)


def _args_to_kwargs(sub: str, rest: Sequence[str]) -> dict[str, Any]:
    """Translate ``/improve <sub> <rest>`` argv into in-process kwargs.

    Keeps the slash surface narrow: only the flags the in-process functions
    understand are recognised. Unknown tokens are dropped (matching the
    other R4 slash handlers).
    """
    kwargs: dict[str, Any] = {}
    # First positional attempt_id for accept/measure/diff/lineage/show.
    positional_attempt_id: str | None = None

    it = iter(rest)
    for token in it:
        if token == "--strategy":
            value = next(it, None)
            if value is not None:
                kwargs["strategy"] = value
        elif token == "--strict-live":
            kwargs["strict_live"] = True
        elif token == "--no-strict-live":
            kwargs["strict_live"] = False
        elif token == "--memory-db":
            value = next(it, None)
            if value is not None:
                kwargs["memory_db"] = value
        elif token == "--lineage-db":
            value = next(it, None)
            if value is not None:
                kwargs["lineage_db"] = value
        elif token == "--status":
            value = next(it, None)
            if value is not None:
                kwargs["status"] = value
        elif token == "--reason":
            value = next(it, None)
            if value is not None:
                kwargs["reason"] = value
        elif token == "--limit":
            value = next(it, None)
            if value is not None:
                try:
                    kwargs["limit"] = int(value)
                except ValueError:
                    pass
        elif token == "--cycles":
            value = next(it, None)
            if value is not None:
                try:
                    kwargs["cycles"] = int(value)
                except ValueError:
                    pass
        elif token == "--mode":
            value = next(it, None)
            if value is not None:
                kwargs["mode"] = value
        elif token == "--auto":
            kwargs["auto"] = True
        elif token.startswith("--"):
            # Unknown flag — drop silently but consume any value that is not
            # itself a flag (avoids swallowing the next recognised token).
            continue
        else:
            # Positional token. For run, it's the config_path; otherwise it's
            # the attempt_id prefix.
            if sub == "run":
                kwargs.setdefault("config_path", token)
            elif positional_attempt_id is None and sub in _ATTEMPT_ID_SUBCOMMANDS:
                positional_attempt_id = token
    if positional_attempt_id is not None:
        kwargs["attempt_id"] = positional_attempt_id
    return kwargs


def _resolve_session_attempt_id(
    sub: str,
    kwargs: dict[str, Any],
    session: Any,
) -> dict[str, Any]:
    """Inject ``session.last_attempt_id`` when the user omits it.

    Applies to ``accept`` / ``measure`` / ``diff`` only (per the R4.5 spec).
    User-supplied ``attempt_id`` always wins. Raises
    :class:`ImproveCommandError` when neither source supplies one.
    """
    out = dict(kwargs)
    if sub not in _AUTO_INJECT_ATTEMPT_ID:
        return out
    if out.get("attempt_id"):
        return out
    session_value = (
        getattr(session, "last_attempt_id", None) if session is not None else None
    )
    if not session_value:
        raise ImproveCommandError(
            f"/improve {sub}: no attempt in session — run /improve run first "
            f"or pass <attempt_id>."
        )
    out["attempt_id"] = session_value
    return out


# ---------------------------------------------------------------------------
# --edit flow (R4.12 / C6) — inline edit of candidate YAML before accept
# ---------------------------------------------------------------------------


def _prompt_yaml_edit(original: str) -> str | None:
    """Prompt the user to edit ``original`` YAML and return the result.

    Injectable seam — the real implementation opens a Textual ``TextArea``
    inside the Workbench app. Unit tests monkey-patch this function
    directly (see ``tests/test_improve_edit_flow.py``) because driving a
    modal dialog requires a full Pilot-backed Textual app context that's
    brittle to stand up in a pure unit test.

    Contract:
      * Return the edited YAML as a string when the user submits.
      * Return ``None`` when the user cancels (Escape / Ctrl-C).

    The default implementation here is a no-op fallback that treats any
    call as a cancel. The real modal is wired up in the Workbench TUI
    layer; this seam is what the slash handler talks to regardless.
    """
    del original
    return None


def _resolve_workspace_root(ctx: SlashContext) -> Path:
    """Resolve the workspace root for scratch-file placement.

    Prefers ``ctx.meta['workspace_root']`` (set in tests), then
    ``ctx.workspace.root`` (real handler), then the current working
    directory as a last resort.
    """
    root = ctx.meta.get("workspace_root") if isinstance(ctx.meta, dict) else None
    if isinstance(root, (str, Path)):
        return Path(root)
    workspace = ctx.workspace
    candidate = getattr(workspace, "root", None)
    if isinstance(candidate, (str, Path)):
        return Path(candidate)
    return Path.cwd()


def _resolve_lineage_store(ctx: SlashContext) -> Any | None:
    """Pull a lineage store out of ``ctx.meta``, if available.

    Mirrors :func:`cli.workbench_app.attempt_diff_slash._resolve_store` —
    prefers a cached ``lineage_store``; otherwise instantiates one from
    ``lineage_db_path``. Returns ``None`` when no handle can be
    constructed (the handler falls back to an error line in that case).
    """
    cached = ctx.meta.get("lineage_store") if isinstance(ctx.meta, dict) else None
    if cached is not None:
        return cached
    db_path = ctx.meta.get("lineage_db_path") if isinstance(ctx.meta, dict) else None
    if isinstance(db_path, (str, Path)):
        from optimizer.improvement_lineage import ImprovementLineageStore

        store = ImprovementLineageStore(db_path=str(db_path))
        ctx.meta["lineage_store"] = store
        return store
    return None


def _extract_candidate_config_path(view: Any) -> str | None:
    """Mirror of ``attempt_diff_slash._extract_config_path`` for the
    candidate_config_path key only. ``AttemptLineageView`` doesn't expose
    the path as a first-class attribute in all store revisions, so we
    fall back to scanning the event stream (most recent wins). See C4 for
    the convention."""
    attr = getattr(view, "candidate_config_path", None)
    if isinstance(attr, str) and attr:
        return attr
    events = getattr(view, "events", None) or []
    from optimizer.improvement_lineage import EVENT_ATTEMPT

    for event in reversed(events):
        if getattr(event, "event_type", None) != EVENT_ATTEMPT:
            continue
        payload = getattr(event, "payload", None) or {}
        value = payload.get("candidate_config_path")
        if isinstance(value, str) and value:
            return value
    return None


def _handle_accept_edit(
    ctx: SlashContext, attempt_id: str, kwargs: dict[str, Any],
) -> OnDoneResult:
    """Run the ``/improve accept <id> --edit`` flow end-to-end.

    1. Look up the attempt via the lineage store; error if unknown.
    2. Read the candidate YAML from the attempt's recorded path.
    3. Prompt the user to edit via :func:`_prompt_yaml_edit` (seam).
    4. On cancel → emit ``edit cancelled`` and return.
    5. On submit → write the edited YAML to
       ``<workspace>/.agentlab/scratch/accept_<attempt_id>.yaml`` and call
       :func:`run_improve_accept_in_process` with
       ``candidate_override_path=<scratch>``.

    The scratch file is intentionally left on disk after a successful
    accept for post-hoc inspection (forensics). On an unhandled error
    we also leave it — the user can inspect and remove manually.
    """
    echo = ctx.echo
    store = _resolve_lineage_store(ctx)
    if store is None:
        echo(theme.error(
            "  /improve accept --edit: no lineage store available; "
            "pass `lineage_store` via slash context."
        ))
        return on_done(
            result="  /improve accept --edit: no lineage store",
            display="skip",
        )

    try:
        view = store.view_attempt(attempt_id)
    except Exception as exc:  # defensive — sqlite / IO
        echo(theme.error(
            f"  /improve accept --edit: failed to load attempt: {exc}"
        ))
        return on_done(result=None, display="skip")

    events = getattr(view, "events", None) or []
    if not events:
        message = f"  [red]Unknown attempt: {attempt_id}[/]"
        echo(message)
        return on_done(result=message, display="skip")

    candidate_path_str = _extract_candidate_config_path(view)
    if not candidate_path_str:
        echo(theme.error(
            f"  /improve accept --edit: attempt {attempt_id} has no "
            f"recorded candidate_config_path."
        ))
        return on_done(result=None, display="skip")

    candidate_path = Path(candidate_path_str)
    try:
        original_yaml = candidate_path.read_text(encoding="utf-8")
    except OSError as exc:
        echo(theme.error(
            f"  /improve accept --edit: unable to read "
            f"{candidate_path}: {exc}"
        ))
        return on_done(result=None, display="skip")

    edited = _prompt_yaml_edit(original_yaml)
    if edited is None:
        echo("[dim]edit cancelled[/]")
        return on_done(result="edit cancelled", display="skip")

    workspace_root = _resolve_workspace_root(ctx)
    scratch_dir = workspace_root / ".agentlab" / "scratch"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    scratch_path = scratch_dir / f"accept_{attempt_id}.yaml"
    scratch_path.write_text(edited, encoding="utf-8")

    accept_kwargs = {
        k: v for k, v in kwargs.items()
        if k in {"attempt_id", "strategy", "memory_db", "lineage_db"}
    }
    accept_kwargs["attempt_id"] = attempt_id
    accept_kwargs["candidate_override_path"] = scratch_path

    # Stream events through the same echo sink the normal handler uses.
    events_seen: list[dict[str, Any]] = []

    def _on_event(event: dict[str, Any]) -> None:
        events_seen.append(event)
        line = _render_event(event)
        if line is not None:
            echo(line)

    try:
        run_improve_accept_in_process(
            on_event=_on_event,
            **accept_kwargs,
        )
    except Exception as exc:
        echo(theme.error(f"  /improve accept --edit failed: {exc}"))
        return on_done(
            result=f"  /improve accept --edit failed: {exc}",
            display="skip",
            meta_messages=(str(exc),),
        )

    # Propagate attempt_id to the shared session so follow-up /improve
    # subcommands can auto-inject it (matches non-edit accept behavior).
    session = (
        ctx.meta.get("workbench_session") if isinstance(ctx.meta, dict) else None
    )
    if session is not None:
        try:
            session.update(last_attempt_id=attempt_id)
        except Exception as exc:
            echo(theme.warning(f"  /improve: session update failed: {exc}"))

    summary_line = theme.success(
        f"  /improve accept --edit — {attempt_id} (override: {scratch_path})",
        bold=True,
    )
    echo(summary_line)
    return on_done(result=summary_line, display="user")


def _build_stream_args(
    sub: str,
    original_rest: Sequence[str],
    resolved_kwargs: dict[str, Any],
) -> list[str]:
    """Append session-injected ``<attempt_id>`` to argv when absent.

    For subcommands in :data:`_AUTO_INJECT_ATTEMPT_ID`, if the user didn't
    pass a positional attempt_id the resolver's value is inserted right
    after the subcommand token so the runner (real + fake) sees the
    canonical invocation.
    """
    out: list[str] = [sub]
    if sub not in _AUTO_INJECT_ATTEMPT_ID:
        out.extend(original_rest)
        return out
    # Determine whether the user already supplied a positional attempt id.
    user_has_attempt = False
    for token in original_rest:
        if not token.startswith("--"):
            user_has_attempt = True
            break
    if user_has_attempt:
        out.extend(original_rest)
        return out
    injected = resolved_kwargs.get("attempt_id")
    if injected:
        out.append(str(injected))
    out.extend(original_rest)
    return out


# ---------------------------------------------------------------------------
# Default in-process runner (R4.5) — thread + queue bridge
# ---------------------------------------------------------------------------


def _dispatch_in_process(
    sub: str,
    kwargs: dict[str, Any],
    on_event: Callable[[dict[str, Any]], None],
) -> None:
    """Route to the correct ``run_improve_*_in_process`` function."""
    from cli.commands.improve import (
        run_improve_accept_in_process,
        run_improve_diff_in_process,
        run_improve_lineage_in_process,
        run_improve_list_in_process,
        run_improve_measure_in_process,
        run_improve_run_in_process,
        run_improve_show_in_process,
    )

    dispatch: dict[str, Callable[..., Any]] = {
        "run": run_improve_run_in_process,
        "list": run_improve_list_in_process,
        "show": run_improve_show_in_process,
        "accept": run_improve_accept_in_process,
        "measure": run_improve_measure_in_process,
        "diff": run_improve_diff_in_process,
        "lineage": run_improve_lineage_in_process,
    }
    fn = dispatch[sub]
    fn(**kwargs, on_event=on_event)


def _default_stream_runner(
    args: Sequence[str],
    *,
    cancellation: CancellationToken | None = None,
    stall_timeout_s: float = DEFAULT_STALL_TIMEOUT_S,
) -> Iterator[StreamEvent]:
    """Run ``improve <sub>`` in-process on a background thread; yield events.

    Parses ``args`` into the matching ``run_improve_*_in_process`` kwargs
    and bridges its ``on_event`` callback into this generator via a
    :class:`queue.Queue`. Domain exceptions (``ImproveCommandError``,
    anything else) are captured and re-raised as
    :class:`ImproveCommandError` at the boundary.

    ``cancellation`` / ``stall_timeout_s`` are preserved for
    ``_invoke_runner`` API compatibility.
    """
    if not args:
        raise ImproveCommandError(_USAGE)
    sub = args[0]
    if sub not in _KNOWN_SUBCOMMANDS:
        raise ImproveCommandError(f"unknown subcommand {sub!r}. {_USAGE}")

    rest = args[1:]
    # Import lazily to avoid the slash module pulling the CLI stack at
    # import time.
    from cli.commands.improve import ImproveCommandError as _DomainError

    kwargs = _args_to_kwargs(sub, rest)

    # Guarantee positional requirements for subcommands that need them.
    if sub in _ATTEMPT_ID_SUBCOMMANDS and not kwargs.get("attempt_id"):
        raise ImproveCommandError(
            f"improve {sub}: missing <attempt_id>."
        )
    if sub == "run" and not kwargs.get("config_path"):
        # The in-process run path requires a config. Surface the error here.
        raise ImproveCommandError(
            "improve run: missing <config_path>."
        )

    q: queue.Queue = queue.Queue()
    error_holder: dict[str, BaseException] = {}

    def _worker() -> None:
        try:
            _dispatch_in_process(sub, kwargs, q.put)
        except _DomainError as exc:
            error_holder["value"] = ImproveCommandError(f"improve {sub}: {exc}")
        except BaseException as exc:  # capture unexpected errors
            error_holder["value"] = exc
        finally:
            q.put(_SENTINEL)

    t = threading.Thread(target=_worker, daemon=True, name="improve-in-process")
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
        if isinstance(exc, ImproveCommandError):
            raise exc
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


# Event-name prefix the R4.5 terminal envelope carries for every subcommand.
_TERMINAL_EVENT_PREFIX = "improve_"
_TERMINAL_EVENT_SUFFIX = "_complete"


def _summarise(
    events: Iterable[StreamEvent],
) -> Iterator[tuple[StreamEvent, ImproveSummary]]:
    """Iterate events yielding ``(event, running_summary)`` tuples."""
    counters = {
        "events": 0,
        "phases_completed": 0,
        "warnings": 0,
        "errors": 0,
    }
    artifacts: list[str] = []
    next_action: str | None = None
    attempt_id: str | None = None
    deployment_id: str | None = None
    status: str | None = None
    subcommand: str | None = None
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
        if (
            isinstance(name, str)
            and name.startswith(_TERMINAL_EVENT_PREFIX)
            and name.endswith(_TERMINAL_EVENT_SUFFIX)
        ):
            # R4.5 terminal event, e.g. ``improve_accept_complete``.
            subcommand = name[len(_TERMINAL_EVENT_PREFIX):-len(_TERMINAL_EVENT_SUFFIX)]
            candidate_attempt = event.get("attempt_id")
            if candidate_attempt:
                attempt_id = str(candidate_attempt)
            candidate_deployment = event.get("deployment_id")
            if candidate_deployment:
                deployment_id = str(candidate_deployment)
            candidate_status = event.get("status")
            if candidate_status:
                status = str(candidate_status)
        yield event, ImproveSummary(
            events=counters["events"],
            phases_completed=counters["phases_completed"],
            artifacts=tuple(artifacts),
            warnings=counters["warnings"],
            errors=counters["errors"],
            next_action=next_action,
            attempt_id=attempt_id,
            deployment_id=deployment_id,
            status=status,
            subcommand=subcommand,
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
# Handler + registration
# ---------------------------------------------------------------------------


def make_improve_handler(
    runner: StreamRunner | None = None,
) -> Callable[..., OnDoneResult]:
    """Return a slash handler closed over ``runner``.

    Defaults to the real in-process runner; tests inject a generator fixture.
    """
    active_runner = runner or _default_stream_runner

    def _handle_improve(ctx: SlashContext, *args: str) -> OnDoneResult:
        echo = ctx.echo
        try:
            stream_args = _parse_args(args)
        except ImproveCommandError as exc:
            message = f"  /improve — {exc}"
            echo(theme.error(message))
            return on_done(result=message, display="skip")

        sub = stream_args[0]
        rest = stream_args[1:]

        # Session-aware attempt_id injection (accept/measure/diff).
        session = (
            ctx.meta.get("workbench_session") if isinstance(ctx.meta, dict) else None
        )
        parsed_kwargs = _args_to_kwargs(sub, rest)
        try:
            resolved_kwargs = _resolve_session_attempt_id(sub, parsed_kwargs, session)
        except ImproveCommandError as exc:
            echo(theme.error(f"  /improve failed: {exc}"))
            return on_done(
                result=f"  /improve failed: {exc}",
                display="skip",
                meta_messages=(str(exc),),
            )

        # R4.12 / C6 — /improve accept <id> --edit routes through a
        # dedicated handler that prompts for an edited YAML and passes
        # the scratch file to run_improve_accept_in_process as
        # candidate_override_path. The non-edit path is unchanged.
        if sub == "accept" and "--edit" in rest:
            attempt_id = resolved_kwargs.get("attempt_id")
            if not attempt_id:
                echo(theme.error(
                    "  /improve accept --edit: missing <attempt_id>."
                ))
                return on_done(
                    result="  /improve accept --edit: missing <attempt_id>.",
                    display="skip",
                )
            return _handle_accept_edit(ctx, str(attempt_id), resolved_kwargs)

        # Thread the resolved attempt_id back into argv so the runner sees
        # the canonical invocation.
        final_stream_args = _build_stream_args(sub, rest, resolved_kwargs)

        echo(theme.command_name(
            f"  /improve starting — agentlab improve {shlex.join(final_stream_args)}".rstrip(),
        ))

        cancellation = ctx.cancellation
        cancelled = False
        final_summary = ImproveSummary()
        try:
            stream = _invoke_runner(active_runner, final_stream_args, cancellation)
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
        except Exception as exc:  # error boundary — must come AFTER domain catches
            # R4.5 §1.6 — an in-process handler must never crash the TUI.
            echo(theme.error(f"  /improve crashed: {type(exc).__name__}: {exc}"))
            return on_done(
                result=f"  /improve crashed: {exc}",
                display="skip",
                meta_messages=(str(exc),),
            )

        if cancelled:
            message = "  /improve cancelled — ctrl-c; no changes persisted."
            echo(theme.warning(message))
            return on_done(result=message, display="skip")

        # R4.5 — propagate attempt identifiers to the shared
        # WorkbenchSession. Only ``run`` and ``accept`` update session state;
        # the read-only subcommands (list/show/measure/diff/lineage) don't.
        if session is not None and final_summary.subcommand in {"run", "accept"}:
            if final_summary.attempt_id:
                try:
                    session.update(last_attempt_id=final_summary.attempt_id)
                except Exception as exc:
                    echo(theme.warning(f"  /improve: session update failed: {exc}"))

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
    working alongside the real in-process runner.
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
        allowed_tools=("in-process",),
    )


__all__ = [
    "ImproveCommandError",
    "ImproveSummary",
    "StreamEvent",
    "StreamRunner",
    "build_improve_command",
    "make_improve_handler",
]
