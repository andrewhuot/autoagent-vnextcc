"""Interactive REPL shell for AutoAgent."""

from __future__ import annotations

import shlex
import time
import uuid
from typing import Any

import click

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
    "/memory": "Show AUTOAGENT.md contents",
    "/doctor": "Run workspace diagnostics",
    "/review": "Show pending review cards",
    "/mcp": "Show MCP integration status",
    "/compact": "Summarize session to .autoagent/memory/latest_session.md",
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
        _run_click_command("mcp")
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
    """Summarize the current session into ``.autoagent/memory/latest_session.md``."""
    if workspace is None:
        click.echo("  No workspace — cannot save session summary.")
        return

    memory_dir = workspace.autoagent_dir / "memory"
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
        click.echo(click.style("  -> routing to: autoagent build", fg="green"))
        _run_click_command(f"build {shlex.quote(text)}")
    elif any(keyword in lower for keyword in ("eval", "test", "score", "grade")):
        click.echo(click.style("  -> routing to: autoagent eval run", fg="green"))
        _run_click_command("eval run")
    elif any(keyword in lower for keyword in ("optimize", "improve", "fix", "refine")):
        click.echo(click.style("  -> routing to: autoagent improve", fg="green"))
        _run_click_command("improve")
    elif any(keyword in lower for keyword in ("review", "check", "inspect")):
        click.echo(click.style("  -> routing to: autoagent review", fg="green"))
        _run_click_command("review")
    elif any(keyword in lower for keyword in ("deploy", "release", "ship")):
        click.echo(click.style("  -> routing to: autoagent deploy status", fg="green"))
        _run_click_command("deploy status")
    elif any(keyword in lower for keyword in ("status", "state", "dashboard")):
        _run_click_command("status")
    else:
        click.echo(click.style("  -> routing to: autoagent edit", fg="green"))
        click.echo(f'  Would run: autoagent edit "{text}"')
        click.echo("  (Free-text editing available in a future release.)")


def run_shell(workspace: Any, *, session_store: SessionStore | None = None) -> None:
    """Run the interactive REPL shell for the current workspace."""
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

    settings = resolve_settings(
        workspace_dir=workspace.root if workspace else None,
    )
    prompt_str = settings.get("shell.prompt", "autoagent> ")

    status_bar = _build_status_bar(workspace)
    click.echo(click.style("\n  AutoAgent Shell", fg="cyan", bold=True))
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

        if session_store is not None:
            session_store.append_entry(session, "user", user_input)
            session_store.append_command(session, user_input)

        if user_input.startswith("/"):
            should_exit = _handle_slash_command(
                user_input,
                workspace=workspace,
                session=session,
                session_store=session_store or SessionStore.__new__(SessionStore),
            )
            if should_exit:
                click.echo("  Goodbye.")
                break
            continue

        _route_free_text(user_input, workspace)

    if session_store is not None:
        session.updated_at = time.time()
        session_store.save(session)
