"""`/deploy` slash command — runs ``agentlab deploy`` **in-process** (R4.6).

The handler no longer spawns a subprocess. It calls
:func:`cli.commands.deploy.run_deploy_in_process` on a background
thread and bridges its ``on_event`` callback into a :class:`queue.Queue`
so the existing synchronous-generator renderer + spinner machinery
keeps its shape.

Deployment mutates shared state, so the handler prompts the user for an
explicit ``y/N`` confirmation before running. The confirmation is
bypassed when ``--dry-run`` is on the args list or when the user
already passed ``-y`` / ``--yes``. When the prompt returns ``y``, the
handler appends ``-y`` to the argv so the subprocess compatibility
layer does not re-prompt through :class:`PermissionManager`.

Session-aware argv injection (R4.6): when the user omits
``--attempt-id``, ``session.last_attempt_id`` is injected. If neither
source supplies one, the handler emits a transcript error and never
calls the runner. R1 invariant: a verdict-blocked runner result
surfaces as a transcript error with ``status="blocked"`` metadata from
the terminal ``deploy_complete`` event.
"""

from __future__ import annotations

import queue
import shlex
import sys
import threading
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator, Sequence

import click

from cli.workbench_app import theme
from cli.workbench_app._subprocess import DEFAULT_STALL_TIMEOUT_S
from cli.workbench_app.cancellation import CancellationToken
from cli.workbench_app.commands import LocalCommand, OnDoneResult, on_done
from cli.workbench_app.slash import SlashContext
from cli.workbench_render import format_workbench_event


_SENTINEL: Any = object()


StreamEvent = dict[str, Any]
"""One JSON event emitted by an in-process deploy run."""

StreamRunner = Callable[..., Iterator[StreamEvent]]
"""Given ``(args,)`` yield parsed JSON events until the run exits.

Raise :class:`DeployCommandError` for domain failures. Tests inject a
generator in place of the real in-process runner.
"""

Prompter = Callable[[str], bool]
"""Renders the confirmation message and returns ``True`` iff the user typed ``y``.

The default implementation uses :func:`click.confirm`; tests inject a lambda
that returns a canned decision.
"""


class DeployCommandError(RuntimeError):
    """Raised by a :data:`StreamRunner` (or session resolver) on failure."""


@dataclass(frozen=True)
class DeploySummary:
    """Counters the `/deploy` handler uses to build the `onDone` result line."""

    events: int = 0
    phases_completed: int = 0
    artifacts: tuple[str, ...] = ()
    warnings: int = 0
    errors: int = 0
    next_action: str | None = None
    strategy: str | None = None
    # R4.6 — populated from the terminal ``deploy_complete`` event.
    attempt_id: str | None = None
    deployment_id: str | None = None
    verdict: str | None = None
    status: str | None = None


# ---------------------------------------------------------------------------
# Default seams
# ---------------------------------------------------------------------------


def _default_prompter(message: str) -> bool:
    """Block on ``click.confirm`` with a default of ``False``."""
    return click.confirm(message, default=False, show_default=True)


# ---------------------------------------------------------------------------
# Argument inspection
# ---------------------------------------------------------------------------


_CONFIRM_SKIP_FLAGS: frozenset[str] = frozenset({"-y", "--yes"})
_DRY_RUN_FLAG = "--dry-run"


def _infer_strategy(args: Sequence[str]) -> str:
    """Guess the strategy the user will run with, for the confirmation prompt.

    Mirrors ``runner.deploy``'s positional-vs-flag resolution: the positional
    ``workflow`` argument overrides ``--strategy`` when set to ``canary``,
    ``immediate``, or ``release`` (which maps to ``immediate``).
    """
    strategy = "canary"
    skip = False
    for index, token in enumerate(args):
        if skip:
            skip = False
            continue
        if token == "--strategy" and index + 1 < len(args):
            strategy = args[index + 1]
            skip = True
        elif token.startswith("--strategy="):
            strategy = token.split("=", 1)[1]
        elif token in ("canary", "immediate"):
            strategy = token
        elif token == "release":
            strategy = "immediate"
    return strategy


def _is_preconfirmed(args: Sequence[str]) -> bool:
    """Return ``True`` when the user already opted into non-interactive execution."""
    return any(token in _CONFIRM_SKIP_FLAGS for token in args)


