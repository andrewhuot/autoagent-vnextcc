"""Slash-command dispatch for the workbench app.

T05 extracts the handler set that previously lived inline in
``cli/repl.py`` into a typed registry built on the three-tier taxonomy in
:mod:`cli.workbench_app.commands`. The handlers here are thin shims:
they format workspace/session state or delegate to existing Click
subcommands via :class:`click.testing.CliRunner` so no business logic is
duplicated.

T05b adds Claude Code's ``onDone(result, display, shouldQuery, metaMessages)``
protocol. Handlers return an :class:`OnDoneResult` built via
:func:`cli.workbench_app.commands.on_done`; :func:`dispatch` routes ``display``
to the transcript (``skip`` → no echo, ``system`` → dim meta line,
``user`` → normal line), echoes ``meta_messages`` as dim lines, and surfaces
``should_query`` on :class:`DispatchResult` so the enclosing loop can feed the
output back into the model on the next turn. Bare ``str`` and ``None`` returns
remain valid sugar for ``on_done(result=value)`` and ``on_done(display="skip")``.

Exit is signalled via :meth:`SlashContext.request_exit` rather than a sentinel
value so that handler return types stay aligned with
:data:`cli.workbench_app.commands.LocalHandler`.
"""

from __future__ import annotations

import difflib
import shlex
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Sequence

import click

from cli.sessions import Session, SessionStore
from cli.workbench_app import theme
from cli.workbench_app.commands import (
    CommandRegistry,
    DisplayMode,
    LocalCommand,
    LocalHandlerReturn,
    LocalJSXCommand,
    OnDoneResult,
    SlashCommand,
    on_done,
)

from cli.workbench_app.cancellation import CancellationToken
from cli.workbench_app.help_text import render_shortcuts_help

if TYPE_CHECKING:
    from cli.workbench_app.transcript import Transcript

EchoFn = Callable[[str], None]
"""Writes one line to the transcript — defaults to :func:`click.echo`."""

ClickInvoker = Callable[[str], str]
"""Runs a CLI command path (e.g. ``"status"``) and returns its captured output."""


@dataclass
class SlashContext:
    """Execution context handed to every slash handler.

    Bundles the per-session state a handler may need so the handler
    signature stays uniform. ``echo`` and ``click_invoker`` are injectable
    so tests can drive dispatch without a workspace or a real Click tree.
    """

    workspace: Any | None = None
    session: Session | None = None
    session_store: SessionStore | None = None
    echo: EchoFn = click.echo
    click_invoker: ClickInvoker | None = None
    registry: CommandRegistry | None = None
    transcript: "Transcript | None" = None
    cancellation: CancellationToken | None = None
    coordinator_session: Any | None = None
    exit_requested: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    def request_exit(self) -> None:
        """Ask the enclosing loop to terminate after this dispatch returns."""
        self.exit_requested = True


@dataclass(frozen=True)
class DispatchResult:
    """Outcome of a single slash-command dispatch.

    The ``output`` field carries the rendered result (after display-mode
    styling — i.e. what was echoed). ``handled`` is ``False`` when the input
    does not start with ``/`` or no matching command was found — the caller
    decides whether to route the line as free text instead.

    T05b additions:

    - ``display``        — the :data:`DisplayMode` the handler selected (or
      ``"user"`` / ``"skip"`` inferred from a bare ``str`` / ``None`` return).
    - ``should_query``   — when ``True``, the enclosing loop should feed the
      raw result back into the model as a new user turn.
    - ``meta_messages``  — additional dim lines the handler asked to surface
      alongside the result. Already echoed by :func:`dispatch`; retained so
      tests and future session logging can inspect them.
    - ``raw_result``     — the ``result`` field on the handler's
      :class:`OnDoneResult`, unmodified by display styling. Useful when the
      caller needs to re-render or archive the value.
    """

    handled: bool
    command: SlashCommand | None = None
    output: str | None = None
    exit: bool = False
    error: str | None = None
    display: DisplayMode = "user"
    should_query: bool = False
    meta_messages: tuple[str, ...] = ()
    raw_result: str | None = None
    next_input: str | None = None
    submit_next_input: bool = False


class UnknownSlashCommandError(KeyError):
    """Raised internally when an unknown ``/command`` is dispatched."""


