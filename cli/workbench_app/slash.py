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
import os
import shlex
import subprocess
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
    from cli.memory.retrieval import RetrievalResult
    from cli.workbench_app.spinner import StreamingSpinner
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
    # P2.T9: callback fired by /uncompact with the restored TurnMessage list.
    # The orchestrator wires this in P2.orch; until then it defaults to None so
    # every existing construction path stays unchanged and the handler is a
    # no-op on the in-memory context.
    uncompact_callback: Callable[[list], None] | None = None
    # P2.T9: last RetrievalResult the orchestrator attached for /memory-debug.
    # Typed ``Any`` here to avoid a runtime import cycle with cli.memory; the
    # real type is :class:`cli.memory.retrieval.RetrievalResult` (see
    # TYPE_CHECKING import above).
    memory_last_retrieval: Any | None = None

    def request_exit(self) -> None:
        """Ask the enclosing loop to terminate after this dispatch returns."""
        self.exit_requested = True

    def spinner(
        self,
        phase: str,
        *,
        model: str | None = None,
    ) -> "StreamingSpinner":
        """Build a :class:`StreamingSpinner` bound to this context's echo sink.

        ``model`` is optional today; the Chunk-4 provider-visibility work
        will introspect :mod:`optimizer.providers` and wire a default when
        the caller leaves it ``None``. Until then, the caller supplies the
        display string. The fallback echo is always ``ctx.echo`` so
        non-TTY runs (tests, pipes) still route transcript lines through
        the transcript / capture rather than bare ``click.echo``.
        """
        from cli.workbench_app.spinner import StreamingSpinner

        model_label = model
        if model_label is None:
            model_label = self.meta.get("provider_model") if isinstance(self.meta, dict) else None
        return StreamingSpinner(
            phase,
            model=model_label,
            echo=self.echo,
        )


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
    """Render categorized help, a filtered search, or a detailed command card.

    Behaviour ladder:

    * ``/help`` with no argument — category-grouped table of every visible
      command, with a footer pointing at the discoverability affordances.
    * ``/help <command>`` where ``<command>`` is an exact name or alias — the
      detail card (unchanged).
    * ``/help <query>`` — fuzzy filter across name, aliases, description, and
      ``when_to_use``. Returns the same category-grouped table narrowed to the
      matches, or a "no matches" hint.
    """
    registry = ctx.registry
    if registry is None:
        return on_done("  /help unavailable: no command registry bound.")
    if args:
        target = args[0]
        # Exact / alias lookup first so `/help resume` still goes to the card.
        command = registry.get(target)
        if command is not None:
            return on_done(_render_command_detail(command), display="user")
        # Otherwise treat the whole argv as a free-text filter.
        query = " ".join(args).strip()
        matches = _filter_commands(registry, query)
        if not matches:
            return on_done(
                f"  No commands matched {query!r}. Try /help on its own, "
                "or /find to search sessions and memories.",
                display="system",
            )
        return on_done(
            _render_help_table(matches, header=f"Matching {query!r}"),
            display="user",
        )

    commands = [command for command in registry.visible()]
    return on_done(_render_help_table(commands, header="Slash Commands"), display="user")


def _render_help_table(
    commands: Sequence[SlashCommand],
    *,
    header: str,
) -> str:
    """Render ``commands`` as a Claude-Code-style three-column help table.

    Commands are grouped by source first (builtin / project / user / plugin)
    so custom extensions stay visually separated from the core surface, then
    by category inside each source so long lists (like ``builtin``) stay
    scannable. The category order matches :data:`_CATEGORY_ORDER` so the
    layout is stable across runs.
    """
    lines: list[str] = [theme.heading(f"\n  {header}")]
    by_source: dict[str, list[SlashCommand]] = {}
    for command in commands:
        by_source.setdefault(command.source, []).append(command)

    rendered_any = False
    for source, label in _SOURCE_LABELS:
        bucket = by_source.get(source)
        if not bucket:
            continue
        rendered_any = True
        lines.append("")
        lines.append(theme.meta(f"  {label}"))

        # Sort into categories so builtin's long list splits into clearer
        # sections — Session / Workflow / Memory / Diagnostics / …
        name_width = max(len(f"/{command.name}") for command in bucket)
        by_category: dict[str, list[SlashCommand]] = {}
        for command in bucket:
            by_category.setdefault(
                _category_for(command), []
            ).append(command)

        ordered = [c for c in _CATEGORY_ORDER if c in by_category] + [
            c for c in sorted(by_category) if c not in _CATEGORY_ORDER
        ]
        for category in ordered:
            category_cmds = sorted(by_category[category], key=lambda c: c.name)
            lines.append(theme.meta(f"    {category}"))
            for command in category_cmds:
                lines.append(_render_help_row(command, name_width=name_width))

    if not rendered_any:
        lines.append("")
        lines.append(theme.meta("  (no matches)"))
    lines.append("")
    lines.append(
        "  Type /help <command> for details, /help <query> to filter, "
        "? for shortcuts."
    )
    return "\n".join(lines)


