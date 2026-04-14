"""Entry point for the Claude-Code-style workbench REPL.

T04 started as a banner/status/input echo-only stub. This module now wires
the slash-command registry (T05) into the loop so ``/help``, ``/status``,
``/build`` etc. dispatch real handlers instead of echoing the raw line —
closing the "Claude-Code-style" promise.

The loop is intentionally minimal but exposes the seams downstream tasks
need: an injectable ``input_provider`` and ``echo`` so tests drive it
without a TTY, an injectable ``registry`` so tests can swap command sets,
and a ``run_workbench_app`` signature stable enough to wire into
``cli/workbench.py``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Iterable

import click

from cli.branding import get_agentlab_version
from cli.permissions import DEFAULT_PERMISSION_MODE, PermissionManager
from cli.workbench_app import theme
from cli.workbench_app.cancellation import CancellationToken
from cli.workbench_app.status_bar import StatusBar, render_snapshot, snapshot_from_workspace

if TYPE_CHECKING:
    from cli.sessions import Session, SessionStore
    from cli.workbench_app.commands import CommandRegistry
    from cli.workbench_app.slash import SlashContext


InputProvider = Callable[[str], str]
"""Callable that returns the next line of input given a prompt string.

Raises ``EOFError`` or ``KeyboardInterrupt`` to end the loop (matching the
built-in ``input()`` contract). Tests inject a generator-backed provider.
"""

EchoFn = Callable[[str], None]
"""Write one line to the transcript. Defaults to :func:`click.echo`."""

DEFAULT_PROMPT = "› "
EXIT_TOKENS = frozenset({"/exit", "/quit", ":q"})
RESUME_HINT_MAX_AGE_SECONDS = 24 * 60 * 60
"""Cap for the '/resume' startup hint: sessions older than 24h stay quiet."""


@dataclass(frozen=True)
class StubAppResult:
    """Return value for the workbench loop — useful for assertions in tests."""

    lines_read: int
    exited_via: str  # "/exit", "eof", "interrupt"
    interrupts: int = 0


def build_status_line(workspace: Any | None, *, color: bool = True) -> str:
    """Render the one-line status shown under the banner.

    Thin wrapper around :mod:`cli.workbench_app.status_bar` that the banner
    uses for its one-shot render. Long-lived callers should hold a
    :class:`StatusBar` instance and call :meth:`StatusBar.render` so state
    can be patched reactively as events arrive.
    """
    snapshot = snapshot_from_workspace(workspace)
    return render_snapshot(snapshot, color=color)


def _default_input_provider(prompt: str) -> str:
    return input(prompt)


def _safe_cwd() -> str:
    """Return the current working directory, or a sentinel on failure.

    Banner rendering runs during startup so any OS-level exception here
    (e.g. the cwd was deleted under us) must not crash the REPL.
    """
    import os

    try:
        return os.getcwd()
    except OSError:
        return "?"


def _permission_mode_for_workspace(workspace: Any | None) -> str:
    """Return the active permission mode without letting settings break launch."""
    root = getattr(workspace, "root", None)
    try:
        return PermissionManager(root=root).mode
    except Exception:  # pragma: no cover - defensive startup path
        return DEFAULT_PERMISSION_MODE


def _render_turn_footer(
    echo: EchoFn,
    workspace: Any | None = None,
    *,
    mode_override: str | None = None,
) -> None:
    """Emit a compact Claude Code-style footer line after each user turn.

    Mirrors Claude Code's bottom-of-input status chrome: a small chevron,
    the current permission mode, and lightweight activity counters. We
    expose it as a separate helper so tests can assert the format without
    standing up the rest of the loop.

    ``mode_override`` lets callers inject a live prompt_toolkit-tracked
    mode (e.g. after shift+tab cycling) so the footer reflects the user's
    current choice before the settings file has been reloaded.
    """
    mode = mode_override or _permission_mode_for_workspace(workspace)
    echo(theme.meta("─" * 72))
    echo(theme.warning(f"⏵ {mode} permissions on · 0 shells, 0 tasks"))


def _iter_input_provider(lines: Iterable[str]) -> InputProvider:
    """Wrap an iterable so it can stand in for ``input()`` in tests."""
    iterator = iter(lines)

    def _provider(_prompt: str) -> str:
        try:
            return next(iterator)
        except StopIteration as exc:
            raise EOFError from exc

    return _provider


def _render_banner(echo: EchoFn, workspace: Any | None) -> None:
    """Render the compact Claude Code-style banner.

    The heavy AgentLab ASCII art is intentionally suppressed here — the
    workbench REPL favours the minimal "sparkle + welcome + status" pattern
    Claude Code uses, so the transcript doesn't eat a whole screen on each
    launch. The ASCII-art banner still lives in :func:`render_startup_banner`
    for one-shot CLI surfaces that want the full branding.
    """
    version = get_agentlab_version()
    cwd = _safe_cwd()
    echo(theme.workspace(f"  ✻ Welcome to AgentLab Workbench  v{version}"))
    echo("")
    echo(theme.meta(f"    cwd: {cwd}"))
    echo(f"    [{build_status_line(workspace)}]")
    echo(theme.meta(f"    {_permission_mode_for_workspace(workspace)} permissions on · ? for shortcuts"))
    echo("")
    echo("  Type /help for commands, /exit to leave.")
    echo("")
    _render_turn_footer(echo, workspace)


def _format_age(seconds: float) -> str:
    """Turn a delta in seconds into a compact "3h ago" style string."""
    seconds = max(0.0, seconds)
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        minutes = int(seconds // 60)
        return f"{minutes}m ago"
    if seconds < RESUME_HINT_MAX_AGE_SECONDS:
        hours = int(seconds // 3600)
        return f"{hours}h ago"
    days = int(seconds // 86400)
    return f"{days}d ago"


def resume_hint(
    store: "SessionStore | None",
    *,
    current: "Session | None" = None,
    max_age_seconds: float = RESUME_HINT_MAX_AGE_SECONDS,
    now: float | None = None,
) -> str | None:
    """Return a one-line ``/resume`` tip when a recent previous session exists.

    ``None`` when there's no store, no prior session, or the latest session
    is older than ``max_age_seconds`` / is the current one. Used by the
    startup banner; extracted as a pure helper so tests don't need to stand
    up the full loop.
    """
    if store is None:
        return None
    try:
        latest = store.latest()
    except Exception:  # pragma: no cover — defensive
        return None
    if latest is None:
        return None
    if current is not None and latest.session_id == current.session_id:
        return None
    now_ts = time.time() if now is None else now
    age = now_ts - (latest.updated_at or 0.0)
    if age > max_age_seconds:
        return None
    title = latest.title or latest.session_id
    return f"  Tip: /resume to continue \"{title}\" ({_format_age(age)})"


def run_workbench_app(
    workspace: Any | None = None,
    *,
    input_provider: InputProvider | None = None,
    echo: EchoFn | None = None,
    prompt: str = DEFAULT_PROMPT,
    show_banner: bool = True,
    cancellation: CancellationToken | None = None,
    session_store: "SessionStore | None" = None,
    session: "Session | None" = None,
    registry: "CommandRegistry | None" = None,
    slash_context: "SlashContext | None" = None,
    prompt_state: Any | None = None,
) -> StubAppResult:
    """Run the interactive workbench loop.

    Parameters
    ----------
    workspace:
        Active :class:`AgentLabWorkspace` or ``None``. Used to render status
        chrome and as context for slash commands.
    input_provider:
        Callable returning the next input line. Accepts an iterable as a
        convenience for tests: ``run_workbench_app(input_provider=["hi"])``.
    echo:
        Callable that writes a transcript line. Defaults to ``click.echo``.
    prompt:
        Prompt text shown before each line. The real app will replace this
        with a prompt_toolkit ``PromptSession`` in a later task.
    show_banner:
        Suppress the banner for test scenarios that only care about loop
        behavior.
    """
    out: EchoFn = echo if echo is not None else click.echo
    if input_provider is None:
        reader: InputProvider = _default_input_provider
    elif callable(input_provider):
        reader = input_provider
    else:
        reader = _iter_input_provider(input_provider)  # type: ignore[arg-type]

    if show_banner:
        _render_banner(out, workspace)
        hint = resume_hint(session_store, current=session)
        if hint is not None:
            out(theme.meta(hint))
            out("")

    token = cancellation if cancellation is not None else CancellationToken()

    # Build a SlashContext so ``/command`` input dispatches through the
    # registry instead of being echoed back. Callers that pass their own
    # context / registry win — tests rely on that to stub handlers. When
    # neither is supplied, we lazily build the built-in registry so the
    # default REPL still reacts to ``/help``, ``/status``, and friends.
    ctx = slash_context
    active_registry = registry
    if ctx is None and active_registry is None:
        from cli.workbench_app.slash import build_builtin_registry

        try:
            active_registry = build_builtin_registry()
        except Exception:  # pragma: no cover — defensive; registry build is cheap
            active_registry = None
    if ctx is None and active_registry is not None:
        from cli.workbench_app.slash import SlashContext

        ctx = SlashContext(
            workspace=workspace,
            session=session,
            session_store=session_store,
            echo=out,
            registry=active_registry,
            cancellation=token,
        )
    elif ctx is not None:
        # Keep the caller-supplied context in sync with the loop's echo /
        # cancellation so transcript output and ctrl-c both route correctly.
        ctx.echo = out
        if ctx.cancellation is None:
            ctx.cancellation = token

    lines_read = 0
    interrupts = 0
    exited_via = "eof"
    while True:
        try:
            raw = reader(prompt)
        except EOFError:
            exited_via = "eof"
            out("")
            break
        except KeyboardInterrupt:
            # T16 double-ctrl-c semantics:
            #   1st press with an active tool call → cancel it.
            #   1st press at idle → warn the user to press again.
            #   2nd consecutive press (no successful input between) → exit.
            if token.active:
                token.cancel()
                interrupts += 1
                out("")
                out(theme.warning(
                    "  (cancelled active tool call — press ctrl-c again to exit)"
                ))
                continue
            interrupts += 1
            if interrupts >= 2:
                exited_via = "interrupt"
                out("")
                out(theme.warning("  (interrupted)"))
                break
            out("")
            out(theme.warning("  (press ctrl-c again to exit, or /exit)"))
            continue

        # A successful read resets the interrupt streak so the user can
        # recover from a stray ctrl-c without getting forced out.
        interrupts = 0
        token.reset()

        line = raw.strip()
        if not line:
            continue

        lines_read += 1

        if line.lower() in EXIT_TOKENS:
            exited_via = "/exit"
            out(theme.meta("  Goodbye."))
            break

        # Route ``/command`` input through the slash registry when one is
        # bound. Non-slash input has no model integration yet, so we echo
        # it as a received-turn acknowledgement until the model layer lands.
        handled_as_slash = False
        if ctx is not None and line.startswith("/"):
            from cli.workbench_app.slash import dispatch

            result = dispatch(ctx, line)
            if result.handled:
                if ctx.exit_requested:
                    exited_via = "/exit"
                    break
                handled_as_slash = True

        if not handled_as_slash:
            out(theme.user(f"  AgentLab received: {line}", bold=False))

        _render_turn_footer(
            out,
            workspace,
            mode_override=getattr(prompt_state, "mode", None),
        )

    return StubAppResult(
        lines_read=lines_read,
        exited_via=exited_via,
        interrupts=interrupts,
    )


def launch_workbench(
    workspace: Any | None,
    *,
    show_banner: bool = True,
    input_provider: InputProvider | None = None,
    echo: EchoFn | None = None,
) -> StubAppResult:
    """Create a persisted session and run the workbench app.

    Thin wrapper used by both ``agentlab`` (default entry) and
    ``agentlab workbench interactive`` so session wiring stays in one
    place. When no workspace is active we still run the loop with an
    ephemeral in-memory session — persistence is a best-effort feature,
    not a precondition for launching.

    The default input path attaches a prompt_toolkit session with the
    slash-command completer, a ``╭─╮ / ╰─╯`` border around the input,
    and a shift+tab binding that cycles the permission mode. Callers
    supplying ``input_provider`` (tests, piped stdin) skip this wiring.
    """
    import sys

    from cli.sessions import Session, SessionStore
    from cli.workbench_app.slash import SlashContext, build_builtin_registry

    store: SessionStore | None = None
    session: Session | None = None
    if workspace is not None:
        try:
            store = SessionStore(workspace.root)
            session = store.create()
        except Exception:  # pragma: no cover — defensive
            store = None
            session = None
    if session is None:
        session = Session(
            session_id=uuid_hex(),
            title="ephemeral",
            started_at=time.time(),
            updated_at=time.time(),
        )
    registry = build_builtin_registry()
    ctx = SlashContext(
        workspace=workspace,
        session=session,
        session_store=store,
        registry=registry,
    )

    resolved_echo: EchoFn = echo if echo is not None else click.echo
    provider = input_provider
    prompt_state: Any | None = None
    if provider is None and sys.stdin.isatty():
        try:
            from cli.workbench_app.pt_prompt import (
                WorkbenchPromptState,
                build_prompt_input_provider,
            )

            prompt_state = WorkbenchPromptState(
                workspace=workspace,
                mode=_permission_mode_for_workspace(workspace),
            )
            provider = build_prompt_input_provider(
                registry, prompt_state, echo=resolved_echo
            )
        except Exception:  # pragma: no cover — fall back to input() on any failure
            provider = None

    return run_workbench_app(
        workspace,
        show_banner=show_banner,
        input_provider=provider,
        echo=echo,
        session_store=store,
        session=session,
        registry=registry,
        slash_context=ctx,
        prompt_state=prompt_state,
    )


def uuid_hex() -> str:
    """Generate a short id for ephemeral sessions."""
    import uuid

    return uuid.uuid4().hex[:12]


__all__ = [
    "DEFAULT_PROMPT",
    "EXIT_TOKENS",
    "RESUME_HINT_MAX_AGE_SECONDS",
    "EchoFn",
    "InputProvider",
    "StubAppResult",
    "build_status_line",
    "launch_workbench",
    "resume_hint",
    "run_workbench_app",
]