def _is_dry_run(args: Sequence[str]) -> bool:
    return _DRY_RUN_FLAG in args


def _parse_args(args: Sequence[str]) -> list[str]:
    """Pass through ``deploy`` args — all flags are already native."""
    return list(args)


# ---------------------------------------------------------------------------
# Argv parser + session resolver
# ---------------------------------------------------------------------------


def _args_to_kwargs(args: Sequence[str]) -> dict[str, Any]:
    """Translate the ``/deploy`` argv shape into ``run_deploy_in_process`` kwargs.

    Mirrors the Click wrapper's argument spec so the slash handler can
    drive the exact same business logic. Unknown flags are dropped — the
    slash command surface is deliberately narrower than the full CLI.
    """
    kwargs: dict[str, Any] = {
        "workflow": None,
        "config_version": None,
        "strategy": "canary",
        "dry_run": False,
        "acknowledge": False,
        "auto_review": False,
        "force_deploy_degraded": False,
        "force_reason": None,
        "attempt_id": None,
        "strict_live": False,
    }
    it = iter(args)
    for token in it:
        if token == "--strategy":
            value = next(it, None)
            if value is not None:
                kwargs["strategy"] = value
        elif token.startswith("--strategy="):
            kwargs["strategy"] = token.split("=", 1)[1]
        elif token in {"canary", "immediate", "release", "rollback", "status"}:
            kwargs["workflow"] = token
        elif token == "--config-version":
            value = next(it, None)
            if value is not None:
                try:
                    kwargs["config_version"] = int(value)
                except ValueError:
                    pass
        elif token == "--dry-run":
            kwargs["dry_run"] = True
        elif token in _CONFIRM_SKIP_FLAGS:
            kwargs["acknowledge"] = True
        elif token == "--auto-review":
            kwargs["auto_review"] = True
        elif token == "--force-deploy-degraded":
            kwargs["force_deploy_degraded"] = True
        elif token == "--reason":
            value = next(it, None)
            if value is not None:
                kwargs["force_reason"] = value
        elif token == "--attempt-id":
            value = next(it, None)
            if value is not None:
                kwargs["attempt_id"] = value
        elif token == "--strict-live":
            kwargs["strict_live"] = True
        elif token == "--no-strict-live":
            kwargs["strict_live"] = False
        # Unknown flags are intentionally ignored for the slash surface.
    return kwargs


def _resolve_session_attempt_id(
    kwargs: dict[str, Any],
    session: Any,
) -> dict[str, Any]:
    """Inject ``session.last_attempt_id`` when the user omits ``--attempt-id``.

    User-supplied ``attempt_id`` always wins. Raises
    :class:`DeployCommandError` when neither source supplies one so the
    handler can surface a command-shape error rather than letting a
    deploy start without attempt linkage.
    """
    out = dict(kwargs)
    if out.get("attempt_id"):
        return out
    session_value = (
        getattr(session, "last_attempt_id", None) if session is not None else None
    )
    if not session_value:
        raise DeployCommandError(
            "/deploy: no attempt in session — run /optimize or /improve accept first, "
            "or pass --attempt-id <id>."
        )
    out["attempt_id"] = session_value
    return out


def _build_stream_args(
    original_args: Sequence[str], resolved_kwargs: dict[str, Any]
) -> list[str]:
    """Append session-injected ``--attempt-id`` to argv when absent.

    Preserves the user's original argv order. If the user already passed
    ``--attempt-id``, argv is returned unchanged. Otherwise the
    resolver-provided value is appended so the runner (real + fake) sees
    the canonical invocation.
    """
    out = list(original_args)
    if any(tok == "--attempt-id" for tok in out):
        return out
    injected = resolved_kwargs.get("attempt_id")
    if injected:
        out.extend(["--attempt-id", str(injected)])
    return out


# ---------------------------------------------------------------------------
# Default in-process runner (R4.6) — thread + queue bridge
# ---------------------------------------------------------------------------