# ---------------------------------------------------------------------------
# Click-invoker helper — isolated so tests can substitute a fake.
# ---------------------------------------------------------------------------


def _default_click_invoker(command_path: str) -> str:
    """Run a command against the real root CLI and return captured output."""
    from click.testing import CliRunner

    from runner import cli as root_cli

    try:
        runner = CliRunner(mix_stderr=False)
    except TypeError:  # Older Click versions without mix_stderr.
        runner = CliRunner()
    result = runner.invoke(
        root_cli, shlex.split(command_path), catch_exceptions=False
    )
    return result.output.rstrip() if result.output else ""


def _record_command(ctx: SlashContext, raw_line: str) -> None:
    """Best-effort append of ``raw_line`` to the session command history.

    No-op when either the session or the store is unbound. Failures from the
    store are swallowed so a flaky filesystem can't take down the loop.
    """
    store = ctx.session_store
    session = ctx.session
    if store is None or session is None:
        return
    command = raw_line.strip()
    if not command:
        return
    try:
        store.append_command(session, command)
    except Exception:  # pragma: no cover — defensive; best-effort persistence
        pass


def _run_click(ctx: SlashContext, command_path: str) -> str:
    """Run a click subcommand via the configured invoker, surfacing errors inline.

    Exceptions are surfaced as transcript text (not a crash) but tagged with
    their type so CI scripts parsing output can distinguish "command not
    found" / "usage error" / internal crash instead of one generic string.
    A debug-level log captures the full traceback for local diagnosis.
    """
    import logging

    invoker = ctx.click_invoker or _default_click_invoker
    try:
        return invoker(command_path)
    except SystemExit:
        # Click raises SystemExit on --help/ExitError; propagate so the
        # harness can honor the exit request rather than masquerading it
        # as a runtime error.
        raise
    except Exception as exc:
        logging.getLogger(__name__).debug(
            "slash _run_click failed", exc_info=exc, extra={"command_path": command_path},
        )
        return f"  Error running '{command_path}': {type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# Handler implementations (ported from cli/repl.py::_handle_slash_command).
# ---------------------------------------------------------------------------


def _handle_help(ctx: SlashContext, *args: str) -> OnDoneResult:
    """Render source-grouped help or a detailed command card."""
    registry = ctx.registry
    if registry is None:
        return on_done("  /help unavailable: no command registry bound.")
    if args:
        target_name = args[0]
        command = registry.get(target_name)
        if command is None:
            return on_done(
                f"  No command named /{target_name.lstrip('/').lower()}.",
                display="system",
            )
        return on_done(_render_command_detail(command), display="user")

    lines = [theme.heading("\n  Slash Commands")]
    for source, label in _SOURCE_LABELS:
        commands = [
            command for command in registry.by_source(source) if not command.hidden
        ]
        if not commands:
            continue
        lines.append(theme.meta(f"  {label}"))
        for command in commands:
            hint = f" {command.argument_hint}" if command.argument_hint else ""
            aliases = _format_aliases(command.aliases)
            lines.append(
                f"    /{command.name:<12} {command.description}{hint}{aliases}"
            )
    lines.append("")
    lines.append("  Type /help <command> for details. Type ? for shortcuts.")
    return on_done("\n".join(lines), display="user")


def _render_command_detail(command: SlashCommand) -> str:
    """Render one command's metadata for `/help <command>`."""
    lines = [theme.heading(f"\n  /{command.name}")]
    lines.append(f"  {command.description}")
    if command.argument_hint:
        lines.append(f"  Arguments: {command.argument_hint}")
    if command.aliases:
        aliases = ", ".join("/" + alias for alias in command.aliases)
        lines.append(f"  Aliases: {aliases}")
    lines.append(f"  Kind: {command.kind}")
    lines.append(f"  Source: {command.source}")
    if command.when_to_use:
        lines.append(f"  When to use: {command.when_to_use}")
    if command.availability != "enabled":
        lines.append(f"  Availability: {command.availability}")
    if command.enabled_reason:
        lines.append(f"  Enabled reason: {command.enabled_reason}")
    if command.context != "inline":
        lines.append(f"  Context: {command.context}")
    if command.effort:
        lines.append(f"  Effort: {command.effort}")
    if command.allowed_tools:
        lines.append(f"  Allowed tools: {', '.join(command.allowed_tools)}")
    if command.paths:
        lines.append(f"  Paths: {', '.join(command.paths)}")
    if command.immediate:
        lines.append("  Runs immediately.")
    if command.sensitive:
        lines.append("  May touch sensitive workspace state.")
    lines.append("")
    return "\n".join(lines)


