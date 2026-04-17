"""Workspace-scoped MCP runtime configuration helpers and commands.

This module is the CLI-facing layer over the typed
:mod:`cli.mcp.config` module. All on-disk reads/writes go through
:func:`cli.mcp.config.load_config` / :func:`cli.mcp.config.save_config`
so the `.mcp.json` file stays validated end-to-end, but the helpers here
still return plain dicts for callers (and JSON envelopes) that predate
the typed surface.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from cli.errors import click_error
from cli.json_envelope import render_json_envelope
from cli.mcp.config import (
    HttpServerConfig,
    McpConfig,
    ServerConfig,
    SseServerConfig,
    StdioServerConfig,
    load_config,
    save_config,
)


MCP_CONFIG_FILENAME = ".mcp.json"

VALID_TRANSPORTS = ("stdio", "sse", "http", "streamable-http")


def mcp_config_path(root: str | Path = ".") -> Path:
    """Return the workspace MCP config path."""
    return Path(root) / MCP_CONFIG_FILENAME


def load_mcp_config(root: str | Path = ".") -> McpConfig:
    """Load the typed workspace `.mcp.json` config.

    Prefer this over :func:`load_mcp_config_raw` in new code — the
    typed surface validates every entry and exposes transport metadata.
    """
    return load_config(mcp_config_path(root))


def load_mcp_config_raw(root: str | Path = ".") -> dict[str, Any]:
    """Load the workspace `.mcp.json` as a raw dict (legacy shape).

    Retained for callers that serialize the payload directly into JSON
    envelopes without going through the typed layer.
    """
    path = mcp_config_path(root)
    if not path.exists():
        return {"mcpServers": {}}
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return {"mcpServers": {}}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"mcpServers": {}}
    if not isinstance(payload, dict):
        return {"mcpServers": {}}
    servers = payload.get("mcpServers")
    if not isinstance(servers, dict):
        payload["mcpServers"] = {}
    return payload


def save_mcp_config(config: McpConfig, root: str | Path = ".") -> Path:
    """Persist a typed workspace `.mcp.json`."""
    path = mcp_config_path(root)
    save_config(path, config)
    return path


def _server_to_dict(name: str, server: ServerConfig) -> dict[str, Any]:
    """Flatten a :class:`ServerConfig` into the legacy dict shape that
    CLI envelopes and bridge adapters expect.

    We always expose ``transport`` so consumers can distinguish stdio
    from SSE / Streamable-HTTP. Stdio entries keep ``command/args/env``
    for backwards compat with the bridge loader; remote transports use
    ``url/headers`` (plus ``ping_interval_seconds`` for SSE).
    """
    base: dict[str, Any] = {"name": name, "transport": server.transport}
    if isinstance(server, StdioServerConfig):
        base["command"] = server.command
        base["args"] = list(server.args)
        base["env"] = dict(server.env)
    elif isinstance(server, SseServerConfig):
        base["url"] = server.url
        base["headers"] = dict(server.headers)
        base["ping_interval_seconds"] = server.ping_interval_seconds
    elif isinstance(server, HttpServerConfig):
        base["url"] = server.url
        base["headers"] = dict(server.headers)
    return base


def list_mcp_servers(root: str | Path = ".") -> list[dict[str, Any]]:
    """Return configured workspace MCP servers as dicts with ``transport``."""
    config = load_mcp_config(root)
    return [
        _server_to_dict(name, server)
        for name, server in sorted(config.mcp_servers.items())
    ]


def add_mcp_server(
    name: str,
    *,
    transport: str = "stdio",
    command: str | None = None,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
    url: str | None = None,
    headers: dict[str, str] | None = None,
    ping_interval_seconds: float | None = None,
    root: str | Path = ".",
) -> Path:
    """Add or update one workspace MCP server entry.

    Dispatches on ``transport`` to construct the right typed model.
    Duplicates replace.
    """
    server = _build_server_config(
        name,
        transport=transport,
        command=command,
        args=args,
        env=env,
        url=url,
        headers=headers,
        ping_interval_seconds=ping_interval_seconds,
    )
    config = load_mcp_config(root)
    config.mcp_servers[name] = server
    return save_mcp_config(config, root)


def _build_server_config(
    name: str,
    *,
    transport: str,
    command: str | None,
    args: list[str] | None,
    env: dict[str, str] | None,
    url: str | None,
    headers: dict[str, str] | None,
    ping_interval_seconds: float | None,
) -> ServerConfig:
    if transport == "stdio":
        if not command:
            raise ValueError(
                f"stdio MCP server '{name}' requires --command"
            )
        return StdioServerConfig(
            command=command,
            args=list(args or []),
            env=dict(env or {}),
        )
    if transport == "sse":
        if not url:
            raise ValueError(f"sse MCP server '{name}' requires --url")
        sse = SseServerConfig(transport="sse", url=url, headers=dict(headers or {}))
        if ping_interval_seconds is not None:
            sse.ping_interval_seconds = ping_interval_seconds
        return sse
    if transport in {"http", "streamable-http"}:
        if not url:
            raise ValueError(
                f"http MCP server '{name}' requires --url"
            )
        return HttpServerConfig(
            transport="http",
            url=url,
            headers=dict(headers or {}),
        )
    raise ValueError(
        f"Unknown MCP transport '{transport}' (expected one of: "
        f"{', '.join(VALID_TRANSPORTS)})"
    )


def remove_mcp_server(name: str, root: str | Path = ".") -> tuple[bool, Path]:
    """Remove one workspace MCP server entry."""
    config = load_mcp_config(root)
    removed = name in config.mcp_servers
    if removed:
        del config.mcp_servers[name]
    path = save_mcp_config(config, root)
    return removed, path


def inspect_mcp_server(name: str, root: str | Path = ".") -> dict[str, Any] | None:
    """Return one workspace MCP server entry as a dict (with transport)."""
    config = load_mcp_config(root)
    server = config.mcp_servers.get(name)
    if server is None:
        return None
    return _server_to_dict(name, server)


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


def _render_server_line(item: dict[str, Any]) -> str:
    """Single-line rendering per server that tolerates any transport."""
    transport = item.get("transport", "stdio")
    name = item.get("name", "?")
    if transport == "stdio":
        cmd = item.get("command") or ""
        args = " ".join(item.get("args") or [])
        payload = f"{cmd} {args}".rstrip()
    else:
        payload = item.get("url") or ""
    return f"  - {name} [{transport}]: {payload}".rstrip()


def render_workspace_mcp_status(*, root: str | Path = ".", json_output: bool = False) -> None:
    """Render workspace MCP runtime status."""
    snapshot = mcp_status_snapshot(root)
    if json_output:
        click.echo(render_json_envelope("ok", snapshot, next_command="agentlab mcp list"))
        return
    click.echo("Workspace MCP runtime")
    click.echo(f"  Config: {snapshot['path']}")
    click.echo(f"  {snapshot['server_count']} workspace MCP server(s) configured")
    for item in snapshot["servers"]:
        click.echo(_render_server_line(item))
        click.echo(f"    Transport: {item.get('transport', 'stdio')}")


def _parse_header_options(raw_headers: tuple[str, ...]) -> dict[str, str]:
    """Parse ``--header 'Key: Value'`` strings into a mapping.

    The Click option is repeated, so we receive a tuple. Empty values
    after the colon are allowed (some servers use presence-only
    headers). Missing colons are a user error surfaced as
    :class:`click.UsageError` upstream.
    """
    out: dict[str, str] = {}
    for raw in raw_headers:
        if ":" not in raw:
            raise click.UsageError(
                f"--header expected 'Key: Value', got: {raw!r}"
            )
        key, _, value = raw.partition(":")
        key = key.strip()
        value = value.strip()
        if not key:
            raise click.UsageError(
                f"--header has empty key: {raw!r}"
            )
        out[key] = value
    return out


def register_runtime_commands(mcp_group: click.Group) -> None:
    """Attach workspace runtime MCP commands to the existing group."""

    @mcp_group.command("list")
    @click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
    def list_cmd(json_output: bool = False) -> None:
        data = list_mcp_servers()
        if json_output:
            click.echo(render_json_envelope("ok", data, next_command="agentlab mcp inspect <name>"))
            return
        if not data:
            click.echo("No workspace MCP servers configured.")
            click.echo("Run: agentlab mcp add <name> --command <cmd>")
            return
        click.echo("Workspace MCP servers")
        for item in data:
            click.echo(_render_server_line(item))

    @mcp_group.command("add")
    @click.argument("name")
    @click.option(
        "--transport",
        type=click.Choice(list(VALID_TRANSPORTS)),
        default="stdio",
        show_default=True,
        help="Transport protocol for the server.",
    )
    @click.option("--command", "command_name", default=None, help="Command to launch the server (stdio only).")
    @click.option("--arg", "args", multiple=True, help="Server argument. Repeat for multiple args (stdio only).")
    @click.option("--url", default=None, help="Server URL (sse / http only).")
    @click.option(
        "--header",
        "headers",
        multiple=True,
        help="HTTP header 'Key: Value' (sse / http only). Repeat for multiple.",
    )
    @click.option(
        "--ping-interval-seconds",
        "ping_interval_seconds",
        type=float,
        default=None,
        help="Expected server keep-alive cadence (sse only).",
    )
    def add_cmd(
        name: str,
        transport: str,
        command_name: str | None,
        args: tuple[str, ...],
        url: str | None,
        headers: tuple[str, ...],
        ping_interval_seconds: float | None,
    ) -> None:
        if transport == "stdio":
            if not command_name:
                raise click.UsageError(
                    "--command is required when --transport stdio"
                )
            if url:
                raise click.UsageError(
                    "--url is not valid for --transport stdio"
                )
            path = add_mcp_server(
                name,
                transport="stdio",
                command=command_name,
                args=list(args),
            )
        else:
            if not url:
                raise click.UsageError(
                    f"--url is required when --transport {transport}"
                )
            if command_name:
                raise click.UsageError(
                    f"--command is not valid for --transport {transport}"
                )
            if args:
                raise click.UsageError(
                    f"--arg is not valid for --transport {transport}"
                )
            header_map = _parse_header_options(headers)
            if transport == "sse":
                path = add_mcp_server(
                    name,
                    transport="sse",
                    url=url,
                    headers=header_map,
                    ping_interval_seconds=ping_interval_seconds,
                )
            else:  # http / streamable-http
                if ping_interval_seconds is not None:
                    raise click.UsageError(
                        "--ping-interval-seconds is sse-only"
                    )
                path = add_mcp_server(
                    name,
                    transport="http",
                    url=url,
                    headers=header_map,
                )
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
            click.echo(render_json_envelope("ok", item, next_command="agentlab mcp remove <name>"))
            return
        click.echo(json.dumps(item, indent=2))

    # ``mcp test`` lives in cli.mcp.test_command so the workspace-runtime
    # module doesn't have to depend on the typed-config + transport
    # machinery at import time. Registering it here keeps the user's
    # mental model of the CLI consistent: every MCP command is on the
    # same group.
    from cli.mcp.test_command import register_mcp_test_command

    register_mcp_test_command(mcp_group)
