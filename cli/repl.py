"""Interactive REPL shell for AgentLab.

.. deprecated::
    This module is the legacy interactive shell reachable via
    ``agentlab --classic``. It is kept for one release for backward
    compatibility; new work should target
    :mod:`cli.workbench_app`, which powers the default ``agentlab``
    entry point (see :func:`cli.workbench_app.app.run_workbench_app`
    and :func:`cli.workbench_app.app.launch_workbench`). Every slash
    command ported here has an equivalent handler registered through
    :func:`cli.workbench_app.slash.build_builtin_registry`. The
    classic shell will be removed in a future release once the
    workbench surface covers the remaining harness-shell niches
    (queued input while busy, bottom-toolbar permission cycling).
"""

from __future__ import annotations

import asyncio
import shlex
import sys
import time
import uuid
import warnings
from typing import Any

import click

from cli.auto_harness import (
    HarnessEvent,
    HarnessRenderer,
    HarnessSession,
    MessageQueue,
    PermissionFooter,
    resolve_cli_ui,
)
from cli.permissions import PermissionManager, update_workspace_settings
from cli.sessions import Session, SessionStore
from cli.settings import resolve_settings


def _build_status_bar(workspace: Any) -> str:
    """Build a compact one-line status bar from workspace state."""
    parts: list[str] = []

    if workspace is not None:
        parts.append(click.style(workspace.workspace_label, fg="cyan", bold=True))

        active_config = workspace.resolve_active_config()
        if active_config:
            parts.append(f"v{active_config.version:03d}")

        cards_db = workspace.change_cards_db
        if cards_db.exists():
            try:
                import sqlite3

                conn = sqlite3.connect(str(cards_db))
                count = conn.execute(
                    "SELECT COUNT(*) FROM change_cards WHERE status = 'pending'"
                ).fetchone()[0]
                conn.close()
                if count:
                    parts.append(click.style(f"{count} reviews", fg="yellow"))
            except Exception:
                pass

        score_file = workspace.best_score_file
        if score_file.exists():
            score_text = score_file.read_text(encoding="utf-8").strip()
            if score_text:
                parts.append(f"score:{score_text}")

    return " | ".join(parts) if parts else "no workspace"


SLASH_COMMANDS: dict[str, str] = {
    "/help": "Show available slash commands",
    "/status": "Show workspace status",
    "/config": "Show active config info",
    "/memory": "Show AGENTLAB.md contents",
    "/doctor": "Run workspace diagnostics",
    "/review": "Show pending review cards",
    "/mcp": "Show MCP integration status",
    "/compact": "Summarize session to .agentlab/memory/latest_session.md",
    "/resume": "Resume the most recent session",
    "/exit": "Exit the shell",
}


def _handle_slash_command(
    command: str,
    *,
    workspace: Any,
    session: Session,
    session_store: SessionStore,
) -> bool:
    """Handle a slash command and return ``True`` when the shell should exit."""
    command_name = command.strip().split()[0].lower()

    if command_name == "/exit":
        return True

    if command_name == "/help":
        click.echo(click.style("\n  Slash Commands", bold=True))
        for name, description in SLASH_COMMANDS.items():
            click.echo(f"    {name:<12} {description}")
        click.echo("")
        return False

    if command_name == "/status":
        _run_click_command("status")
        return False

    if command_name == "/config":
        if workspace is not None:
            active = workspace.resolve_active_config()
            if active:
                click.echo(f"  Active config: v{active.version:03d} — {active.path}")
                click.echo(f"  Summary: {workspace.summarize_config(active.config)}")
            else:
                click.echo("  No active config.")
        else:
            click.echo("  No workspace.")
        return False

    if command_name == "/memory":
        _run_click_command("memory show")
        return False

    if command_name == "/doctor":
        _run_click_command("doctor")
        return False

    if command_name == "/review":
        _run_click_command("review")
        return False

    if command_name == "/mcp":
        _run_click_command("mcp status")
        return False

    if command_name == "/compact":
        _compact_session(session, workspace)
        return False

    if command_name == "/resume":
        latest = session_store.latest()
        if latest and latest.session_id != session.session_id:
            click.echo(f"  Loaded session: {latest.title} ({latest.session_id})")
            click.echo(f"  Goal: {latest.active_goal or '(none)'}")
            click.echo(f"  Entries: {len(latest.transcript)}")
        else:
            click.echo("  No previous session to resume.")
        return False

    click.echo(f"  Unknown command: {command_name}.  Type /help for available commands.")
    return False


