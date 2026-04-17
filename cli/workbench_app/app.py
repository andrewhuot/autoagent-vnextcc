"""Entry point for the Claude-Code-style workbench REPL.

T04 started as a banner/status/input echo-only stub. This module now wires
the slash-command registry (T05) into the loop so ``/help``, ``/status``,
``/build`` etc. dispatch real handlers instead of echoing the raw line.
Plain text is kept on the chat path; coordinator fan-out is reserved for
explicit workflow commands.

The loop is intentionally minimal but exposes the seams downstream tasks
need: an injectable ``input_provider`` and ``echo`` so tests drive it
without a TTY, an injectable ``registry`` so tests can swap command sets,
and a ``run_workbench_app`` signature stable enough to wire into
``cli/workbench.py``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterable

import click

from cli.branding import get_agentlab_version, render_startup_banner
from cli.permissions import DEFAULT_PERMISSION_MODE, PermissionManager
from cli.terminal_renderer import render_box, terminal_width
from cli.workbench_app import theme
from cli.workbench_app.cancellation import CancellationToken
from cli.workbench_app.help_text import render_shortcuts_help
from cli.workbench_app.input_router import EXIT_TOKENS, InputKind, route_user_input
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
WORKFLOW_COMMANDS = frozenset({"build", "eval", "optimize", "deploy", "ship", "skills"})
RESUME_HINT_MAX_AGE_SECONDS = 24 * 60 * 60
"""Cap for the '/resume' startup hint: sessions older than 24h stay quiet."""


@dataclass(frozen=True)
class StubAppResult:
    """Return value for the workbench loop — useful for assertions in tests."""

    lines_read: int
    exited_via: str  # "/exit", "eof", "interrupt"
    interrupts: int = 0


@dataclass(frozen=True)
class _ChatModelChoice:
    """Resolved model for the Workbench chat runtime."""

    model: str
    active_model: str
    api_key: str | None = None


def build_status_line(
    workspace: Any | None,
    *,
    color: bool = True,
    agent_runtime: Any | None = None,
    chat_runtime: Any | None = None,
    show_chat_badge: bool = False,
) -> str:
    """Render the one-line status shown under the banner.

    Thin wrapper around :mod:`cli.workbench_app.status_bar` that the banner
    uses for its one-shot render. Long-lived callers should hold a
    :class:`StatusBar` instance and call :meth:`StatusBar.render` so state
    can be patched reactively as events arrive.

    When ``agent_runtime`` is supplied, a ``worker:`` badge is appended
    showing ``llm`` or ``stub`` so operators see the active mode without
    running ``/doctor`` first.
    """
    snapshot = snapshot_from_workspace(workspace)
    if agent_runtime is not None:
        badge = _worker_mode_badge(agent_runtime)
        if badge is not None:
            snapshot = replace_snapshot_extras(snapshot, ("worker", badge))
    if show_chat_badge:
        chat_badge = "configured" if chat_runtime is not None else "unconfigured"
        snapshot = replace_snapshot_extras(snapshot, ("chat", chat_badge))
    return render_snapshot(snapshot, color=color)


def replace_snapshot_extras(snapshot, pair):
    """Return a copy of ``snapshot`` with ``pair`` appended to ``extras``."""
    from dataclasses import replace

    return replace(snapshot, extras=tuple(list(snapshot.extras) + [pair]))


def _worker_mode_badge(agent_runtime: Any) -> str | None:
    """Return the ``(label, value)`` badge string describing the active worker mode."""
    mode = getattr(agent_runtime, "worker_mode", None)
    if mode is None:
        return None
    degraded = getattr(agent_runtime, "worker_mode_degraded_reason", None)
    if degraded:
        return "stub"
    return getattr(mode, "value", str(mode))


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
    active_shells: int = 0,
    active_tasks: int = 0,
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
    activity = _format_activity(
        active_shells=active_shells,
        active_tasks=active_tasks,
    )
    echo(theme.meta("─" * 72))
    mode_label = theme.format_mode(mode, color=False)
    echo(theme.warning(f"⏵ {mode_label} permissions on · {activity}"))


def _format_activity(*, active_shells: int = 0, active_tasks: int = 0) -> str:
    """Render truthful footer activity instead of placeholder counters."""
    parts: list[str] = []
    if active_shells > 0:
        noun = "shell" if active_shells == 1 else "shells"
        parts.append(f"{active_shells} {noun}")
    if active_tasks > 0:
        noun = "task" if active_tasks == 1 else "tasks"
        parts.append(f"{active_tasks} {noun}")
    return ", ".join(parts) if parts else "idle"


def _iter_input_provider(lines: Iterable[str]) -> InputProvider:
    """Wrap an iterable so it can stand in for ``input()`` in tests."""
    iterator = iter(lines)

    def _provider(_prompt: str) -> str:
        try:
            return next(iterator)
        except StopIteration as exc:
            raise EOFError from exc

    return _provider


def _render_banner(
    echo: EchoFn,
    workspace: Any | None,
    *,
    agent_runtime: Any | None = None,
    chat_runtime: Any | None = None,
) -> None:
    """Render the branded ASCII-logo intro + Claude-Code-style welcome card.

    The AgentLab logo (logo + wordmark + "Experiment. Evaluate. Refine."
    tagline) anchors the top so the REPL feels like *our* tool rather
    than a clone. Below it we render Claude Code's signature rounded
    welcome card: a ``✻ Welcome`` title, cwd, one-line status, and
    permission/shortcuts hints — all boxed together so the eye lands on
    a single card on first render.
    """
    version = get_agentlab_version()
    cwd = _safe_cwd()
    echo(render_startup_banner(version))
    echo("")

    # Size the welcome card to the narrower of the terminal width or a
    # comfortable reading width. Claude Code's card is not full-width on
    # wide monitors — it feels lighter when capped.
    card_width = min(terminal_width(), 76)
    mode_label = theme.format_mode(_permission_mode_for_workspace(workspace), color=False)
    status = build_status_line(
        workspace,
        color=False,
        agent_runtime=agent_runtime,
        chat_runtime=chat_runtime,
        show_chat_badge=True,
    )
    body_lines: list[str] = [
        theme.accent(f"✻ Welcome to AgentLab Workbench  v{version}"),
        "",
        theme.meta(f"cwd: {cwd}"),
        theme.meta(f"status: {status}"),
        "",
        theme.meta(f"{mode_label} permissions on · ? for shortcuts · / for commands"),
        theme.meta("Type /help for commands. Plain text is chat. /exit to leave."),
    ]
    for line in render_box(body_lines, width=card_width, padding=2):
        echo(line)
    echo("")


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
    agent_runtime: Any | None = None,
    orchestrator: Any | None = None,
    prompt_owns_footer: bool = False,
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
    prompt_owns_footer:
        True when the live prompt_toolkit session is rendering the bottom
        toolbar. In that mode the loop does not echo an extra post-turn
        footer, avoiding duplicated/clipped bottom chrome.
    orchestrator:
        Optional :class:`~cli.llm.orchestrator.LLMOrchestrator` (or a
        :class:`~cli.workbench_app.orchestrator_runtime.WorkbenchRuntime`
        wrapper). When supplied, natural-language turns are routed through
        it — giving the REPL live tool-calling, permission dialogs,
        streaming markdown, and hook integration. ``agent_runtime`` still
        handles ``/build``/``/eval``/``/optimize``/``/deploy`` workflow
        commands because those exercise agentlab-specific coordinator
        logic rather than chat. When neither the orchestrator nor the
        agent runtime is supplied, free-text input echoes back (the
        headless test default).
    """
    out: EchoFn = echo if echo is not None else click.echo
    if input_provider is None:
        reader: InputProvider = _default_input_provider
    elif callable(input_provider):
        reader = input_provider
    else:
        reader = _iter_input_provider(input_provider)  # type: ignore[arg-type]

    # Build the workflow runtime before the banner so the welcome card can show
    # the active worker mode (llm vs stub). The runtime resolves this from
    # harness.models.worker + credentials; hiding it behind a post-banner
    # notice means users don't realize they're on canned stubs until a
    # turn completes with suspiciously fast, uniform output.
    active_workflow_runtime = agent_runtime
    if active_workflow_runtime is None and workspace is not None:
        try:
            from cli.workbench_app.runtime import build_default_agent_runtime

            active_workflow_runtime = build_default_agent_runtime(workspace)
        except Exception:  # pragma: no cover - defensive startup path
            active_workflow_runtime = None

    active_orchestrator = _resolve_orchestrator(orchestrator)

    if show_banner:
        _render_banner(
            out,
            workspace,
            agent_runtime=active_workflow_runtime,
            chat_runtime=active_orchestrator,
        )
        hint = resume_hint(session_store, current=session)
        if hint is not None:
            out(theme.meta(hint))
            out("")
        if active_workflow_runtime is not None:
            degraded = getattr(active_workflow_runtime, "worker_mode_degraded_reason", None)
            if degraded:
                out(theme.warning(f"⚠ Worker mode: deterministic stub — {degraded}"))
                out(theme.meta("  Run /doctor for provider + credential diagnostics."))
                out("")

    token = cancellation if cancellation is not None else CancellationToken()

    # Build a SlashContext so ``/command`` input dispatches through the
    # registry instead of being echoed back. Callers that pass their own
    # context / registry win — tests rely on that to stub handlers. When
    # neither is supplied, we lazily build the built-in registry so the
    # default REPL still reacts to ``/help``, ``/status``, and friends.
    ctx = slash_context
    active_registry = registry
    if active_registry is None and ctx is not None:
        active_registry = ctx.registry
    if active_registry is None:
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
        # Fill only missing bindings so explicit context fields still win.
        ctx.echo = out
        if ctx.workspace is None:
            ctx.workspace = workspace
        if ctx.session is None:
            ctx.session = session
        if ctx.session_store is None:
            ctx.session_store = session_store
        if ctx.registry is None:
            ctx.registry = active_registry
        if ctx.cancellation is None:
            ctx.cancellation = token

    if ctx is not None and active_workflow_runtime is not None:
        ctx.meta["agent_runtime"] = active_workflow_runtime
        ctx.coordinator_session = getattr(active_workflow_runtime, "coordinator_session", None)

    # When an orchestrator is supplied, publish its subsystems onto the
    # slash context so /plan, /skill, /transcript-*, /background, /usage
    # all see the live state the orchestrator is using. Without this the
    # slash layer would fall back to "not configured" warnings even
    # though the REPL is running with a full orchestrator stack.
    if ctx is not None and active_orchestrator is not None:
        _publish_orchestrator_meta(ctx, orchestrator)

    def _maybe_render_turn_footer() -> None:
        if prompt_owns_footer:
            return
        _render_turn_footer(
            out,
            workspace,
            mode_override=getattr(prompt_state, "mode", None),
            active_shells=_meta_int(ctx, "active_shells"),
            active_tasks=_meta_int(ctx, "active_tasks"),
        )

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

        route = route_user_input(raw)
        if route.kind is InputKind.EMPTY:
            continue

        lines_read += 1

        if route.kind is InputKind.EXIT:
            exited_via = "/exit"
            out(theme.meta("  Goodbye."))
            break

        if route.kind is InputKind.SHORTCUTS:
            out(render_shortcuts_help())
            _maybe_render_turn_footer()
            continue

        # `!cmd` — shell-mode passthrough, gated by permission mode.
        if route.kind is InputKind.SHELL:
            current_mode = (
                getattr(prompt_state, "mode", None)
                or _permission_mode_for_workspace(workspace)
            )
            _run_shell_turn(
                ctx=ctx,
                workspace=workspace,
                line=route.payload,
                permission_mode=current_mode,
                echo=out,
                reader=reader,
            )
            _maybe_render_turn_footer()
            continue

        # `&cmd` — dispatch the remainder as a background coordinator turn.
        if route.kind is InputKind.BACKGROUND:
            _run_background_turn(
                runtime=active_workflow_runtime,
                ctx=ctx,
                line=route.payload,
                echo=out,
            )
            _maybe_render_turn_footer()
            continue

        # Route ``/command`` input through the slash registry when one is
        # bound. Plain text is handled below as chat and never falls through
        # to the workflow coordinator.
        handled_as_slash = False
        if route.kind is InputKind.SLASH and ctx is not None:
            from cli.workbench_app.slash import dispatch, parse_slash_line

            line = route.payload
            parsed = parse_slash_line(line)
            command_name = route.command_name or (parsed[0] if parsed else "")
            current_mode = (
                getattr(prompt_state, "mode", None)
                or _permission_mode_for_workspace(workspace)
            )
            if (
                active_workflow_runtime is not None
                and command_name in WORKFLOW_COMMANDS
                and _should_gate_with_plan(ctx, current_mode)
            ):
                args = parsed[1] if parsed else []
                _run_plan_gated_turn(
                    runtime=active_workflow_runtime,
                    ctx=ctx,
                    line=" ".join(args).strip() or _default_workflow_message(command_name),
                    echo=out,
                    reader=reader,
                    command_intent=_workflow_command_intent(command_name),
                )
                handled_as_slash = True
            else:
                result = dispatch(ctx, line)
                if result.handled:
                    if ctx.exit_requested:
                        exited_via = "/exit"
                        break
                    _run_follow_up_turns(
                        orchestrator=active_orchestrator,
                        ctx=ctx,
                        result=result,
                        echo=out,
                        bridge=getattr(orchestrator, "conversation_bridge", None),
                        session=getattr(orchestrator, "workbench_session", None),
                        model_id=getattr(orchestrator, "model_id", None),
                    )
                    handled_as_slash = True
            if ctx.exit_requested:
                exited_via = "/exit"
                break

        if route.kind is InputKind.SLASH:
            if not handled_as_slash:
                out(theme.warning("  Slash commands are not available in this session."))
            _maybe_render_turn_footer()
            continue

        if route.kind is InputKind.CHAT:
            line = route.payload
            _persist_user_turn(
                ctx=ctx,
                session_store=session_store,
                session=session,
                line=line,
            )
            if active_orchestrator is not None:
                # Orchestrator path: real LLM turn with tool-calling,
                # permission dialogs, hooks, and streaming markdown. All
                # subsystems were published onto ctx.meta above so slash
                # commands fired from inside this turn see the same state.
                # Pull the conversation bridge from the bundle (R7.B.7) so
                # each user/assistant turn mirrors into SQLite. Legacy
                # callers that pass a bare orchestrator skip the bridge.
                _run_orchestrator_turn(
                    orchestrator=active_orchestrator,
                    ctx=ctx,
                    line=line,
                    echo=out,
                    bridge=getattr(orchestrator, "conversation_bridge", None),
                    session=getattr(orchestrator, "workbench_session", None),
                    model_id=getattr(orchestrator, "model_id", None),
                )
            else:
                _run_chat_unavailable_turn(echo=out)

        _maybe_render_turn_footer()

    return StubAppResult(
        lines_read=lines_read,
        exited_via=exited_via,
        interrupts=interrupts,
    )


