"""Entry point for the Claude-Code-style workbench REPL.

T04 started as a banner/status/input echo-only stub. This module now wires
the slash-command registry (T05) into the loop so ``/help``, ``/status``,
``/build`` etc. dispatch real handlers instead of echoing the raw line —
and routes natural-language turns into the builder coordinator runtime.

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

from cli.branding import get_agentlab_version, render_startup_banner
from cli.permissions import DEFAULT_PERMISSION_MODE, PermissionManager
from cli.terminal_renderer import render_box, terminal_width
from cli.workbench_app import theme
from cli.workbench_app.cancellation import CancellationToken
from cli.workbench_app.help_text import render_shortcuts_help
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
EXIT_TOKENS = frozenset({"/exit", "/quit", ":q", "exit", "quit"})
WORKFLOW_COMMANDS = frozenset({"build", "eval", "optimize", "deploy", "skills"})
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


def _render_banner(echo: EchoFn, workspace: Any | None) -> None:
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
    status = build_status_line(workspace, color=False)
    body_lines: list[str] = [
        theme.accent(f"✻ Welcome to AgentLab Workbench  v{version}"),
        "",
        theme.meta(f"cwd: {cwd}"),
        theme.meta(f"status: {status}"),
        "",
        theme.meta(f"{mode_label} permissions on · ? for shortcuts · / for commands"),
        theme.meta("Type /help for commands, /exit to leave."),
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

    active_agent_runtime = agent_runtime
    if active_agent_runtime is None and workspace is not None:
        try:
            from cli.workbench_app.runtime import build_default_agent_runtime

            active_agent_runtime = build_default_agent_runtime(workspace)
        except Exception:  # pragma: no cover - defensive startup path
            active_agent_runtime = None
    if ctx is not None and active_agent_runtime is not None:
        ctx.meta["agent_runtime"] = active_agent_runtime
        ctx.coordinator_session = getattr(active_agent_runtime, "coordinator_session", None)

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

        if line == "?":
            out(render_shortcuts_help())
            _render_turn_footer(
                out,
                workspace,
                mode_override=getattr(prompt_state, "mode", None),
                active_shells=_meta_int(ctx, "active_shells"),
                active_tasks=_meta_int(ctx, "active_tasks"),
            )
            continue

        # `!cmd` — shell-mode passthrough, gated by permission mode.
        if line.startswith("!"):
            current_mode = (
                getattr(prompt_state, "mode", None)
                or _permission_mode_for_workspace(workspace)
            )
            _run_shell_turn(
                ctx=ctx,
                workspace=workspace,
                line=line,
                permission_mode=current_mode,
                echo=out,
                reader=reader,
            )
            _render_turn_footer(
                out,
                workspace,
                mode_override=getattr(prompt_state, "mode", None),
                active_shells=_meta_int(ctx, "active_shells"),
                active_tasks=_meta_int(ctx, "active_tasks"),
            )
            continue

        # `&cmd` — dispatch the remainder as a background coordinator turn.
        if line.startswith("&"):
            _run_background_turn(
                runtime=active_agent_runtime,
                ctx=ctx,
                line=line[1:].strip(),
                echo=out,
            )
            _render_turn_footer(
                out,
                workspace,
                mode_override=getattr(prompt_state, "mode", None),
                active_shells=_meta_int(ctx, "active_shells"),
                active_tasks=_meta_int(ctx, "active_tasks"),
            )
            continue

        # Route ``/command`` input through the slash registry when one is
        # bound. Non-slash input uses the coordinator runtime when available;
        # the echo fallback remains only for tests/embedders without a runtime.
        handled_as_slash = False
        if ctx is not None and line.startswith("/"):
            from cli.workbench_app.slash import dispatch, parse_slash_line

            parsed = parse_slash_line(line)
            command_name = parsed[0] if parsed else ""
            current_mode = (
                getattr(prompt_state, "mode", None)
                or _permission_mode_for_workspace(workspace)
            )
            if (
                active_agent_runtime is not None
                and command_name in WORKFLOW_COMMANDS
                and _should_gate_with_plan(ctx, current_mode)
            ):
                args = parsed[1] if parsed else []
                _run_plan_gated_turn(
                    runtime=active_agent_runtime,
                    ctx=ctx,
                    line=" ".join(args).strip() or _default_workflow_message(command_name),
                    echo=out,
                    reader=reader,
                    command_intent=command_name,
                )
                handled_as_slash = True
            else:
                result = dispatch(ctx, line)
                if result.handled:
                    if ctx.exit_requested:
                        exited_via = "/exit"
                        break
                    _run_follow_up_turns(
                        runtime=active_agent_runtime,
                        ctx=ctx,
                        result=result,
                        echo=out,
                    )
                    handled_as_slash = True
            if ctx.exit_requested:
                exited_via = "/exit"
                break

        if not handled_as_slash:
            _persist_user_turn(
                ctx=ctx,
                session_store=session_store,
                session=session,
                line=line,
            )
            if active_agent_runtime is not None:
                current_mode = (
                    getattr(prompt_state, "mode", None)
                    or _permission_mode_for_workspace(workspace)
                )
                if _should_gate_with_plan(ctx, current_mode):
                    _run_plan_gated_turn(
                        runtime=active_agent_runtime,
                        ctx=ctx,
                        line=line,
                        echo=out,
                        reader=reader,
                    )
                else:
                    _run_agent_turn(
                        runtime=active_agent_runtime,
                        ctx=ctx,
                        line=line,
                        echo=out,
                    )
            else:
                out(theme.user(f"  AgentLab received: {line}", bold=False))

        _render_turn_footer(
            out,
            workspace,
            mode_override=getattr(prompt_state, "mode", None),
            active_shells=_meta_int(ctx, "active_shells"),
            active_tasks=_meta_int(ctx, "active_tasks"),
        )

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

    The live echo path prints each worker event with an ``[Ns]`` elapsed
    prefix. The batched transcript also includes a ``Coordinator plan X
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


def _default_workflow_message(command_name: str) -> str:
    """Return a useful prompt when a workflow slash command has no args."""
    defaults = {
        "build": "Build or refine the active agent.",
        "eval": "Evaluate the active agent candidate and summarize failures.",
        "optimize": "Optimize the agent from the latest eval evidence.",
        "deploy": "Prepare a canary deployment and rollback plan.",
        "skills": "Recommend build-time skills that would improve this agent.",
    }
    return defaults.get(command_name, "Continue the agent build.")


def _run_follow_up_turns(
    *,
    runtime: Any | None,
    ctx: "SlashContext | None",
    result: Any,
    echo: EchoFn,
) -> None:
    """Process command-requested follow-up prompts through the coordinator."""
    if runtime is None:
        return
    if getattr(result, "submit_next_input", False) and getattr(result, "next_input", None):
        _run_agent_turn(
            runtime=runtime,
            ctx=ctx,
            line=str(result.next_input),
            echo=echo,
        )
        return
    if getattr(result, "should_query", False) and getattr(result, "raw_result", None):
        _run_agent_turn(
            runtime=runtime,
            ctx=ctx,
            line=str(result.raw_result),
            echo=echo,
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
    slash-command completer, a ``╭─╮ / ╰─╯`` border around the input,
    and a shift+tab binding that cycles the permission mode. Callers
    supplying ``input_provider`` (tests, piped stdin) skip this wiring.
    """
    import os
    import sys

    from cli.sessions import Session, SessionStore
    from cli.workbench_app.slash import SlashContext, build_builtin_registry

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