def _run_click_command(command_path: str) -> None:
    """Invoke an existing CLI command by name and echo its output."""
    try:
        from click.testing import CliRunner
        from runner import cli as root_cli

        try:
            runner = CliRunner(mix_stderr=False)
        except TypeError:
            runner = CliRunner()
        result = runner.invoke(root_cli, shlex.split(command_path), catch_exceptions=False)
        if result.output:
            click.echo(result.output.rstrip())
    except Exception as exc:
        click.echo(f"  Error running '{command_path}': {exc}")


def _compact_session(session: Session, workspace: Any) -> None:
    """Summarize the current session into ``.agentlab/memory/latest_session.md``."""
    if workspace is None:
        click.echo("  No workspace — cannot save session summary.")
        return

    memory_dir = workspace.agentlab_dir / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    summary_path = memory_dir / "latest_session.md"

    lines = [
        f"# Session: {session.title}",
        f"ID: {session.session_id}",
        f"Started: {time.strftime('%Y-%m-%d %H:%M', time.localtime(session.started_at))}",
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
    click.echo(f"  Session summary saved to {summary_path}")


def _route_free_text(text: str, workspace: Any) -> None:
    """Route free-text input to the most likely CLI surface."""
    lower = text.lower().strip()
    del workspace

    if any(keyword in lower for keyword in ("build", "create", "scaffold", "generate")):
        click.echo(click.style("  -> routing to: agentlab build", fg="green"))
        _run_click_command(f"build {shlex.quote(text)}")
    elif any(keyword in lower for keyword in ("eval", "test", "score", "grade")):
        click.echo(click.style("  -> routing to: agentlab eval run", fg="green"))
        _run_click_command("eval run")
    elif any(keyword in lower for keyword in ("optimize", "improve", "fix", "refine")):
        click.echo(click.style("  -> routing to: agentlab improve", fg="green"))
        _run_click_command("improve")
    elif any(keyword in lower for keyword in ("review", "check", "inspect")):
        click.echo(click.style("  -> routing to: agentlab review", fg="green"))
        _run_click_command("review")
    elif any(keyword in lower for keyword in ("deploy", "release", "ship")):
        click.echo(click.style("  -> routing to: agentlab deploy status", fg="green"))
        _run_click_command("deploy status")
    elif any(keyword in lower for keyword in ("status", "state", "dashboard")):
        _run_click_command("status")
    else:
        click.echo(click.style("  -> routing to: agentlab edit", fg="green"))
        click.echo(f'  Would run: agentlab edit "{text}"')
        click.echo("  (Free-text editing available in a future release.)")


def _create_shell_session(
    workspace: Any,
    session_store: SessionStore | None,
) -> tuple[Session, SessionStore | None]:
    """Create the persisted or ephemeral shell session shared by both UIs."""
    if session_store is None and workspace is not None:
        session_store = SessionStore(workspace.root)

    if session_store is not None:
        session = session_store.create()
    else:
        session = Session(
            session_id=uuid.uuid4().hex[:12],
            title="ephemeral",
            started_at=time.time(),
            updated_at=time.time(),
        )
    return session, session_store


def _record_shell_input(
    session: Session,
    session_store: SessionStore | None,
    user_input: str,
) -> None:
    """Record user input in the shell transcript before command routing."""
    if session_store is not None:
        session_store.append_entry(session, "user", user_input)
        session_store.append_command(session, user_input)


def _process_shell_input(
    user_input: str,
    *,
    workspace: Any,
    session: Session,
    session_store: SessionStore | None,
) -> bool:
    """Execute one shell input and return True when the shell should exit."""
    _record_shell_input(session, session_store, user_input)

    if user_input.startswith("/"):
        return _handle_slash_command(
            user_input,
            workspace=workspace,
            session=session,
            session_store=session_store or SessionStore.__new__(SessionStore),
        )

    _route_free_text(user_input, workspace)
    return False


def run_shell(
    workspace: Any,
    *,
    session_store: SessionStore | None = None,
    ui: str | None = None,
) -> None:
    """Run the interactive REPL shell for the current workspace.

    .. deprecated::
        Prefer :func:`cli.workbench_app.app.launch_workbench`. This
        function is reached via ``agentlab --classic`` and will be
        removed in a future release. A :class:`DeprecationWarning` is
        emitted on each entry to surface the migration path.
    """
    warnings.warn(
        "cli.repl.run_shell is deprecated; use "
        "cli.workbench_app.app.launch_workbench (default for "
        "`agentlab` with no args). `--classic` is kept for one release.",
        DeprecationWarning,
        stacklevel=2,
    )
    session, session_store = _create_shell_session(workspace, session_store)

    settings = resolve_settings(
        workspace_dir=workspace.root if workspace else None,
    )
    prompt_str = settings.get("shell.prompt", "agentlab> ")

    resolved_ui = resolve_cli_ui("text", requested_ui=ui)
    if resolved_ui == "claude" and _stdio_is_tty():
        try:
            _run_harness_shell(
                workspace,
                session=session,
                session_store=session_store,
                prompt_str=prompt_str,
            )
            return
        except ImportError:
            click.echo("  prompt_toolkit is not installed; falling back to classic shell.")

    status_bar = _build_status_bar(workspace)
    click.echo(click.style("\n  AgentLab Shell", fg="cyan", bold=True))
    click.echo(f"  [{status_bar}]")
    click.echo("  Type /help for commands, or enter free text.\n")

    while True:
        try:
            user_input = input(prompt_str).strip()
        except (EOFError, KeyboardInterrupt):
            click.echo("\n  Goodbye.")
            break

        if not user_input:
            continue

        should_exit = _process_shell_input(
            user_input,
            workspace=workspace,
            session=session,
            session_store=session_store,
        )
        if should_exit:
            click.echo("  Goodbye.")
            break

    if session_store is not None:
        session.updated_at = time.time()
        session_store.save(session)


def _stdio_is_tty() -> bool:
    """Return True when both shell input and output can support a live prompt."""
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except Exception:
        return False


def _run_harness_shell(
    workspace: Any,
    *,
    session: Session,
    session_store: SessionStore | None,
    prompt_str: str,
) -> None:
    """Run the prompt_toolkit-backed shell that can queue input while busy."""
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.patch_stdout import patch_stdout
        from prompt_toolkit.styles import Style
    except ImportError:
        raise

    async def _main() -> None:
        permission_root = workspace.root if workspace is not None else "."
        footer = PermissionFooter(PermissionManager(root=permission_root).mode)
        harness = HarnessSession(permission_mode=footer.mode)
        queue = MessageQueue()
        renderer = HarnessRenderer(include_footer=False, styled=True)
        bindings = KeyBindings()

        @bindings.add("s-tab")
        def _cycle_permission_mode(event) -> None:  # noqa: ANN001 - prompt_toolkit callback
            del event
            footer.cycle()
            harness.emit(HarnessEvent("permission.mode_changed", message=footer.mode))
            if workspace is not None:
                update_workspace_settings(
                    {"permissions": {"mode": footer.mode}},
                    root=workspace.root,
                )
            event.app.invalidate()

        @bindings.add("down")
        def _toggle_manage_panel(event) -> None:  # noqa: ANN001 - prompt_toolkit callback
            harness.emit(HarnessEvent("manage.toggled"))
            event.app.invalidate()

        prompt_session = PromptSession(
            message=renderer.prompt_message() if prompt_str == "agentlab> " else prompt_str,
            bottom_toolbar=lambda: footer.render_toolbar_fragments(harness.snapshot()),
            key_bindings=bindings,
            style=Style.from_dict(
                {
                    "prompt.border": "ansibrightblack",
                    "permission.danger": "ansired",
                    "permission.normal": "ansiwhite",
                    "separator": "ansibrightblack",
                    "activity": "ansicyan",
                    "hint": "ansibrightblack",
                    "panel.title": "ansicyan bold",
                    "panel.row": "ansiwhite",
                }
            ),
        )
        harness.emit(HarnessEvent("session.started", message="AgentLab Shell"))
        harness.emit(
            HarnessEvent(
                "message.delta",
                message="Ready. Type a prompt or slash command.",
            )
        )
        harness.emit(
            HarnessEvent(
                "plan.ready",
                payload={
                    "tasks": [
                        {"id": "route", "title": "Route command or prompt"},
                        {"id": "run", "title": "Run selected AgentLab workflow"},
                        {"id": "queue", "title": "Drain queued input"},
                    ]
                },
            )
        )
        click.echo(click.style("\n  AgentLab Shell", fg="cyan", bold=True))
        click.echo(renderer.render(harness.snapshot()))

        active_task: asyncio.Task[bool] | None = None
        stop_requested = False

        async def _run_input(text: str) -> bool:
            harness.emit(
                HarnessEvent(
                    "task.started",
                    task_id="route",
                    task="Route command or prompt",
                )
            )
            loop = asyncio.get_running_loop()
            should_exit = await loop.run_in_executor(
                None,
                lambda: _process_shell_input(
                    text,
                    workspace=workspace,
                    session=session,
                    session_store=session_store,
                ),
            )
            harness.emit(
                HarnessEvent(
                    "task.completed",
                    task_id="route",
                    task="Route command or prompt",
                )
            )
            return should_exit

        def _drain_next() -> None:
            nonlocal active_task
            if active_task is None and queue.items():
                queued = queue.pop_next()
                if harness.queue.items():
                    harness.queue.pop_next()
                harness.emit(
                    HarnessEvent("stage.started", message=_input_stage_label(queued.text))
                )
                harness.emit(
                    HarnessEvent(
                        "task.started",
                        task_id="queue",
                        task="Drain queued input",
                    )
                )
                active_task = asyncio.create_task(_run_input(queued.text))

        with patch_stdout():
            while not stop_requested:
                if active_task is not None and active_task.done():
                    stop_requested = active_task.result()
                    active_task = None
                    harness.emit(
                        HarnessEvent(
                            "task.completed",
                            task_id="run",
                            task="Run selected AgentLab workflow",
                        )
                    )
                    harness.emit(HarnessEvent("stage.completed", message="Done"))
                    _drain_next()
                    if stop_requested:
                        break

                try:
                    user_input = (await prompt_session.prompt_async()).strip()
                except (EOFError, KeyboardInterrupt):
                    click.echo("\n  Goodbye.")
                    break

                if not user_input:
                    continue

                if active_task is not None and not active_task.done():
                    queue.add(user_input)
                    harness.emit(HarnessEvent("input.queued", message=user_input))
                    click.echo(renderer.render(harness.snapshot()))
                    continue

                harness.emit(HarnessEvent("stage.started", message=_input_stage_label(user_input)))
                harness.emit(
                    HarnessEvent(
                        "task.started",
                        task_id="run",
                        task="Run selected AgentLab workflow",
                    )
                )
                active_task = asyncio.create_task(_run_input(user_input))

            if active_task is not None and not active_task.done():
                await active_task

        if session_store is not None:
            session.updated_at = time.time()
            session_store.save(session)

    asyncio.run(_main())


def _input_stage_label(text: str) -> str:
    """Return a compact Claude-style active label for a shell input turn."""
    stripped = " ".join(text.strip().split())
    if not stripped:
        return "Running input"
    if len(stripped) > 64:
        stripped = stripped[:61] + "..."
    return f"Running {stripped}"