def _meta_int(ctx: "SlashContext | None", key: str) -> int:
    """Read an integer activity counter from slash context metadata."""
    if ctx is None:
        return 0
    value = ctx.meta.get(key, 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _persist_user_turn(
    *,
    ctx: "SlashContext | None",
    session_store: "SessionStore | None",
    session: "Session | None",
    line: str,
) -> None:
    """Best-effort persistence for non-slash user turns.

    Slash commands already write command history during dispatch. Free text
    needs a separate path so `/resume` can reconstruct the operator's side of
    the session before full model integration lands.
    """
    if ctx is not None and ctx.transcript is not None:
        ctx.transcript.append_user(line, emit=False)
        if ctx.transcript.bound_session is not None:
            return

    store = (
        ctx.session_store
        if ctx is not None and ctx.session_store is not None
        else session_store
    )
    active_session = (
        ctx.session if ctx is not None and ctx.session is not None else session
    )
    if store is None or active_session is None:
        return
    try:
        store.append_entry(active_session, "user", line)
    except Exception:  # pragma: no cover - defensive persistence path
        pass


def _run_agent_turn(
    *,
    runtime: Any,
    ctx: "SlashContext | None",
    line: str,
    echo: EchoFn,
    command_intent: str | None = None,
) -> None:
    """Route one user turn into the coordinator and echo its transcript lines.

    Prefers the streaming ``process_turn(stream=True)`` path when the
    runtime exposes it so worker state transitions render live instead of
    all-at-once after the full turn completes. Falls back to the batched
    path transparently when a stub runtime doesn't understand ``stream``.
    """
    outcome = _stream_turn_with_live_echo(
        runtime=runtime,
        ctx=ctx,
        line=line,
        echo=echo,
        command_intent=command_intent,
    )
    if outcome is _STREAM_NOT_SUPPORTED:
        try:
            result = runtime.process_turn(line, ctx=ctx, command_intent=command_intent)
        except Exception as exc:
            echo(theme.error(f"  Coordinator error: {exc}", bold=False))
            return
        try:
            from cli.workbench_app.runtime import remember_turn_result

            remember_turn_result(ctx, result)
        except Exception:  # pragma: no cover - metadata sync is best effort
            pass
        for transcript_line in tuple(getattr(result, "transcript_lines", ()) or ()):
            echo(str(transcript_line))
    elif outcome is not None:
        # Streaming path already echoed per-event progress lines; emit
        # the header + trailing summary lines the live loop didn't cover.
        result, live_text = outcome
        _echo_post_stream_summary(
            result=result, echo=echo, live_echoed_lines=live_text
        )


# Sentinel returned by the streaming helper when the runtime does not
# accept ``stream=True`` — callers fall back to the batched path.
_STREAM_NOT_SUPPORTED = object()


def _stream_turn_with_live_echo(
    *,
    runtime: Any,
    ctx: "SlashContext | None",
    line: str,
    echo: EchoFn,
    command_intent: str | None,
) -> Any:
    """Iterate coordinator events as they arrive and render progress live.

    Returns:
        - ``(result, live_echoed_text)`` when streaming succeeded. The set
          contains the original (un-prefixed) transcript strings the live
          loop already echoed so callers can skip duplicates when emitting
          the batched transcript's header and synthesis footer.
        - ``None`` if the streaming path raised (error already echoed).
        - ``_STREAM_NOT_SUPPORTED`` when the runtime has no ``stream`` kwarg.
    """
    try:
        stream = runtime.process_turn(
            line,
            ctx=ctx,
            command_intent=command_intent,
            stream=True,
        )
    except TypeError:
        # The runtime (likely a test stub) doesn't accept ``stream``; let
        # the caller fall back to the batched invocation.
        return _STREAM_NOT_SUPPORTED
    except Exception as exc:
        echo(theme.error(f"  Coordinator error: {exc}", bold=False))
        return None

    from cli.workbench_app.coordinator_render import (
        format_coordinator_event,
        render_progress_line,
        worker_phase_verb,
    )
    from cli.workbench_app.effort import EffortIndicator

    indicator = EffortIndicator()
    indicator.start()
    start_ts = time.time()
    result: Any = None
    live_text: set[str] = set()
    try:
        while True:
            try:
                event = next(stream)
            except StopIteration as stop:
                result = stop.value
                break
            verb = worker_phase_verb(event)
            if verb is not None:
                indicator.set_verb(verb)
                indicator.record_progress()
            rendered = render_progress_line(event, start_ts)
            if rendered is not None:
                echo(rendered)
                base = format_coordinator_event(event)
                if base is not None:
                    live_text.add(base.strip())
    except Exception as exc:
        echo(theme.error(f"  Coordinator error: {exc}", bold=False))
        return None
    finally:
        indicator.stop()
    return result, live_text


def _echo_post_stream_summary(
    *, result: Any, echo: EchoFn, live_echoed_lines: set[str]
) -> None:
    """Echo header + ``Next:`` lines the live stream didn't cover itself.

    The live echo path prints each worker event as a Claude-style progress
    line. The batched transcript also includes a ``Coordinator plan X
    created for N worker(s).`` header and a trailing ``Next: ...``
    summary. We surface any transcript line that wasn't matched by a live
    progress echo so the operator still sees the plan header and the
    synthesis hint without duplicating per-event lines.
    """
    lines = tuple(getattr(result, "transcript_lines", ()) or ())
    for candidate in lines:
        text = str(candidate)
        if text.strip() in live_echoed_lines:
            continue
        echo(text)


def _should_gate_with_plan(ctx: "SlashContext | None", mode: str | None) -> bool:
    """Return True when the current turn must route through :class:`PlanGate`.

    ``plan`` permission mode opts into approval-before-execution for every
    free-text coordinator turn. Respects an explicit ``ctx.meta[\"skip_plan_gate\"] = True``
    override so tests / embedders can short-circuit when they're driving
    process_turn directly.
    """
    if ctx is not None and bool(ctx.meta.get("skip_plan_gate")):
        return False
    if not mode:
        return False
    return str(mode).lower() == "plan"


def _run_plan_gated_turn(
    *,
    runtime: Any,
    ctx: "SlashContext | None",
    line: str,
    echo: EchoFn,
    reader: InputProvider,
    command_intent: str | None = None,
) -> None:
    """Route one free-text turn through the plan-mode approval gate.

    The gate drives the plan-then-confirm loop and, on approval, executes
    the real turn through ``runtime.process_turn``. We keep the gate's
    batched execution here (plan-mode already requires a round-trip with
    the operator, so live streaming during execution is less critical)
    and echo the same transcript the non-gated batched path would.
    """
    try:
        from cli.workbench_app.plan_gate import PlanGate
    except Exception:  # pragma: no cover - defensive import
        _run_agent_turn(runtime=runtime, ctx=ctx, line=line, echo=echo)
        return

    def _prompt(prompt_text: str) -> str:
        try:
            return reader(prompt_text)
        except (EOFError, KeyboardInterrupt):
            return "n"

    gate = PlanGate(runtime, prompt_fn=_prompt, echo_fn=echo)
    try:
        outcome = gate.run(line, ctx=ctx, command_intent=command_intent)
    except Exception as exc:
        echo(theme.error(f"  Plan gate error: {exc}", bold=False))
        return

    if outcome.decision == "approved":
        try:
            from cli.workbench_app.runtime import remember_turn_result

            remember_turn_result(ctx, outcome.result)
        except Exception:  # pragma: no cover - metadata sync is best effort
            pass
        for transcript_line in tuple(getattr(outcome.result, "transcript_lines", ()) or ()):
            echo(str(transcript_line))


def _run_shell_turn(
    *,
    ctx: "SlashContext | None",
    workspace: Any | None,
    line: str,
    permission_mode: str,
    echo: EchoFn,
    reader: InputProvider,
) -> None:
    """Run a ``!`` shell-mode line via :func:`shell_mode.run_shell_turn`.

    Maintains ``ctx.meta["active_shells"]`` while the subprocess executes so
    the truthful footer reflects the running work.
    """
    try:
        from cli.workbench_app.shell_mode import run_shell_turn
    except Exception as exc:  # pragma: no cover - defensive import
        echo(theme.error(f"  Shell mode error: {exc}", bold=False))
        return

    root: Any | None = getattr(workspace, "root", None)
    if ctx is not None:
        ctx.meta["active_shells"] = _meta_int(ctx, "active_shells") + 1
    try:
        run_shell_turn(
            line,
            permission_mode=permission_mode,
            echo=echo,
            input_provider=reader,
            workspace_root=root,
        )
    finally:
        if ctx is not None:
            remaining = max(0, _meta_int(ctx, "active_shells") - 1)
            ctx.meta["active_shells"] = remaining


def _run_background_turn(
    *,
    runtime: Any | None,
    ctx: "SlashContext | None",
    line: str,
    echo: EchoFn,
) -> None:
    """Spawn a coordinator turn marked as background work.

    Background dispatch runs the coordinator turn synchronously here but
    adds the request to ``ctx.meta["background_queue"]`` and bumps
    ``ctx.meta["active_tasks"]`` so the truthful footer reflects the queued
    work. The counter is adjusted again after the turn returns so the
    footer reads ``idle`` once nothing is left to do.
    """
    text = line.strip()
    if not text:
        echo(theme.warning("  Background mode: provide a request after '&'."))
        return
    if runtime is None:
        echo(theme.warning(
            "  Background mode: coordinator runtime is not available."
        ))
        return

    if ctx is not None:
        ctx.meta["active_tasks"] = _meta_int(ctx, "active_tasks") + 1
        queue = list(ctx.meta.get("background_queue") or [])
        queue.append(text)
        ctx.meta["background_queue"] = queue

    echo(theme.meta(f"  Dispatched background task: {text}"))
    try:
        _run_agent_turn(
            runtime=runtime, ctx=ctx, line=text, echo=echo,
            command_intent="background",
        )
    finally:
        if ctx is not None:
            queue = list(ctx.meta.get("background_queue") or [])
            if queue and queue[-1] == text:
                queue.pop()
            ctx.meta["background_queue"] = queue
            # After the synchronous turn completes, leave only queued work
            # visible in the footer. `_run_agent_turn` may have overwritten
            # ``active_tasks`` via ``remember_turn_result``; align it with
            # the actual queue length so the footer stays truthful.
            ctx.meta["active_tasks"] = len(queue)


def _run_chat_unavailable_turn(*, echo: EchoFn) -> None:
    """Tell the user why plain text cannot be answered locally yet."""
    echo(theme.warning("  Plain prompts need a chat model before I can answer here."))
    echo(theme.meta(
        "  Try /help for commands, /build <brief> for coordinator workflows, "
        "or /model to inspect model setup."
    ))
    echo(theme.meta("  Run /doctor for provider and credential diagnostics."))


def _default_workflow_message(command_name: str) -> str:
    """Return a useful prompt when a workflow slash command has no args."""
    defaults = {
        "build": "Build or refine the active agent.",
        "eval": "Evaluate the active agent candidate and summarize failures.",
        "optimize": "Optimize the agent from the latest eval evidence.",
        "deploy": "Prepare a canary deployment and rollback plan.",
        "ship": "Apply pending review, create a release, and prepare a canary deployment.",
        "skills": "Recommend build-time skills that would improve this agent.",
    }
    return defaults.get(command_name, "Continue the agent build.")


def _workflow_command_intent(command_name: str) -> str:
    """Map slash-command aliases onto coordinator intents accepted by the runtime."""
    if command_name == "ship":
        return "deploy"
    return command_name


def _run_follow_up_turns(
    *,
    orchestrator: Any | None,
    ctx: "SlashContext | None",
    result: Any,
    echo: EchoFn,
    bridge: Any | None = None,
    session: Any | None = None,
    model_id: str | None = None,
) -> None:
    """Process command-requested follow-up prompts through the chat path."""
    prompt: str | None = None
    if getattr(result, "submit_next_input", False) and getattr(result, "next_input", None):
        prompt = str(result.next_input)
    elif getattr(result, "should_query", False) and getattr(result, "raw_result", None):
        prompt = str(result.raw_result)
    if not prompt:
        return
    if orchestrator is None:
        _run_chat_unavailable_turn(echo=echo)
        return
    _run_orchestrator_turn(
        orchestrator=orchestrator,
        ctx=ctx,
        line=prompt,
        echo=echo,
        bridge=bridge,
        session=session,
        model_id=model_id,
    )


def _maybe_run_first_run_onboarding(workspace: Any | None) -> None:
    """Run guided onboarding before launching the REPL when needed.

    Triggers when *either*:
    - no ``agentlab.yaml`` is discoverable from the active workspace root
      (or the current directory when the REPL was launched outside one), or
    - an ``agentlab.yaml`` exists but its ``harness.models.{coordinator,worker}``
      keys are missing/invalid — the exact case LLM worker mode blows up on.

    Silent on failure: onboarding is best-effort and must not prevent
    the REPL from coming up for users who know what they're doing.
    """
    import os as _os
    from pathlib import Path as _Path

    if workspace is not None:
        config_path = _Path(getattr(workspace, "runtime_config_path", workspace.root / "agentlab.yaml"))
    else:
        config_path = _Path(_os.getcwd()) / "agentlab.yaml"

    try:
        from cli.harness_onboarding import needs_harness_config
    except Exception:  # pragma: no cover — defensive
        return

    should_prompt_for_workspace = workspace is None and not config_path.exists()
    try:
        should_prompt_for_models = needs_harness_config(config_path)
    except Exception:  # pragma: no cover — never block REPL on doctor errors
        should_prompt_for_models = False

    if not (should_prompt_for_workspace or should_prompt_for_models):
        return

    try:
        if should_prompt_for_workspace:
            from cli.onboarding import run_onboarding

            run_onboarding()
        else:
            from cli.onboarding import _maybe_run_harness_wizard  # type: ignore[attr-defined]

            _maybe_run_harness_wizard(config_path)
    except (EOFError, KeyboardInterrupt):  # pragma: no cover — user bailed
        return
    except Exception:  # pragma: no cover — defensive: never block REPL
        return


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
    slash-command completer, prompt-owned footer chrome, and a shift+tab
    binding that cycles the permission mode. Callers supplying
    ``input_provider`` (tests, piped stdin) skip this wiring.
    """
    import os
    import sys

    from cli.sessions import Session, SessionStore
    from cli.workbench_app.slash import SlashContext, build_builtin_registry

    # ---- TUI feature flag ----
    # When AGENTLAB_TUI=1 is set and a TTY is available, launch the Textual
    # TUI instead of the legacy REPL loop. The TUI codepath is fully
    # independent — it wires its own store, widgets, and event bridge.
    if (
        os.environ.get("AGENTLAB_TUI", "").lower() in ("1", "true")
        and input_provider is None
        and sys.stdin.isatty()
    ):
        try:
            from cli.workbench_app.tui.app import run_tui_app

            return run_tui_app(workspace, show_banner=show_banner, echo=echo)
        except ImportError:
            # Textual not installed — fall through to legacy REPL.
            pass

    # Gate onboarding on env escape hatch, an explicit input_provider
    # (tests drive the REPL synchronously), and a TTY check so piped
    # stdin doesn't get consumed by the wizard prompts.
    if (
        not os.environ.get("AGENTLAB_SKIP_ONBOARDING")
        and input_provider is None
        and sys.stdin.isatty()
    ):
        _maybe_run_first_run_onboarding(workspace)

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

    orchestrator_bundle = _maybe_build_orchestrator(workspace, session, store, resolved_echo)

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
        orchestrator=orchestrator_bundle,
        prompt_owns_footer=prompt_state is not None,
    )


def _maybe_build_orchestrator(
    workspace: Any | None,
    session: "Session | None",
    store: "SessionStore | None",
    echo: EchoFn,
) -> Any | None:
    """Build the :class:`WorkbenchRuntime` bundle when chat can really run.

    Plain text now belongs to the chat path, so startup should attach the
    orchestrator whenever a usable model is configured. Missing keys or
    unsupported adapters return ``None`` and the REPL renders local guidance
    instead of silently falling back to an echo model or coordinator workers.
    Set ``AGENTLAB_CLASSIC_COORDINATOR=1`` to force-disable chat while
    debugging.
    """
    import os

    if os.environ.get("AGENTLAB_CLASSIC_COORDINATOR"):
        return None
    if workspace is None:
        return None

    choice = _select_chat_model(workspace, session)
    if choice is None:
        return None

    try:
        from cli.llm.providers import create_model_client
        from cli.workbench_app.orchestrator_runtime import build_workbench_runtime

        model_kwargs: dict[str, Any] = {
            "model": choice.model,
            "echo_fallback_on_missing_keys": False,
        }
        if choice.api_key is not None:
            model_kwargs["api_key"] = choice.api_key
        model = create_model_client(**model_kwargs)
        return build_workbench_runtime(
            workspace_root=Path(workspace.root) if hasattr(workspace, "root") else Path.cwd(),
            model=model,
            session=session,
            session_store=store,
            active_model=choice.active_model,
            echo=echo,
        )
    except Exception:  # pragma: no cover — chat setup must never crash boot
        return None


def _select_chat_model(
    workspace: Any | None,
    session: "Session | None",
) -> _ChatModelChoice | None:
    """Return the first usable chat model for the active Workbench session."""
    import os

    root: Path | None = None
    if workspace is not None:
        root = Path(getattr(workspace, "root", Path.cwd()))
        try:
            from cli.workspace_env import load_workspace_env

            load_workspace_env(root)
        except Exception:
            pass

    env_model = os.environ.get("AGENTLAB_MODEL")
    if env_model:
        model_name = _strip_provider_prefix(env_model)
        if _model_name_can_run_without_echo(model_name):
            return _ChatModelChoice(model=model_name, active_model=model_name)
        return None

    if root is None:
        return None

    try:
        from cli.model import list_available_models

        available = list_available_models(root)
    except Exception:
        return None

    override = _session_model_override(session)
    if override:
        matched = _match_available_model(available, override)
        if matched is not None:
            return _choice_from_model_item(matched)
        model_name = _strip_provider_prefix(override)
        if _model_name_can_run_without_echo(model_name):
            return _ChatModelChoice(model=model_name, active_model=model_name)
        return None

    for item in available:
        choice = _choice_from_model_item(item)
        if choice is not None:
            return choice
    return None


def _session_model_override(session: "Session | None") -> str | None:
    """Return the session-local model override set by ``/model``."""
    overrides = getattr(session, "settings_overrides", None) if session else None
    if not isinstance(overrides, dict):
        return None
    value = overrides.get("model")
    return str(value) if value else None


def _match_available_model(
    available: list[dict[str, Any]],
    requested: str,
) -> dict[str, Any] | None:
    """Find a model by full provider key or bare model name."""
    normalized = requested.strip().lower()
    for item in available:
        if str(item.get("key", "")).lower() == normalized:
            return item
    matches = [
        item
        for item in available
        if str(item.get("model", "")).lower() == normalized
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def _choice_from_model_item(item: dict[str, Any]) -> _ChatModelChoice | None:
    """Return a chat choice when an agentlab.yaml model can run now."""
    import os

    env_name = str(item.get("api_key_env") or "").strip()
    api_key = os.environ.get(env_name) if env_name else None
    if env_name and not api_key:
        return None
    model_name = str(item.get("model") or "").strip()
    if not model_name or not _model_name_can_run_without_echo(
        model_name,
        api_key=api_key,
    ):
        return None
    return _ChatModelChoice(model=model_name, active_model=model_name, api_key=api_key)


def _model_name_can_run_without_echo(
    model_name: str,
    *,
    api_key: str | None = None,
) -> bool:
    """Return whether the provider adapter can answer without echo fallback."""
    import os

    try:
        from cli.llm.providers import resolve_provider

        provider = resolve_provider(model_name)
    except Exception:
        return False
    if provider == "anthropic":
        return bool(api_key or os.environ.get("ANTHROPIC_API_KEY"))
    if provider == "openai":
        return bool(api_key or os.environ.get("OPENAI_API_KEY"))
    if provider == "echo":
        return bool(os.environ.get("AGENTLAB_ALLOW_ECHO_CHAT"))
    # Gemini is intentionally false until the adapter exists; otherwise a
    # configured GOOGLE_API_KEY would create a runtime that can only fail at
    # turn time.
    return False


def _strip_provider_prefix(model: str) -> str:
    """Accept either ``provider:model`` keys or bare model names."""
    cleaned = model.strip()
    if ":" not in cleaned:
        return cleaned
    _provider, model_name = cleaned.split(":", 1)
    return model_name.strip()


def uuid_hex() -> str:
    """Generate a short id for ephemeral sessions."""
    import uuid

    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# Orchestrator helpers (Phase C live wiring)
# ---------------------------------------------------------------------------


def _resolve_orchestrator(bundle: Any | None) -> Any | None:
    """Return the :class:`LLMOrchestrator` from either a bare orchestrator
    or a :class:`WorkbenchRuntime` bundle. ``None`` means "no LLM path"."""
    if bundle is None:
        return None
    if hasattr(bundle, "orchestrator"):
        return bundle.orchestrator
    if hasattr(bundle, "run_turn"):
        return bundle
    return None


def _publish_orchestrator_meta(ctx: "SlashContext", bundle: Any) -> None:
    """Thread every subsystem from the :class:`WorkbenchRuntime` into
    ``SlashContext.meta`` so slash handlers (``/plan``, ``/skill``,
    ``/transcript-*``, ``/background``, ``/usage``) see the live state.

    Accepts both a bare orchestrator (limited publication — just the
    active_model) and a full runtime bundle (every subsystem). The two
    paths share the same helper so callers never need to remember which
    keys land where."""
    if bundle is None or ctx is None:
        return

    from cli.tools.exit_plan_mode import PLAN_WORKFLOW_KEY
    from cli.tools.skill_tool import SKILL_REGISTRY_KEY
    from cli.user_skills.slash import SKILL_REGISTRY_META_KEY as SKILL_SLASH_KEY
    from cli.workbench_app.background_slash import (
        BACKGROUND_REGISTRY_META_KEY,
    )
    from cli.workbench_app.plan_slash import PLAN_WORKFLOW_META_KEY
    from cli.workbench_app.transcript_rewind_slash import (
        TRANSCRIPT_REWIND_MANAGER_META_KEY,
    )

    # Both ``WorkbenchRuntime`` and a future bundle with plain fields
    # expose attributes by the same names — we check with getattr so
    # either shape works.
    plan_workflow = getattr(bundle, "plan_workflow", None)
    skill_registry = getattr(bundle, "skill_registry", None)
    transcript_rewind = getattr(bundle, "transcript_rewind", None)
    background_tasks = getattr(bundle, "background_tasks", None)
    hook_registry = getattr(bundle, "hook_registry", None)

    if plan_workflow is not None:
        ctx.meta[PLAN_WORKFLOW_META_KEY] = plan_workflow
        ctx.meta[PLAN_WORKFLOW_KEY] = plan_workflow
    if skill_registry is not None:
        # Slash dispatch reads under one key, SkillTool reads under
        # another — both point at the same registry instance.
        ctx.meta[SKILL_SLASH_KEY] = skill_registry
        ctx.meta[SKILL_REGISTRY_KEY] = skill_registry
    if transcript_rewind is not None:
        ctx.meta[TRANSCRIPT_REWIND_MANAGER_META_KEY] = transcript_rewind
    if background_tasks is not None:
        ctx.meta[BACKGROUND_REGISTRY_META_KEY] = background_tasks
    if hook_registry is not None:
        ctx.meta["hook_registry"] = hook_registry

    orchestrator = _resolve_orchestrator(bundle)
    if orchestrator is not None:
        # active_model feeds /usage's per-model context-window lookup.
        seed = getattr(orchestrator, "_tool_extra_seed", None)
        if isinstance(seed, dict) and "active_model" in seed:
            ctx.meta["active_model"] = seed["active_model"]


def _run_orchestrator_turn(
    *,
    orchestrator: Any,
    ctx: "SlashContext | None",
    line: str,
    echo: EchoFn,
    bridge: Any | None = None,
    session: Any | None = None,
    model_id: str | None = None,
) -> None:
    """Route one natural-language user turn through :meth:`run_turn`.

    The orchestrator owns its own echo sink (set at construction) but the
    REPL wants streamed output to land in its live transcript. We rebind
    :attr:`LLMOrchestrator.echo` to the REPL's sink for the duration of
    the turn — callers that injected their own sink keep it for
    reporting outside the orchestrator but see every live text delta in
    the REPL. The rebind is scoped so a failure inside run_turn still
    restores the prior echo, which matters when the orchestrator lives
    across multiple REPL instances (tests reuse it)."""
    previous_echo = getattr(orchestrator, "echo", None)
    try:
        orchestrator.echo = echo
    except Exception:  # pragma: no cover — orchestrator without echo attribute
        previous_echo = None

    if bridge is not None:
        try:
            bridge.record_user_turn(line)
        except Exception:  # pragma: no cover — bridge persistence is best-effort
            pass

    try:
        result = orchestrator.run_turn(line)
    except Exception as exc:  # pragma: no cover — defensive REPL
        echo(theme.warning(f"  (orchestrator turn failed: {exc})"))
        return
    finally:
        if previous_echo is not None:
            try:
                orchestrator.echo = previous_echo
            except Exception:  # pragma: no cover
                pass

    if bridge is not None and result is not None:
        try:
            bridge.record_assistant_turn(result)
        except Exception:  # pragma: no cover — bridge persistence is best-effort
            pass

    # R7.C.3 — advance the workbench cost ticker. Wrapped in try/except
    # because cost reporting must NEVER block the conversation: an unknown
    # model, missing capability, or write failure on the session file is a
    # diagnostics issue, not a UX-blocking error.
    if result is not None and session is not None and model_id is not None:
        try:
            from cli.workbench_app.cost_calculator import compute_turn_cost

            delta = compute_turn_cost(getattr(result, "usage", None), model_id)
            if delta > 0:
                session.increment_cost(delta)
        except Exception:  # pragma: no cover — cost reporting must never block UX
            pass

    if ctx is None or result is None:
        return

    # Update status counters so the footer reflects what just happened.
    tool_executions = list(getattr(result, "tool_executions", []) or [])
    ctx.meta["active_tasks"] = len(tool_executions)
    stop_reason = getattr(result, "stop_reason", None)
    if stop_reason and stop_reason != "end_turn":
        echo(theme.meta(f"  (stop: {stop_reason})"))


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