def _format_aliases(aliases: Sequence[str]) -> str:
    """Return a compact alias suffix for broad help rows."""
    if not aliases:
        return ""
    alias_text = ", ".join("/" + alias for alias in aliases)
    return "  " + theme.meta(f"(aliases: {alias_text})")


def _handle_exit(ctx: SlashContext, *_: str) -> str:
    ctx.request_exit()
    return "  Goodbye."


def _handle_status(ctx: SlashContext, *_: str) -> str:
    return _run_click(ctx, "status")


def _handle_memory(ctx: SlashContext, *_: str) -> str:
    return _run_click(ctx, "memory show")


def _handle_doctor(ctx: SlashContext, *_: str) -> str:
    return _run_click(ctx, "doctor")


def _handle_review(ctx: SlashContext, *_: str) -> str:
    return _run_click(ctx, "review")


def _handle_permissions(ctx: SlashContext, *args: str) -> str:
    """Delegate Workbench permission inspection and mode changes to the root CLI."""
    suffix = " " + shlex.join(args) if args else " show"
    return _run_click(ctx, "permissions" + suffix)


def _handle_mcp(ctx: SlashContext, *_: str) -> str:
    return _run_click(ctx, "mcp status")


def _handle_save(ctx: SlashContext, *args: str) -> str:
    """Materialize the active Workbench candidate.

    Thin delegator over ``agentlab workbench save``. Extra ``args`` are
    forwarded as CLI flags (``--project-id``, ``--category``, ``--dataset``,
    ``--split``, ``--generated-suite-id``) so users can steer save behaviour
    from the transcript without leaving the REPL.
    """
    suffix = (" " + shlex.join(args)) if args else ""
    return _run_click(ctx, "workbench save" + suffix)


def _handle_config(ctx: SlashContext, *_: str) -> str:
    workspace = ctx.workspace
    if workspace is None:
        return "  No workspace."
    active = workspace.resolve_active_config()
    if active is None:
        return "  No active config."
    summary = workspace.summarize_config(active.config)
    return (
        f"  Active config: v{active.version:03d} — {active.path}\n"
        f"  Summary: {summary}"
    )


def _handle_resume(ctx: SlashContext, *args: str) -> OnDoneResult:
    """Resume a prior session — swap ctx.session and rehydrate the transcript.

    Default: resume the most recently updated session on disk. An explicit
    ``<session_id>`` argument loads that specific session instead. The
    transcript (when bound) is cleared and repopulated from the loaded
    session's persisted entries; the store binding rolls over so new
    appends continue to write to the resumed session.
    """
    store = ctx.session_store
    current = ctx.session
    if store is None:
        return on_done(
            "  Sessions are not persisted — nothing to resume.", display="system"
        )

    requested_id = args[0] if args else None
    target: Session | None
    if requested_id is not None:
        target = store.get(requested_id)
        if target is None:
            return on_done(
                f"  No session with id {requested_id!r}.", display="system"
            )
    else:
        target = store.latest()

    if target is None or (current is not None and target.session_id == current.session_id):
        return on_done("  No previous session to resume.", display="system")

    ctx.session = target
    if ctx.transcript is not None:
        ctx.transcript.clear()
        ctx.transcript.restore_from_session(target)
        ctx.transcript.bind_session(target, store)

    meta: list[str] = [
        f"Session: {target.title or target.session_id} ({target.session_id})",
        f"Goal: {target.active_goal or '(none)'}",
        f"Entries restored: {len(target.transcript)}",
    ]
    return on_done(
        "  Resumed previous session.", display="system", meta_messages=meta
    )


def _handle_shortcuts(ctx: SlashContext, *_: str) -> OnDoneResult:
    """Show prompt/input shortcuts from the shared renderer used by bare `?`."""
    del ctx
    return on_done(render_shortcuts_help(), display="user")