def _render_help_row(command: SlashCommand, *, name_width: int) -> str:
    """Render one command row so the name / description / hint columns align."""
    name_cell = f"/{command.name}".ljust(name_width)
    hint = (
        f"  {theme.meta(command.argument_hint)}"
        if command.argument_hint
        else ""
    )
    aliases = _format_aliases(command.aliases)
    return f"      {name_cell}  {command.description}{hint}{aliases}"


def _filter_commands(
    registry: CommandRegistry, query: str
) -> list[SlashCommand]:
    """Return every visible command matching ``query`` (fuzzy, case-insensitive).

    Scoring prefers:

    1. Exact substring hits in name/alias (very common for re-typing a half-
       remembered command).
    2. Substring hits in the description / ``when_to_use`` help text.
    3. ``difflib`` close-match on the command name as a last resort so
       typos still surface something useful.

    The ordering is stable: matches with equal score are returned in the
    registry's natural alphabetical order so users building muscle memory
    always see the same list for the same query.
    """
    token = query.strip().lower()
    if not token:
        return list(registry.visible())

    scored: list[tuple[int, str, SlashCommand]] = []
    names = [command.name for command in registry.visible()]
    close = set(difflib.get_close_matches(token, names, n=8, cutoff=0.55))

    for command in registry.visible():
        name = command.name.lower()
        alias_hits = any(token in alias.lower() for alias in command.aliases)
        description = (command.description or "").lower()
        guidance = (command.when_to_use or "").lower()
        score = 0
        if token == name:
            score = 100
        elif name.startswith(token):
            score = 80
        elif token in name:
            score = 60
        elif alias_hits:
            score = 55
        elif token in description:
            score = 40
        elif token in guidance:
            score = 30
        elif command.name in close:
            score = 20
        if score > 0:
            scored.append((score, command.name, command))

    scored.sort(key=lambda row: (-row[0], row[1]))
    return [command for _score, _name, command in scored]


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


def _handle_uncompact(ctx: SlashContext, *_: str) -> str:
    """Restore the most recent compacted range from the session's archive.

    Looks up ``<workspace>/.agentlab/compact_archive`` for the active
    session, picks the most recent ``(start, end)`` range, loads its
    :class:`TurnMessage` list, and (when wired) hands them to
    ``ctx.uncompact_callback`` so the orchestrator can splice them back
    into the live transcript. Until P2.orch lands the callback is ``None``
    and the handler still reports what would have been restored — that
    way users can audit the archive before the orchestrator integration
    goes live.
    """
    from cli.llm.compact_archive import CompactArchive

    workspace = ctx.workspace
    session = ctx.session
    if workspace is None:
        return "  No workspace — /uncompact unavailable."
    if session is None:
        return "  No active session to uncompact."

    # Archive root mirrors the location the orchestrator writes to: a
    # sibling of the memory dir under .agentlab. Session isolation is
    # baked into CompactArchive via its ``session_id`` field.
    archive_root: Path = workspace.agentlab_dir / "compact_archive"
    archive = CompactArchive(root=archive_root, session_id=session.session_id)
    ranges = archive.ranges()
    if not ranges:
        return "Nothing to uncompact — no compaction archive for this session."

    # Most recent = last in sorted order. ``ranges()`` sorts ascending by
    # (start, end), so ``ranges[-1]`` is the most-recent slice.
    start, end = ranges[-1]
    messages = archive.load(start, end)

    callback = ctx.uncompact_callback
    if callable(callback):
        try:
            callback(messages)
        except Exception as exc:  # Keep the loop alive on callback failures.
            return (
                f"  Restored {end - start} messages from range [{start}, {end}), "
                f"but uncompact_callback raised: {type(exc).__name__}: {exc}"
            )

    return f"Restored {end - start} messages from range [{start}, {end})."