def _default_stream_runner(
    args: Sequence[str],
    *,
    cancellation: CancellationToken | None = None,
    stall_timeout_s: float = DEFAULT_STALL_TIMEOUT_S,
) -> Iterator[StreamEvent]:
    """Run ``deploy`` in-process on a background thread; yield events.

    Parses ``args`` into :func:`cli.commands.deploy.run_deploy_in_process`
    kwargs, spins up a worker thread, and bridges the worker's
    ``on_event`` callback into this generator via a :class:`queue.Queue`.
    Domain exceptions are captured and re-raised as
    :class:`DeployCommandError` at the boundary.

    ``cancellation`` and ``stall_timeout_s`` are preserved for
    ``_invoke_runner`` API compatibility; ``stall_timeout_s`` is a no-op
    in-process.
    """
    from cli.commands.deploy import (
        DeployCommandError as _DomainError,
        DeployVerdictBlockedError,
        run_deploy_in_process,
    )

    kwargs = _args_to_kwargs(args)
    q: queue.Queue = queue.Queue()
    error_holder: dict[str, BaseException] = {}

    def _worker() -> None:
        try:
            run_deploy_in_process(**kwargs, on_event=q.put)
        except DeployVerdictBlockedError as exc:
            error_holder["value"] = DeployCommandError(f"deploy blocked: {exc}")
        except _DomainError as exc:
            error_holder["value"] = DeployCommandError(f"deploy: {exc}")
        except BaseException as exc:
            error_holder["value"] = exc
        finally:
            q.put(_SENTINEL)

    t = threading.Thread(target=_worker, daemon=True, name="deploy-in-process")
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
        if isinstance(exc, DeployCommandError):
            raise exc
        raise DeployCommandError(f"deploy: {exc}") from exc


# ---------------------------------------------------------------------------
# Event → transcript line rendering
# ---------------------------------------------------------------------------


def _render_event(event: StreamEvent) -> str | None:
    event_name = str(event.get("event", ""))
    if not event_name:
        return None
    payload = {k: v for k, v in event.items() if k != "event"}
    return format_workbench_event(event_name, payload)


def _advance_phase(spin: Any, event: StreamEvent) -> None:
    """Advance the deploy spinner phase on lifecycle / fallback events."""
    name = str(event.get("event", ""))
    data = {k: v for k, v in event.items() if k != "event"}
    if name == "phase_started":
        spin.update(str(data.get("phase") or "deploying"))
    elif name == "llm.fallback":
        spin.update(f"fallback ({data.get('reason', 'unknown')})")
    elif name == "llm.retry":
        spin.update("retrying JSON parse")


def _summarise(
    events: Iterable[StreamEvent], *, strategy: str | None
) -> Iterator[tuple[StreamEvent, DeploySummary]]:
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
    verdict: str | None = None
    status: str | None = None
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
        elif name == "deploy_complete":
            # R4.6 terminal event: flat-shape metadata the slash handler
            # surfaces in the summary + onDone meta lines.
            candidate_attempt = event.get("attempt_id")
            if candidate_attempt:
                attempt_id = str(candidate_attempt)
            candidate_deployment = event.get("deployment_id")
            if candidate_deployment:
                deployment_id = str(candidate_deployment)
            candidate_verdict = event.get("verdict")
            if candidate_verdict:
                verdict = str(candidate_verdict)
            candidate_status = event.get("status")
            if candidate_status:
                status = str(candidate_status)
        yield event, DeploySummary(
            events=counters["events"],
            phases_completed=counters["phases_completed"],
            artifacts=tuple(artifacts),
            warnings=counters["warnings"],
            errors=counters["errors"],
            next_action=next_action,
            strategy=strategy,
            attempt_id=attempt_id,
            deployment_id=deployment_id,
            verdict=verdict,
            status=status,
        )


def _format_summary(summary: DeploySummary) -> str:
    parts: list[str] = [f"{summary.events} events"]
    if summary.strategy:
        parts.append(f"strategy={summary.strategy}")
    if summary.phases_completed:
        label = "phase" if summary.phases_completed == 1 else "phases"
        parts.append(f"{summary.phases_completed} {label}")
    if summary.artifacts:
        parts.append(f"{len(summary.artifacts)} artifacts")
    if summary.warnings:
        parts.append(f"{summary.warnings} warnings")
    if summary.errors:
        parts.append(theme.error(f"{summary.errors} errors", bold=False))
    status = "failed" if summary.errors else "complete"
    line = f"  /deploy {status} — {', '.join(parts)}"
    return theme.error(line) if summary.errors else theme.success(line, bold=True)