def _handle_sessions(ctx: SlashContext, *args: str) -> OnDoneResult:
    """List recent persisted sessions with direct `/resume` hints."""
    store = ctx.session_store
    if store is None:
        return on_done(
            "  Sessions are not persisted in this Workbench launch.",
            display="system",
        )

    limit = 5
    if args:
        try:
            limit = int(args[0])
        except ValueError:
            return on_done(
                f"  Invalid session limit {args[0]!r}; use /sessions [count].",
                display="system",
            )
    limit = min(max(limit, 1), 20)

    try:
        sessions = store.list_sessions(limit=limit)
    except Exception as exc:
        return on_done(f"  Failed to list sessions: {exc}", display="system")
    if not sessions:
        return on_done("  No saved sessions.", display="system")

    now = time.time()
    current_id = ctx.session.session_id if ctx.session is not None else None
    lines = [theme.heading("\n  Recent Sessions")]
    for session in sessions:
        title = session.title or session.session_id
        age = _format_session_age(now - (session.updated_at or 0.0))
        marker = " (current)" if session.session_id == current_id else ""
        lines.append(
            f"    {session.session_id}  {title}  {theme.meta(age)}{marker}"
        )
    lines.append("")
    lines.append("  Use /resume <session_id> to restore a session.")
    return on_done("\n".join(lines), display="user")


def _format_session_age(seconds: float) -> str:
    """Render a compact age string for the `/sessions` listing."""
    seconds = max(0.0, seconds)
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)}d ago"


def _handle_compact(ctx: SlashContext, *_: str) -> str:
    workspace = ctx.workspace
    session = ctx.session
    if workspace is None:
        return "  No workspace — cannot save session summary."
    if session is None:
        return "  No active session to compact."

    memory_dir: Path = workspace.agentlab_dir / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    summary_path = memory_dir / "latest_session.md"

    started = time.strftime("%Y-%m-%d %H:%M", time.localtime(session.started_at))
    lines: list[str] = [
        f"# Session: {session.title}",
        f"ID: {session.session_id}",
        f"Started: {started}",
        f"Goal: {session.active_goal or '(none)'}",
        "",
        "## Commands",
    ]
    for command in session.command_history[-50:]:
        lines.append(f"- `{command}`")

    lines.append("")
    lines.append("## Transcript (last 20)")
    for entry in session.transcript[-20:]:
        lines.append(f"**{entry.role}**: {entry.content[:200]}")

    if session.pending_next_actions:
        lines.append("")
        lines.append("## Pending Next Actions")
        for action in session.pending_next_actions:
            lines.append(f"- {action}")

    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f"  Session summary saved to {summary_path}"


def _handle_cost(ctx: SlashContext, *_: str) -> OnDoneResult:
    """Show session cost summary when model/tool runners have recorded it."""
    cost = ctx.meta.get("cost", {})
    if not isinstance(cost, dict) or not cost:
        return on_done(
            "  No cost data recorded for this session.\n"
            "  (Cost tracking populates as model calls execute.)",
            display="user",
        )

    from cli.workbench_app.effort import format_elapsed

    parts: list[str] = [theme.heading("\n  Session Cost Summary")]
    if "total_cost_usd" in cost:
        parts.append(f"    Total cost:      {_format_cost_value(cost['total_cost_usd'])}")
    if "total_input_tokens" in cost:
        parts.append(f"    Input tokens:    {_format_count_value(cost['total_input_tokens'])}")
    if "total_output_tokens" in cost:
        parts.append(f"    Output tokens:   {_format_count_value(cost['total_output_tokens'])}")
    if "total_duration_ms" in cost:
        secs = _coerce_float(cost["total_duration_ms"]) / 1000.0
        parts.append(f"    Total duration:  {format_elapsed(secs)}")
    if "total_api_duration_ms" in cost:
        secs = _coerce_float(cost["total_api_duration_ms"]) / 1000.0
        parts.append(f"    API duration:    {format_elapsed(secs)}")
    parts.append("")
    return on_done("\n".join(parts), display="user")


def _coerce_float(value: Any) -> float:
    """Return a numeric metric value or raise a helpful error."""
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid cost metric {value!r}") from exc


def _format_cost_value(value: Any) -> str:
    """Format a USD value supplied by a model/cost runner."""
    return f"${_coerce_float(value):.4f}"


def _format_count_value(value: Any) -> str:
    """Format a token count supplied by a model/cost runner."""
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid token count {value!r}") from exc