def _handle_memory_debug(ctx: SlashContext, *_: str) -> str:
    """Show the memories injected on the most recent turn with their scores.

    Reads :attr:`SlashContext.memory_last_retrieval` — a
    :class:`cli.memory.retrieval.RetrievalResult` the orchestrator stamps
    onto the context after each turn that invokes retrieval. When nothing
    is stamped yet (new session, or retrieval was skipped) we emit a
    friendly hint rather than an empty render.
    """
    retrieval = ctx.memory_last_retrieval
    if not retrieval:
        return "No memories injected yet. Run a turn with memories in the workspace first."

    reasons = list(getattr(retrieval, "reasons", []) or [])
    count = len(reasons)
    lines: list[str] = [f"Injected {count} memories this turn:"]
    if count == 0:
        # Retrieval ran but nothing scored — say so explicitly instead of
        # leaving the user staring at a lone header.
        lines.append("  (retrieval ran but nothing matched — consider broadening the query)")
        return "\n".join(lines)

    for reason in reasons:
        name = getattr(reason, "name", "?")
        final_score = float(getattr(reason, "final_score", 0.0) or 0.0)
        recency = float(getattr(reason, "recency_bonus", 0.0) or 0.0)
        term_hits = getattr(reason, "term_hits", {}) or {}
        lines.append(
            f"- {name}: score={final_score:.3f} recency={recency:.3f} terms={dict(term_hits)}"
        )
    return "\n".join(lines)


def _handle_memory_edit(ctx: SlashContext, *args: str) -> str:
    """Open the memory index (or a specific memory file) in ``$EDITOR``.

    Default target is ``<workspace>/.agentlab/memory/MEMORY.md`` — the
    index :class:`cli.memory.store.MemoryStore` rewrites on every save.
    When a positional slug is supplied we target ``<slug>.md`` in the
    same directory, matching the per-memory file layout.

    ``$EDITOR`` falls back to ``vi`` to match the POSIX convention and
    Claude Code's own ``/memory-edit`` behaviour. ``subprocess.run``
    uses ``check=False`` so a non-zero exit from the editor (e.g.
    ``:cq`` in vim) doesn't crash the REPL.
    """
    workspace = ctx.workspace
    if workspace is None:
        return "  No workspace — /memory-edit unavailable."

    memory_dir: Path = workspace.agentlab_dir / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)

    if args and args[0].strip():
        slug = args[0].strip()
        path = memory_dir / f"{slug}.md"
    else:
        path = memory_dir / "MEMORY.md"

    editor = os.environ.get("EDITOR") or "vi"
    # ``subprocess.run`` is called through the module-level name so tests
    # can ``monkeypatch.setattr("cli.workbench_app.slash.subprocess.run", …)``
    # without touching the global subprocess module.
    subprocess.run([editor, str(path)], check=False)
    return f"Opened {path} in {editor}."


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


