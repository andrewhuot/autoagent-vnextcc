"""Workspace-scoped MCP runtime configuration helpers and commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from cli.errors import click_error
from cli.json_envelope import render_json_envelope


MCP_CONFIG_FILENAME = ".mcp.json"


def mcp_config_path(root: str | Path = ".") -> Path:
    """Return the workspace MCP config path."""
    return Path(root) / MCP_CONFIG_FILENAME


def load_mcp_config(root: str | Path = ".") -> dict[str, Any]:
    """Load the workspace `.mcp.json` payload."""
    path = mcp_config_path(root)
    if not path.exists():
        return {"mcpServers": {}}
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return {"mcpServers": {}}
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        return {"mcpServers": {}}
    servers = payload.get("mcpServers")
    if not isinstance(servers, dict):
        payload["mcpServers"] = {}
    return payload


def save_mcp_config(payload: dict[str, Any], root: str | Path = ".") -> Path:
    """Persist the workspace `.mcp.json` payload."""
    path = mcp_config_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def list_mcp_servers(root: str | Path = ".") -> list[dict[str, Any]]:
    """Return configured workspace MCP servers."""
    payload = load_mcp_config(root)
    servers = payload.get("mcpServers", {})
    if not isinstance(servers, dict):
        return []
    items: list[dict[str, Any]] = []
    for name, config in sorted(servers.items()):
        config = config if isinstance(config, dict) else {}
        items.append(
            {
                "name": name,
                "command": config.get("command"),
                "args": config.get("args", []),
                "env": config.get("env", {}),
            }
        )
    return items


def add_mcp_server(
    name: str,
    *,
    command: str,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
    root: str | Path = ".",
) -> Path:
    """Add or update one workspace MCP server entry."""
    payload = load_mcp_config(root)
    servers = payload.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        servers = {}
        payload["mcpServers"] = servers
    servers[name] = {
        "command": command,
        "args": args or [],
    }
    if env:
        servers[name]["env"] = env
    return save_mcp_config(payload, root)


def remove_mcp_server(name: str, root: str | Path = ".") -> tuple[bool, Path]:
    """Remove one workspace MCP server entry."""
    payload = load_mcp_config(root)
    servers = payload.setdefault("mcpServers", {})
    removed = False
    if isinstance(servers, dict) and name in servers:
        removed = True
        del servers[name]
    path = save_mcp_config(payload, root)
    return removed, path


def inspect_mcp_server(name: str, root: str | Path = ".") -> dict[str, Any] | None:
    """Return one workspace MCP server entry."""
    for item in list_mcp_servers(root):
        if item["name"] == name:
            return item
    return None


def mcp_status_snapshot(root: str | Path = ".") -> dict[str, Any]:
    """Build the workspace MCP status summary."""
    path = mcp_config_path(root)
    servers = list_mcp_servers(root)
    return {
        "path": str(path),
        "configured": path.exists(),
        "server_count": len(servers),
        "servers": servers,
    }


def render_workspace_mcp_status(*, root: str | Path = ".", json_output: bool = False) -> None:
    """Render workspace MCP runtime status."""
    snapshot = mcp_status_snapshot(root)
    if json_output:
        click.echo(render_json_envelope("ok", snapshot, next_command="autoagent mcp list"))
        return
    click.echo("Workspace MCP runtime")
    click.echo(f"  Config: {snapshot['path']}")
    click.echo(f"  {snapshot['server_count']} workspace MCP server(s) configured")
    for item in snapshot["servers"]:
        click.echo(f"  - {item['name']}: {item['command']} {' '.join(item['args'])}".rstrip())


def register_runtime_commands(mcp_group: click.Group) -> None:
    """Attach workspace runtime MCP commands to the existing group."""

    @mcp_group.command("list")
    @click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
    def list_cmd(json_output: bool = False) -> None:
        data = list_mcp_servers()
        if json_output:
            click.echo(render_json_envelope("ok", data, next_command="autoagent mcp inspect <name>"))
            return
        if not data:
            click.echo("No workspace MCP servers configured.")
            click.echo("Run: autoagent mcp add <name> --command <cmd>")
            return
        click.echo("Workspace MCP servers")
        for item in data:
            click.echo(f"  {item['name']}: {item['command']} {' '.join(item['args'])}".rstrip())

    @mcp_group.command("add")
    @click.argument("name")
    @click.option("--command", "command_name", required=True, help="Command to launch the server.")
    @click.option("--arg", "args", multiple=True, help="Server argument. Repeat for multiple args.")
    def add_cmd(name: str, command_name: str, args: tuple[str, ...]) -> None:
        path = add_mcp_server(name, command=command_name, args=list(args))
        click.echo(f"Saved MCP server '{name}' to {path}")

    @mcp_group.command("remove")
    @click.argument("name")
    def remove_cmd(name: str) -> None:
        removed, path = remove_mcp_server(name)
        if not removed:
            raise click.ClickException(f"MCP server not found: {name}")
        click.echo(f"Removed MCP server '{name}' from {path}")

    @mcp_group.command("inspect")
    @click.argument("name")
    @click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
    def inspect_cmd(name: str, json_output: bool = False) -> None:
        item = inspect_mcp_server(name)
        if item is None:
            raise click.ClickException(f"MCP server not found: {name}")
        if json_output:
            click.echo(render_json_envelope("ok", item, next_command="autoagent mcp remove <name>"))
            return
        click.echo(json.dumps(item, indent=2))