def _handle_clear(ctx: SlashContext, *_: str) -> OnDoneResult:
    """Wipe the in-memory transcript without touching the active session.

    Mirrors Claude Code's ``/clear`` (reset the visible context while keeping
    the conversation file intact). Persisted session state is untouched — the
    caller can still ``/resume`` it or ``/compact`` it on demand.
    """
    transcript = ctx.transcript
    if transcript is None:
        return on_done(
            "  No transcript bound — nothing to clear.",
            display="system",
        )
    count = len(transcript)
    transcript.clear()
    noun = "entry" if count == 1 else "entries"
    meta = (f"Removed {count} {noun}; session kept.",)
    return on_done("  Transcript cleared.", display="system", meta_messages=meta)


def _handle_new(ctx: SlashContext, *args: str) -> OnDoneResult:
    """Start a fresh session, swap it onto the context, and clear the transcript.

    Optional positional args are joined as the new session title, matching the
    ``SessionStore.create(title=…)`` contract. The previous session is left on
    disk (not deleted); we only move the pointer on ``ctx.session``.
    """
    store = ctx.session_store
    if store is None:
        return on_done(
            "  Sessions are not persisted — cannot start a new one.",
            display="system",
        )
    title = " ".join(args).strip()
    try:
        session = store.create(title=title)
    except Exception as exc:  # Store failures shouldn't crash the loop.
        return on_done(f"  Failed to start new session: {exc}", display="system")

    previous = ctx.session
    ctx.session = session
    if ctx.transcript is not None:
        ctx.transcript.clear()

    meta: list[str] = []
    if previous is not None and previous.session_id != session.session_id:
        meta.append(f"Previous session: {previous.session_id}")
    meta.append(f"New session: {session.session_id}")
    if session.title:
        meta.append(f"Title: {session.title}")
    return on_done(
        "  Started new session.",
        display="system",
        meta_messages=meta,
    )


# ---------------------------------------------------------------------------
# Registry construction.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _BuiltinSpec:
    """Registration metadata for a built-in Workbench slash command."""

    name: str
    description: str
    handler: Callable[..., LocalHandlerReturn]
    argument_hint: str | None = None
    when_to_use: str | None = None
    aliases: tuple[str, ...] = ()
    immediate: bool = False
    sensitive: bool = False


_SOURCE_LABELS: tuple[tuple[str, str], ...] = (
    ("builtin", "Builtin Commands"),
    ("project", "Project Commands"),
    ("user", "User Commands"),
    ("plugin", "Plugin Commands"),
)


_BUILTIN_SPECS: tuple[_BuiltinSpec, ...] = (
    _BuiltinSpec(
        "help",
        "Show available slash commands",
        _handle_help,
        argument_hint="[command]",
        when_to_use="Use when you need command syntax, aliases, or source details.",
    ),
    _BuiltinSpec("status", "Show workspace status", _handle_status),
    _BuiltinSpec("config", "Show active config info", _handle_config),
    _BuiltinSpec("memory", "Show AGENTLAB.md contents", _handle_memory),
    _BuiltinSpec("doctor", "Run workspace diagnostics", _handle_doctor),
    _BuiltinSpec("review", "Show pending review cards", _handle_review),
    _BuiltinSpec(
        "permissions",
        "Show or set Workbench permission mode",
        _handle_permissions,
        argument_hint="[show|set <mode>]",
        when_to_use="Use to inspect or change whether tools ask before editing, deploying, or running commands.",
        sensitive=True,
    ),
    _BuiltinSpec("mcp", "Show MCP integration status", _handle_mcp),
    _BuiltinSpec(
        "save",
        "Materialize the active Workbench candidate",
        _handle_save,
        argument_hint="[--project-id ID] [--split NAME]",
        sensitive=True,
    ),
    _BuiltinSpec("cost", "Show session cost summary", _handle_cost),
    _BuiltinSpec(
        "compact",
        "Summarize session to .agentlab/memory/latest_session.md",
        _handle_compact,
        sensitive=True,
    ),
    _BuiltinSpec(
        "resume",
        "Resume the most recent session",
        _handle_resume,
        argument_hint="[session_id]",
        aliases=("r",),
        when_to_use="Use after restarting Workbench or switching back to prior work.",
    ),
    _BuiltinSpec(
        "sessions",
        "List recent Workbench sessions",
        _handle_sessions,
        argument_hint="[count]",
        aliases=("session", "history"),
    ),
    _BuiltinSpec(
        "shortcuts",
        "Show keyboard shortcuts",
        _handle_shortcuts,
        aliases=("?",),
    ),
    _BuiltinSpec("clear", "Wipe the transcript but keep the active session", _handle_clear),
    _BuiltinSpec(
        "new",
        "Start a fresh session (and clear the transcript)",
        _handle_new,
        argument_hint="[title]",
    ),
    _BuiltinSpec("exit", "Exit the shell", _handle_exit, aliases=("quit", "q")),
)