def _handle_find(ctx: SlashContext, *args: str) -> OnDoneResult:
    """Quick-open fuzzy search across commands, sessions, and memories.

    Modes:

    * ``/find`` — render a help card showing the supported scopes.
    * ``/find <query>`` — search all scopes and return a ranked list.
    * ``/find cmd:<query>`` / ``sess:<query>`` / ``mem:<query>`` — scope
      the search to one source. The ``cmd:``/``sess:``/``mem:`` prefixes
      are matched case-insensitively so ``/find CMD:status`` also works.

    The handler is the terminal analog of Claude Code's ``GlobalSearchDialog``
    — it reads like a `fd`/`fzf` one-shot: you type a query, you get a list
    of hits you can copy-paste into the next prompt.
    """
    if not args:
        return on_done(_render_find_help(), display="user")

    raw = " ".join(args).strip()
    scope, query = _parse_find_scope(raw)
    if not query:
        return on_done(
            "  /find needs a query. Try /find status or /find sess:r6.",
            display="system",
        )

    lines: list[str] = [theme.heading(f"\n  Search: {query!r}")]
    any_hits = False

    if scope in ("all", "cmd"):
        cmd_hits = _filter_commands(ctx.registry, query) if ctx.registry else []
        if cmd_hits:
            any_hits = True
            lines.append("")
            lines.append(theme.meta("  Commands"))
            for command in cmd_hits[:10]:
                lines.append(
                    f"    /{command.name}  {theme.meta(command.description)}"
                )

    if scope in ("all", "sess"):
        session_hits = _filter_sessions(ctx, query)
        if session_hits:
            any_hits = True
            lines.append("")
            lines.append(theme.meta("  Sessions"))
            for session in session_hits[:10]:
                title = session.title or session.session_id
                age = _format_session_age(time.time() - (session.updated_at or 0.0))
                lines.append(
                    f"    {session.session_id}  {title}  {theme.meta(age)}"
                )
            lines.append(theme.meta("    (use /resume <id> to switch)"))

    if scope in ("all", "mem"):
        memory_hits = _filter_memories(ctx, query)
        if memory_hits:
            any_hits = True
            lines.append("")
            lines.append(theme.meta("  Memories"))
            for slug, snippet in memory_hits[:10]:
                lines.append(f"    {slug}  {theme.meta(snippet)}")
            lines.append(theme.meta("    (use /memory-edit <slug> to open)"))

    if not any_hits:
        return on_done(
            f"  No matches for {query!r} in {scope if scope != 'all' else 'any scope'}.",
            display="system",
        )

    lines.append("")
    return on_done("\n".join(lines), display="user")


def _render_find_help() -> str:
    """Short usage card for ``/find`` with no arguments."""
    rows = [
        ("/find <query>", "Search commands, sessions, and memories"),
        ("/find cmd:<query>", "Restrict the search to slash commands"),
        ("/find sess:<query>", "Restrict the search to saved sessions"),
        ("/find mem:<query>", "Restrict the search to memory entries"),
    ]
    width = max(len(row[0]) for row in rows)
    lines = [theme.heading("\n  Find — quick-open search")]
    for key, desc in rows:
        lines.append(f"    {key.ljust(width)}  {desc}")
    lines.append("")
    lines.append("  Tip: /find is fuzzy — typos land close matches too.")
    return "\n".join(lines)


def _parse_find_scope(raw: str) -> tuple[str, str]:
    """Split ``"cmd:status"`` → ``("cmd", "status")``; default scope ``"all"``."""
    lowered = raw.lower()
    for prefix, scope in (
        ("cmd:", "cmd"),
        ("sess:", "sess"),
        ("session:", "sess"),
        ("mem:", "mem"),
        ("memory:", "mem"),
    ):
        if lowered.startswith(prefix):
            return scope, raw[len(prefix):].strip()
    return "all", raw


def _filter_sessions(ctx: SlashContext, query: str) -> list[Session]:
    """Return saved sessions whose title or id matches ``query`` (fuzzy)."""
    store = ctx.session_store
    if store is None:
        return []
    token = query.strip().lower()
    if not token:
        return []
    try:
        sessions = store.list_sessions(limit=50)
    except Exception:  # pragma: no cover — defensive
        return []
    scored: list[tuple[int, Session]] = []
    for session in sessions:
        title = (session.title or "").lower()
        sid = session.session_id.lower()
        score = 0
        if token == sid or token == title:
            score = 100
        elif sid.startswith(token) or title.startswith(token):
            score = 80
        elif token in sid or token in title:
            score = 60
        elif any(token in entry.content.lower() for entry in session.transcript[-5:]):
            score = 40
        if score > 0:
            scored.append((score, session))
    scored.sort(key=lambda row: (-row[0], -row[1].updated_at))
    return [session for _score, session in scored]


