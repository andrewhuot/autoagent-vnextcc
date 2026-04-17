"""Headless ``agentlab conversation`` CLI (R7 Slice C.5).

Exposes the workspace's persisted conversation store
(``.agentlab/conversations.db``) over four subcommands:

- ``list``      — recent conversations (text or JSON).
- ``show``      — full message history for one conversation.
- ``export``    — dump a conversation as JSON or Markdown.
- ``resume``    — point the next Workbench REPL launch at this
                  conversation by writing ``current_conversation_id``
                  into ``.agentlab/workbench_session.json``.

Markdown export deliberately wraps tool results in
``<tool_result tool="..." status="...">...</tool_result>`` fences so a
shared transcript preserves the same data/instructions distinction that
the R7.4 prompt-injection guard enforces inside the Workbench. Anything
inside the fences came back from a tool — never user instructions.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import click

from cli.workbench_app.conversation_store import Conversation, ConversationStore
from cli.workbench_app.session_state import WorkbenchSession


def _runner_module():
    """Late-bound import to keep the cli.commands package free of cycles."""
    import runner as _r
    return _r


def _store(workspace) -> ConversationStore:
    """Open the conversation DB rooted at the given workspace."""
    return ConversationStore(workspace.root / ".agentlab" / "conversations.db")


def _require_workspace():
    """Resolve the active workspace or raise a Click error.

    Centralized so all four subcommands fail the same way when run
    outside a workspace tree.
    """
    runner = _runner_module()
    workspace = runner.discover_workspace()
    if workspace is None:
        raise click.ClickException(
            "No AgentLab workspace found in the current directory tree. "
            "Run `agentlab init` or cd into a workspace first."
        )
    return workspace


def _conversation_to_dict(conv: Conversation) -> dict[str, Any]:
    """Serialize a Conversation to plain dicts (drops dataclass identity)."""
    return asdict(conv)


def _render_markdown(conv: Conversation) -> str:
    """Format a conversation as Markdown.

    Tool results are wrapped in ``<tool_result>`` fences to preserve the
    data/instructions distinction when transcripts are shared.
    """
    lines: list[str] = []
    lines.append(f"# Conversation {conv.id}")
    lines.append(f"- Created: {conv.created_at}")
    lines.append(f"- Model: {conv.model}")
    lines.append("")

    for msg in conv.messages:
        role_header = msg.role.capitalize()
        lines.append(f"## {role_header}")
        if msg.content:
            lines.append(msg.content)
        for tc in msg.tool_calls:
            display = ""
            if tc.result and isinstance(tc.result, dict):
                display = tc.result.get("display") or ""
            lines.append("")
            lines.append(
                f'<tool_result tool="{tc.tool_name}" status="{tc.status}">'
            )
            lines.append(display if display else "(no display)")
            lines.append("</tool_result>")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _render_show_text(conv: Conversation) -> str:
    """Human-readable text form for ``conversation show``."""
    lines: list[str] = []
    lines.append(f"Conversation {conv.id}")
    lines.append(f"  created_at: {conv.created_at}")
    lines.append(f"  model:      {conv.model}")
    lines.append(f"  messages:   {len(conv.messages)}")
    lines.append("")
    for msg in conv.messages:
        lines.append(f"[{msg.position}] {msg.role} @ {msg.created_at}")
        if msg.content:
            for content_line in msg.content.splitlines() or [""]:
                lines.append(f"    {content_line}")
        for tc in msg.tool_calls:
            display = ""
            if tc.result and isinstance(tc.result, dict):
                display = tc.result.get("display") or ""
            lines.append(f"    -> tool {tc.tool_name} [{tc.status}]")
            if display:
                for d_line in display.splitlines():
                    lines.append(f"       {d_line}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def register_conversation_commands(cli: click.Group) -> None:
    """Register the ``conversation`` group on *cli*."""

    @cli.group("conversation")
    def conversation_group() -> None:
        """Inspect, export, and resume Workbench conversations."""

    @conversation_group.command("list")
    @click.option(
        "--limit", default=20, show_default=True, type=int,
        help="Max conversations to return.",
    )
    @click.option(
        "--json", "json_output", is_flag=True,
        help="Emit JSON array instead of one line per conversation.",
    )
    def conversation_list(limit: int, json_output: bool) -> None:
        """List recent conversations (newest first)."""
        workspace = _require_workspace()
        store = _store(workspace)
        recent = store.list_recent(limit=limit)

        items = []
        for conv in recent:
            full = store.get_conversation(conv.id)
            items.append(
                {
                    "id": conv.id,
                    "updated_at": conv.updated_at,
                    "created_at": conv.created_at,
                    "model": conv.model,
                    "message_count": len(full.messages),
                }
            )

        if json_output:
            click.echo(json.dumps(items, indent=2))
            return

        for item in items:
            click.echo(
                f"{item['id']}  {item['updated_at']}  "
                f"{item['model'] or '-'}  ({item['message_count']} messages)"
            )

    @conversation_group.command("show")
    @click.argument("conversation_id")
    @click.option(
        "--json", "json_output", is_flag=True,
        help="Emit the conversation as a JSON object.",
    )
    def conversation_show(conversation_id: str, json_output: bool) -> None:
        """Show one conversation's full history."""
        workspace = _require_workspace()
        store = _store(workspace)
        try:
            conv = store.get_conversation(conversation_id)
        except KeyError as exc:
            raise click.ClickException(str(exc))

        if json_output:
            click.echo(json.dumps(_conversation_to_dict(conv), indent=2))
            return
        click.echo(_render_show_text(conv))

    @conversation_group.command("export")
    @click.argument("conversation_id")
    @click.option(
        "--format", "fmt",
        type=click.Choice(["json", "markdown"]),
        default="json", show_default=True,
        help="Export format.",
    )
    def conversation_export(conversation_id: str, fmt: str) -> None:
        """Export one conversation as JSON or Markdown."""
        workspace = _require_workspace()
        store = _store(workspace)
        try:
            conv = store.get_conversation(conversation_id)
        except KeyError as exc:
            raise click.ClickException(str(exc))

        if fmt == "json":
            click.echo(json.dumps(_conversation_to_dict(conv), indent=2))
        else:
            click.echo(_render_markdown(conv), nl=False)

    @conversation_group.command("resume")
    @click.argument("conversation_id")
    def conversation_resume(conversation_id: str) -> None:
        """Mark a conversation as the next REPL's resume target."""
        workspace = _require_workspace()
        store = _store(workspace)
        try:
            store.get_conversation(conversation_id)
        except KeyError as exc:
            raise click.ClickException(str(exc))

        session_path: Path = workspace.root / ".agentlab" / "workbench_session.json"
        session = WorkbenchSession.load(session_path)
        session.update(current_conversation_id=conversation_id)
        click.echo(
            f"Marked {conversation_id} as the next REPL resume target. "
            f"Run `agentlab workbench` to continue."
        )


__all__ = ["register_conversation_commands"]