def build_builtin_registry(
    *, extra: Sequence[SlashCommand] = (), include_streaming: bool = True
) -> CommandRegistry:
    """Return a registry populated with the ported built-in commands.

    ``extra`` allows callers (and tests) to register additional commands
    during construction without needing a second ``.register`` pass.
    ``include_streaming`` is the historical flag name for workflow commands;
    when enabled, `/build`, `/eval`, `/optimize`, `/deploy`, and `/skills`
    register as coordinator-backed commands. Tests that want only core
    built-ins can disable it; production callers keep the default.
    """
    registry = CommandRegistry()
    for spec in _BUILTIN_SPECS:
        registry.register(
            LocalCommand(
                name=spec.name,
                description=spec.description,
                handler=spec.handler,
                source="builtin",
                aliases=spec.aliases,
                argument_hint=spec.argument_hint,
                when_to_use=spec.when_to_use,
                immediate=spec.immediate,
                sensitive=spec.sensitive,
            )
        )
    # ``/model`` is an inline built-in with a factory (injectable model
    # lister) — registered outside ``_BUILTIN_SPECS`` so tests that need a
    # stub lister can re-register via ``extra=``.
    from cli.workbench_app.model_slash import build_model_command
    from cli.workbench_app.coordinator_slash import (
        build_context_command,
        build_tasks_command,
    )
    from cli.workbench_app.checkpoint_slash import (
        build_checkpoint_command,
        build_checkpoints_command,
        build_rewind_command,
    )
    from cli.workbench_app.config_diff_slash import (
        build_accept_command,
        build_diff_command,
        build_reject_command,
    )
    from cli.workbench_app.plan_slash import all_plan_commands
    from cli.workbench_app.context_viz_slash import build_usage_command
    from cli.workbench_app.transcript_rewind_slash import all_transcript_rewind_commands
    from cli.user_skills.slash import all_skill_commands
    from cli.workbench_app.background_slash import all_background_commands
    from cli.workbench_app.init_slash import build_init_command
    from cli.workbench_app.theme_slash import build_theme_command
    from cli.workbench_app.output_style_slash import build_output_style_command

    registry.register(build_model_command())
    registry.register(build_tasks_command())
    registry.register(build_context_command())
    registry.register(build_checkpoint_command())
    registry.register(build_rewind_command())
    registry.register(build_checkpoints_command())
    registry.register(build_diff_command())
    registry.register(build_accept_command())
    registry.register(build_reject_command())
    registry.register(build_usage_command())
    for plan_command in all_plan_commands():
        registry.register(plan_command)
    for transcript_command in all_transcript_rewind_commands():
        registry.register(transcript_command)
    for skill_command in all_skill_commands():
        registry.register(skill_command)
    for background_command in all_background_commands():
        registry.register(background_command)
    registry.register(build_init_command())
    registry.register(build_theme_command())
    registry.register(build_output_style_command())
    if include_streaming:
        from cli.workbench_app.coordinator_slash import (
            build_coordinator_command,
            build_ship_command,
            build_skills_coordinator_command,
        )

        for intent in ("eval", "optimize", "build", "deploy"):
            registry.register(build_coordinator_command(intent))
        registry.register(build_ship_command())
        registry.register(build_skills_coordinator_command())
    for command in extra:
        registry.register(command)
    return registry


# ---------------------------------------------------------------------------
# Dispatch.
# ---------------------------------------------------------------------------