def _filter_memories(ctx: SlashContext, query: str) -> list[tuple[str, str]]:
    """Return ``(slug, snippet)`` pairs from the workspace memory dir."""
    workspace = ctx.workspace
    if workspace is None:
        return []
    memory_dir = getattr(workspace, "agentlab_dir", None)
    if memory_dir is None:
        return []
    memory_dir = memory_dir / "memory"
    if not memory_dir.exists():
        return []
    token = query.strip().lower()
    if not token:
        return []
    hits: list[tuple[int, str, str]] = []
    for path in sorted(memory_dir.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        slug = path.stem
        lower = text.lower()
        if token not in slug.lower() and token not in lower:
            continue
        score = 80 if token in slug.lower() else 40
        # Snippet: the line containing the first hit, trimmed.
        snippet = ""
        for line in text.splitlines():
            if token in line.lower():
                snippet = line.strip()
                break
        if not snippet:
            snippet = text.splitlines()[0].strip() if text.splitlines() else ""
        if len(snippet) > 80:
            snippet = snippet[:77] + "..."
        hits.append((score, slug, snippet))
    hits.sort(key=lambda row: (-row[0], row[1]))
    return [(slug, snippet) for _score, slug, snippet in hits]


def _handle_keybindings(ctx: SlashContext, *args: str) -> OnDoneResult:
    """Inspect active keyboard bindings, or open the config for editing.

    ``/keybindings`` renders a Claude-Code-style grouped table with each
    binding's keys, action, context, and whether it is built-in or came
    from the user's ``keybindings.json``. ``/keybindings edit`` opens that
    file in ``$EDITOR`` (creating a starter stub when the file is absent)
    so users can customise without having to remember the path.
    """
    from cli.keybindings.loader import (
        DEFAULT_BINDINGS,
        DEFAULT_CONFIG_PATH,
        KeyBindingMode,
        load_bindings,
    )

    if args and args[0].lower() == "edit":
        return _keybindings_edit(DEFAULT_CONFIG_PATH)

    try:
        binding_set = load_bindings()
    except Exception as exc:  # Malformed config shouldn't crash the REPL.
        return on_done(
            f"  Could not load keybindings: {exc}\n"
            "  Run /keybindings edit to repair the config.",
            display="system",
        )

    default_keys = {(b.keys, b.when) for b in DEFAULT_BINDINGS}
    user_bindings = [
        b for b in binding_set.bindings if (b.keys, b.when) not in default_keys
    ]
    default_kept = [
        b for b in binding_set.bindings if (b.keys, b.when) in default_keys
    ]
    # Hard-coded prompt bindings that live in pt_prompt.py but the user
    # can't override. Listed explicitly so the surface honestly reflects
    # what will fire at the keyboard.
    hardwired: tuple[tuple[str, str, str], ...] = (
        ("/", "open-slash-menu", "prompt"),
        ("shift+tab", "mode-cycle", "prompt"),
        ("ctrl+t", "toggle-transcript", "prompt"),
    )

    lines: list[str] = [theme.heading("\n  Keyboard Bindings")]
    mode_label = (
        "Vim" if binding_set.mode == KeyBindingMode.VIM else "Default (emacs)"
    )
    lines.append(theme.meta(f"  Mode: {mode_label}"))

    lines.append("")
    lines.append(theme.meta("  Built-in"))
    width = _keybindings_column_width(default_kept, hardwired)
    for binding in default_kept:
        keys = "+".join(binding.keys) if len(binding.keys) > 1 else binding.keys[0]
        context = binding.when or "global"
        lines.append(
            f"    {keys.ljust(width)}  {binding.command}  {theme.meta('(' + context + ')')}"
        )
    for keys_text, action, context in hardwired:
        lines.append(
            f"    {keys_text.ljust(width)}  {action}  "
            f"{theme.meta('(' + context + ', hard-wired)')}"
        )

    if user_bindings:
        lines.append("")
        lines.append(theme.meta("  User overrides"))
        for binding in user_bindings:
            keys = "+".join(binding.keys) if len(binding.keys) > 1 else binding.keys[0]
            context = binding.when or "global"
            lines.append(
                f"    {keys.ljust(width)}  {binding.command}  "
                f"{theme.meta('(' + context + ')')}"
            )
    else:
        lines.append("")
        lines.append(theme.meta("  No user overrides — /keybindings edit to add some."))

    lines.append("")
    lines.append(
        f"  Config file: {DEFAULT_CONFIG_PATH}  "
        f"{theme.meta('(edit with /keybindings edit)')}"
    )
    return on_done("\n".join(lines), display="user")


def _keybindings_column_width(
    default_kept: Sequence[Any], hardwired: Sequence[tuple[str, str, str]]
) -> int:
    """Compute a shared column width so keys line up across sections."""
    widths = [6]  # sensible minimum
    for binding in default_kept:
        keys = "+".join(binding.keys) if len(binding.keys) > 1 else binding.keys[0]
        widths.append(len(keys))
    for keys_text, _action, _context in hardwired:
        widths.append(len(keys_text))
    return max(widths)


def _keybindings_edit(path: Path) -> OnDoneResult:
    """Open ``keybindings.json`` in ``$EDITOR``, creating a stub if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(
            '{\n'
            '  "mode": "default",\n'
            '  "bindings": [\n'
            '    {"keys": "ctrl+k", "command": "clear-transcript"}\n'
            '  ]\n'
            '}\n',
            encoding="utf-8",
        )
    editor = os.environ.get("EDITOR") or "vi"
    subprocess.run([editor, str(path)], check=False)
    return on_done(
        f"Opened {path} in {editor}. Restart the Workbench to pick up changes.",
        display="system",
    )


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
    # Narrow category label used by the new categorized /help renderer.
    # Optional — unset commands fall through to _category_for()'s keyword
    # heuristic so new built-ins don't have to ship a category on day one.
    category: str | None = None


_SOURCE_LABELS: tuple[tuple[str, str], ...] = (
    ("builtin", "Builtin Commands"),
    ("project", "Project Commands"),
    ("user", "User Commands"),
    ("plugin", "Plugin Commands"),
)

# Category display order for the ``/help`` table. Anything not listed here
# is rendered alphabetically after the known categories so future additions
# still appear without a code change.
_CATEGORY_ORDER: tuple[str, ...] = (
    "Session",
    "Memory & Context",
    "Config & Theme",
    "Workflow",
    "Planning",
    "Lineage & Diff",
    "Skills & Plugins",
    "Shell",
    "Diagnostics",
    "Help & Meta",
    "Other",
)

# Map of built-in command name → category. Kept separate from ``_BuiltinSpec``
# so command categorization can be edited in one table without churning the
# spec list. Names not in the map fall through to _category_keyword() and
# finally to "Other".
_BUILTIN_CATEGORIES: dict[str, str] = {
    # Session lifecycle
    "resume": "Session",
    "new": "Session",
    "sessions": "Session",
    "clear": "Session",
    "fork": "Session",
    "exit": "Session",
    "compact": "Session",
    "uncompact": "Session",
    # Memory and context
    "memory": "Memory & Context",
    "memory-debug": "Memory & Context",
    "memory-edit": "Memory & Context",
    "usage": "Memory & Context",
    "context": "Memory & Context",
    "transcript-checkpoint": "Memory & Context",
    "transcript-checkpoints": "Memory & Context",
    "transcript-rewind": "Memory & Context",
    "checkpoint": "Memory & Context",
    "checkpoints": "Memory & Context",
    "rewind": "Memory & Context",
    # Config and theme
    "config": "Config & Theme",
    "theme": "Config & Theme",
    "output-style": "Config & Theme",
    "model": "Config & Theme",
    "permissions": "Config & Theme",
    "init": "Config & Theme",
    "mcp": "Config & Theme",
    # Workflow (streaming coordinator)
    "eval": "Workflow",
    "optimize": "Workflow",
    "build": "Workflow",
    "deploy": "Workflow",
    "ship": "Workflow",
    "improve": "Workflow",
    "save": "Workflow",
    "review": "Workflow",
    "tasks": "Workflow",
    # Planning
    "plan": "Planning",
    "plan-approve": "Planning",
    "plan-discard": "Planning",
    "plan-done": "Planning",
    "plan-list": "Planning",
    # Lineage and diff
    "diff": "Lineage & Diff",
    "accept": "Lineage & Diff",
    "reject": "Lineage & Diff",
    "attempt-diff": "Lineage & Diff",
    "lineage": "Lineage & Diff",
    # Skills and plugins
    "skill": "Skills & Plugins",
    "skills": "Skills & Plugins",
    "skill-list": "Skills & Plugins",
    "skill-reload": "Skills & Plugins",
    "background": "Skills & Plugins",
    "background-clear": "Skills & Plugins",
    # Diagnostics
    "status": "Diagnostics",
    "doctor": "Diagnostics",
    "cost": "Diagnostics",
    # Help and meta
    "help": "Help & Meta",
    "shortcuts": "Help & Meta",
    "find": "Help & Meta",
    "keybindings": "Help & Meta",
}


def _category_for(command: SlashCommand) -> str:
    """Resolve the display category for a command.

    Precedence:

    1. Explicit ``_BUILTIN_CATEGORIES`` mapping — authoritative.
    2. Keyword heuristic on ``name`` / ``description`` — lets unmapped
       plugin/user commands still land in a sensible bucket.
    3. ``"Other"`` — everything else, rendered last.
    """
    explicit = _BUILTIN_CATEGORIES.get(command.name)
    if explicit is not None:
        return explicit
    return _category_keyword(command)


def _category_keyword(command: SlashCommand) -> str:
    """Heuristic fallback for commands not present in the explicit map."""
    haystack = f"{command.name} {command.description or ''}".lower()
    if any(k in haystack for k in ("session", "resume", "fork", "compact")):
        return "Session"
    if any(k in haystack for k in ("memory", "transcript", "checkpoint", "context")):
        return "Memory & Context"
    if any(k in haystack for k in ("theme", "config", "style", "model", "permission", "mcp")):
        return "Config & Theme"
    if any(k in haystack for k in ("plan", "plan-", "planning")):
        return "Planning"
    if any(k in haystack for k in ("diff", "accept", "reject", "lineage")):
        return "Lineage & Diff"
    if any(k in haystack for k in ("skill", "plugin", "background")):
        return "Skills & Plugins"
    if any(k in haystack for k in ("status", "doctor", "cost", "diagnose")):
        return "Diagnostics"
    if any(k in haystack for k in ("help", "shortcut", "find", "keybind")):
        return "Help & Meta"
    if any(k in haystack for k in ("eval", "optim", "build", "deploy", "ship", "improve", "review", "task")):
        return "Workflow"
    return "Other"


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
        "uncompact",
        "Restore the most recent compaction",
        _handle_uncompact,
        when_to_use="Use when compaction hid a turn you still need.",
    ),
    _BuiltinSpec(
        "memory-debug",
        "Show which memories were injected this turn and why",
        _handle_memory_debug,
    ),
    _BuiltinSpec(
        "memory-edit",
        "Open MEMORY.md in $EDITOR",
        _handle_memory_edit,
        argument_hint="[name]",
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
    _BuiltinSpec(
        "find",
        "Fuzzy search commands, sessions, memories",
        _handle_find,
        argument_hint="[cmd:|sess:|mem:]<q>",
        aliases=("search",),
        when_to_use="Use when you know part of a name but not where it lives.",
    ),
    _BuiltinSpec(
        "keybindings",
        "Show active key bindings; `edit` opens the config",
        _handle_keybindings,
        argument_hint="[edit]",
        aliases=("keys",),
        when_to_use="Use to inspect what keys do what, or to customize the config.",
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
    from cli.workbench_app.attempt_diff_slash import build_attempt_diff_command
    from cli.workbench_app.lineage_view_slash import build_lineage_view_command
    from cli.workbench_app.plan_slash import all_plan_commands
    from cli.workbench_app.context_viz_slash import build_usage_command
    from cli.workbench_app.transcript_rewind_slash import all_transcript_rewind_commands
    from cli.user_skills.slash import all_skill_commands
    from cli.workbench_app.background_slash import all_background_commands
    from cli.workbench_app.init_slash import build_init_command
    from cli.workbench_app.theme_slash import build_theme_command
    from cli.workbench_app.output_style_slash import build_output_style_command
    from cli.workbench_app.fork_slash import build_fork_command
    from cli.workbench_app.resume_slash import build_resume_command
    from cli.workbench_app.suggest_slash import build_suggest_command

    registry.register(build_resume_command())
    registry.register(build_suggest_command())
    registry.register(build_fork_command())
    registry.register(build_model_command())
    registry.register(build_tasks_command())
    registry.register(build_context_command())
    registry.register(build_checkpoint_command())
    registry.register(build_rewind_command())
    registry.register(build_checkpoints_command())
    registry.register(build_diff_command())
    registry.register(build_accept_command())
    registry.register(build_reject_command())
    registry.register(build_attempt_diff_command())
    registry.register(build_lineage_view_command())
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
    # `/improve` is a streaming passthrough — no coordinator wrapper. It is
    # registered unconditionally so the TUI surfaces the full R2 improve
    # surface (run, accept, measure, diff, lineage, list, show) independently
    # of the streaming-intent toggle, which only gates coordinator commands.
    from cli.workbench_app.improve_slash import build_improve_command

    registry.register(build_improve_command())
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