# ---------------------------------------------------------------------------
# Handler + registration
# ---------------------------------------------------------------------------


def make_deploy_handler(
    runner: StreamRunner | None = None,
    prompter: Prompter | None = None,
) -> Callable[..., OnDoneResult]:
    """Return a slash handler closed over ``runner`` and ``prompter``."""
    active_runner = runner or _default_stream_runner
    active_prompter = prompter or _default_prompter

    def _handle_deploy(ctx: SlashContext, *args: str) -> OnDoneResult:
        stream_args = _parse_args(args)
        strategy = _infer_strategy(stream_args)
        echo = ctx.echo

        needs_confirm = not (
            _is_preconfirmed(stream_args) or _is_dry_run(stream_args)
        )
        if needs_confirm:
            message = f"  Deploy with strategy={strategy}? (y/N)"
            try:
                confirmed = active_prompter(message)
            except (KeyboardInterrupt, EOFError):
                confirmed = False
            if not confirmed:
                cancelled = theme.warning("  /deploy cancelled — no changes made.")
                echo(cancelled)
                return on_done(result=cancelled, display="skip")
            stream_args.append("-y")

        # R4.6 — session-aware attempt_id injection.
        session = (
            ctx.meta.get("workbench_session") if isinstance(ctx.meta, dict) else None
        )
        parsed_kwargs = _args_to_kwargs(stream_args)
        try:
            resolved_kwargs = _resolve_session_attempt_id(parsed_kwargs, session)
        except DeployCommandError as exc:
            echo(theme.error(f"  /deploy failed: {exc}"))
            return on_done(
                result=f"  /deploy failed: {exc}",
                display="skip",
                meta_messages=(str(exc),),
            )

        # Thread the resolved attempt_id back into argv so the runner
        # (real + fake) sees the canonical invocation.
        stream_args = _build_stream_args(stream_args, resolved_kwargs)

        echo(theme.command_name(
            f"  /deploy starting — agentlab deploy {shlex.join(stream_args)}".rstrip(),
        ))

        cancellation = ctx.cancellation
        cancelled = False
        final_summary = DeploySummary(strategy=strategy)
        try:
            stream = _invoke_runner(active_runner, stream_args, cancellation)
            with ctx.spinner(f"deploying ({strategy})") as spin:
                for event, summary in _summarise(stream, strategy=strategy):
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
        except DeployCommandError as exc:
            if cancellation is not None and cancellation.cancelled:
                cancelled = True
            else:
                echo(theme.error(f"  /deploy failed: {exc}"))
                return on_done(
                    result=f"  /deploy failed: {exc}",
                    display="skip",
                    meta_messages=(str(exc),),
                )
        except FileNotFoundError as exc:
            echo(theme.error(f"  /deploy failed: {exc}"))
            return on_done(result=None, display="skip")
        except Exception as exc:  # error boundary — must come AFTER domain catches
            # R4.6 — an in-process handler must never crash the TUI.
            echo(theme.error(f"  /deploy crashed: {type(exc).__name__}: {exc}"))
            return on_done(
                result=f"  /deploy crashed: {exc}",
                display="skip",
                meta_messages=(str(exc),),
            )

        if cancelled:
            message = "  /deploy cancelled — ctrl-c; rollout aborted."
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

    return _handle_deploy


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


def build_deploy_command(
    runner: StreamRunner | None = None,
    prompter: Prompter | None = None,
    *,
    description: str = "Deploy the active config (prompts before mutating state)",
) -> LocalCommand:
    """Build the :class:`LocalCommand` for `/deploy`."""
    return LocalCommand(
        name="deploy",
        description=description,
        handler=make_deploy_handler(runner, prompter),
        source="builtin",
        argument_hint="[canary|immediate] [--dry-run] [-y]",
        when_to_use="Use when you are ready to ship the active config.",
        effort="medium",
        allowed_tools=("in-process",),
        sensitive=True,
    )


__all__ = [
    "DeployCommandError",
    "DeploySummary",
    "Prompter",
    "StreamEvent",
    "StreamRunner",
    "build_deploy_command",
    "make_deploy_handler",
]