def parse_slash_line(line: str) -> tuple[str, list[str]] | None:
    """Split ``"/cmd a b"`` → ``("cmd", ["a", "b"])``; return ``None`` otherwise.

    Unbalanced quotes fall back to a whitespace split so the caller still
    sees a command name and can surface a useful error. Callers that want
    to warn the user should use :func:`_parse_slash_line_with_warning`.
    """
    parsed = _parse_slash_line_with_warning(line)
    if parsed is None:
        return None
    name, args, _warning = parsed
    return name, args


def _parse_slash_line_with_warning(
    line: str,
) -> tuple[str, list[str], str] | None:
    """Parser variant that also returns a quote-warning string (empty when OK)."""
    stripped = line.strip()
    if not stripped.startswith("/"):
        return None
    warning = ""
    try:
        tokens = shlex.split(stripped[1:])
    except ValueError as exc:
        tokens = stripped[1:].split()
        warning = f"unbalanced quotes ({exc}); falling back to whitespace split"
    if not tokens:
        return None
    return tokens[0].lower(), tokens[1:], warning


def dispatch(
    ctx: SlashContext,
    line: str,
    *,
    registry: CommandRegistry | None = None,
) -> DispatchResult:
    """Dispatch a single slash line against the registry.

    The ``registry`` arg overrides ``ctx.registry`` for the call but does
    not mutate the context — helpful when running one-off commands with a
    scoped registry (e.g. tests or nested screens).
    """
    active_registry = registry or ctx.registry
    parsed = _parse_slash_line_with_warning(line)
    if parsed is None:
        return DispatchResult(handled=False)
    name, args, quote_warning = parsed

    _record_command(ctx, line)

    if quote_warning:
        ctx.echo(f"  Warning: {quote_warning}")

    if active_registry is None:
        return DispatchResult(
            handled=True,
            error="no command registry bound",
        )

    # Bind the active registry onto ctx for the duration of this call so
    # handlers like /help can introspect it without the caller threading
    # it through. Restored on exit to avoid leaking scoped overrides.
    previous_registry = ctx.registry
    ctx.registry = active_registry
    try:
        command = active_registry.get(name)
        if command is None:
            message = _unknown_command_message(active_registry, name)
            ctx.echo(message)
            return DispatchResult(handled=True, output=message, error="unknown")

        if isinstance(command, LocalJSXCommand):
            return _dispatch_local_jsx(ctx, command, args)

        if not isinstance(command, LocalCommand):
            message = (
                f"  /{command.name} is a {command.kind} command; "
                "inline dispatch is not supported yet."
            )
            ctx.echo(message)
            return DispatchResult(
                handled=True, command=command, output=message, error="unsupported-kind"
            )

        handler = command.handler
        assert handler is not None  # Guaranteed by LocalCommand.__post_init__.
        try:
            output = handler(ctx, *args)
            normalized = _normalize_handler_return(output)
            rendered = _render_and_echo(ctx, normalized)
        except Exception as exc:  # Surface handler errors without crashing loop.
            message = f"  Error running /{command.name}: {exc}"
            ctx.echo(message)
            return DispatchResult(
                handled=True,
                command=command,
                output=message,
                error=str(exc),
                display="system",
                raw_result=message,
            )

        return DispatchResult(
            handled=True,
            command=command,
            output=rendered,
            exit=ctx.exit_requested,
            display=normalized.display,
            should_query=normalized.should_query,
            meta_messages=normalized.meta_messages,
            raw_result=normalized.result,
            next_input=normalized.next_input,
            submit_next_input=normalized.submit_next_input,
        )
    finally:
        ctx.registry = previous_registry


def _unknown_command_message(registry: CommandRegistry, name: str) -> str:
    """Build an unknown-command message with a close-match suggestion."""
    suggestions = _suggest_commands(registry, name)
    if not suggestions:
        return f"  Unknown command: /{name}.  Type /help for available commands."
    if len(suggestions) == 1:
        hint = f" Did you mean {suggestions[0]}?"
    else:
        hint = f" Did you mean {', '.join(suggestions[:-1])}, or {suggestions[-1]}?"
    return f"  Unknown command: /{name}.{hint} Type /help for available commands."


def _suggest_commands(registry: CommandRegistry, name: str) -> tuple[str, ...]:
    """Return up to three visible slash command suggestions for ``name``."""
    token = name.lstrip("/").lower()
    commands_by_token: dict[str, SlashCommand] = {}
    for command in registry.visible():
        commands_by_token[command.name] = command
        for alias in command.aliases:
            commands_by_token[alias] = command

    close_tokens = difflib.get_close_matches(
        token,
        list(commands_by_token),
        n=6,
        cutoff=0.55,
    )
    prefix = token[: max(1, min(3, len(token)))]
    prefix_matches = [
        command for command in registry.visible() if command.name.startswith(prefix)
    ]
    seen: set[str] = set()
    suggestions: list[str] = []
    for command in [*(commands_by_token[t] for t in close_tokens), *prefix_matches]:
        if command.name in seen:
            continue
        seen.add(command.name)
        suggestions.append(f"/{command.name}")
        if len(suggestions) >= 3:
            break
    return tuple(suggestions)


# ---------------------------------------------------------------------------
# LocalJSXCommand dispatch (T13) — hand over to a Screen, translate result.
# ---------------------------------------------------------------------------


def _dispatch_local_jsx(
    ctx: SlashContext,
    command: LocalJSXCommand,
    args: Sequence[str],
) -> "DispatchResult":
    """Run a ``local-jsx`` screen and fold its :class:`ScreenResult` into
    a :class:`DispatchResult`.

    The screen is constructed via ``command.screen_factory(ctx, *args)`` so
    factories can read workspace/session state off the context. ``meta_messages``
    on the screen result are echoed as dim lines (mirroring the
    :class:`OnDoneResult` routing in :func:`_render_and_echo`) so the screen
    can pass a summary back to the transcript without a second dispatch hop.
    ``action``/``value`` ride through on :class:`DispatchResult` so callers
    that want to react to a selected skill id / session id can.
    """
    factory = command.screen_factory
    assert factory is not None  # LocalJSXCommand.__post_init__ guarantees this.
    try:
        screen = factory(ctx, *args)
        screen_result = screen.run()
    except Exception as exc:  # Keep the loop alive on screen failures.
        message = f"  Error running /{command.name}: {exc}"
        ctx.echo(message)
        return DispatchResult(
            handled=True,
            command=command,
            output=message,
            error=str(exc),
            display="system",
            raw_result=message,
        )

    meta = tuple(getattr(screen_result, "meta_messages", ()) or ())
    for line in meta:
        ctx.echo(theme.meta(line))

    value = getattr(screen_result, "value", None)
    raw = value if isinstance(value, str) else None
    return DispatchResult(
        handled=True,
        command=command,
        output=None,
        exit=ctx.exit_requested,
        display="system",
        meta_messages=meta,
        raw_result=raw,
    )


# ---------------------------------------------------------------------------
# onDone normalization + display routing (T05b).
# ---------------------------------------------------------------------------


def _normalize_handler_return(value: LocalHandlerReturn) -> OnDoneResult:
    """Coerce a handler return into an :class:`OnDoneResult`.

    Bare strings map to ``display="user"`` so existing handlers that returned
    plain text keep rendering identically. ``None`` maps to ``display="skip"``
    (no transcript output). Anything else must already be an
    :class:`OnDoneResult`.
    """
    if isinstance(value, OnDoneResult):
        return value
    if value is None:
        return on_done(display="skip")
    if isinstance(value, str):
        return on_done(result=value, display="user")
    raise TypeError(
        f"slash handler returned unsupported type {type(value).__name__!r}; "
        "expected str | None | OnDoneResult"
    )


def _render_and_echo(ctx: SlashContext, result: OnDoneResult) -> str | None:
    """Echo ``result`` according to its ``display`` mode and return the line.

    Returns whatever was written to the transcript (post-styling) or ``None``
    when ``display="skip"`` / the result is empty. ``meta_messages`` are
    always echoed as dim lines after the main output, regardless of mode.
    """
    rendered: str | None = None
    text = result.result
    if result.display == "skip" or text is None:
        rendered = None
    elif result.display == "system":
        rendered = theme.meta(text)
        ctx.echo(rendered)
    else:  # "user"
        rendered = text
        ctx.echo(rendered)

    for meta in result.meta_messages:
        ctx.echo(theme.meta(meta))

    return rendered


__all__ = [
    "ClickInvoker",
    "DispatchResult",
    "EchoFn",
    "OnDoneResult",
    "SlashContext",
    "UnknownSlashCommandError",
    "build_builtin_registry",
    "dispatch",
    "on_done",
    "parse_slash_line",
]
