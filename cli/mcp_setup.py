"""CLI commands for MCP client configuration.

These flows write the documented AutoAgent MCP server definitions directly to
the target client config files so users do not need to hand-edit JSON/TOML.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import click

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python <3.11 fallback
    tomllib = None  # type: ignore[assignment]


@dataclass(frozen=True)
class MCPClientSpec:
    """Describe where and how a specific MCP client stores AutoAgent config."""

    client_name: str
    path_factory: Callable[[], Path]
    file_format: str
    verification_steps: list[str]


def _autoagent_json_entry() -> dict[str, Any]:
    """Return the shared stdio MCP server shape for JSON-based clients."""
    return {
        "command": "autoagent",
        "args": ["mcp-server"],
    }


def _autoagent_toml_payload() -> dict[str, Any]:
    """Return the shared stdio MCP server shape for TOML-based clients."""
    return {
        "mcp_servers": {
            "autoagent": {
                "command": "autoagent",
                "args": ["mcp-server"],
            }
        }
    }


def _client_specs() -> dict[str, MCPClientSpec]:
    """Return the supported MCP client definitions."""
    return {
        "claude-code": MCPClientSpec(
            client_name="claude-code",
            path_factory=lambda: Path.home() / ".claude" / "mcp.json",
            file_format="json",
            verification_steps=[
                "Run `claude mcp list`.",
                "Open Claude Code and run `/mcp`.",
                "Ask Claude Code to run `autoagent_status`.",
            ],
        ),
        "codex": MCPClientSpec(
            client_name="codex",
            path_factory=lambda: Path.home() / ".codex" / "config.toml",
            file_format="toml",
            verification_steps=[
                "Run `codex mcp list`.",
                "Run `codex mcp get autoagent`.",
                "Ask Codex to call `autoagent_status`.",
            ],
        ),
        "cursor": MCPClientSpec(
            client_name="cursor",
            path_factory=lambda: Path.cwd() / ".cursor" / "mcp.json",
            file_format="json",
            verification_steps=[
                "Restart Cursor.",
                "Confirm `autoagent` appears in Agent / Composer tools.",
                "Ask Cursor to run `autoagent_status`.",
            ],
        ),
        "windsurf": MCPClientSpec(
            client_name="windsurf",
            path_factory=lambda: Path.home() / ".codeium" / "windsurf" / "mcp_config.json",
            file_format="json",
            verification_steps=[
                "Open Windsurf Cascade.",
                "Open the MCP picker and confirm `autoagent` is enabled.",
                "Ask Windsurf to run `autoagent_status`.",
            ],
        ),
    }


def _backup_file(path: Path) -> Path | None:
    """Back up the existing config before rewriting it."""
    if not path.exists():
        return None
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    backup_path = path.with_name(f"{path.name}.bak.{timestamp}")
    shutil.copy2(path, backup_path)
    return backup_path


def _load_json(path: Path) -> dict[str, Any]:
    """Load a JSON config file, defaulting to an empty object."""
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise click.ClickException(f"Could not parse JSON config at {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise click.ClickException(f"Expected JSON object at {path}")
    return payload


def _load_toml(path: Path) -> dict[str, Any]:
    """Load a TOML config file, defaulting to an empty object."""
    if not path.exists():
        return {}
    raw = path.read_bytes()
    if not raw.strip():
        return {}
    if tomllib is None:  # pragma: no cover - Python <3.11 fallback
        raise click.ClickException("Python tomllib support is required to edit Codex MCP config.")
    try:
        payload = tomllib.loads(raw.decode("utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        raise click.ClickException(f"Could not parse TOML config at {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise click.ClickException(f"Expected TOML table at {path}")
    return payload


def _format_toml_value(value: Any) -> str:
    """Render a Python value as TOML for the small config surface we write."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_format_toml_value(item) for item in value) + "]"
    return json.dumps(str(value))


def _dump_toml(data: dict[str, Any]) -> str:
    """Serialize a nested dict into TOML suitable for the Codex config file."""
    lines: list[str] = []

    def _write_table(table: dict[str, Any], prefix: tuple[str, ...]) -> None:
        scalars = {key: value for key, value in table.items() if not isinstance(value, dict)}
        children = {key: value for key, value in table.items() if isinstance(value, dict)}

        if prefix:
            lines.append(f"[{'.'.join(prefix)}]")
        for key, value in scalars.items():
            lines.append(f"{key} = {_format_toml_value(value)}")
        if prefix and (scalars or children):
            lines.append("")

        for key, child in children.items():
            _write_table(child, prefix + (key,))

    root_scalars = {key: value for key, value in data.items() if not isinstance(value, dict)}
    root_children = {key: value for key, value in data.items() if isinstance(value, dict)}

    for key, value in root_scalars.items():
        lines.append(f"{key} = {_format_toml_value(value)}")
    if root_scalars and root_children:
        lines.append("")

    for key, child in root_children.items():
        _write_table(child, (key,))

    return "\n".join(line for line in lines if line is not None).rstrip() + "\n"


def _merge_json_config(path: Path) -> None:
    """Merge the AutoAgent server into a JSON MCP config file."""
    payload = _load_json(path)
    servers = payload.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    payload["mcpServers"] = servers
    servers["autoagent"] = _autoagent_json_entry()
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _merge_toml_config(path: Path) -> None:
    """Merge the AutoAgent server into a TOML MCP config file."""
    payload = _load_toml(path)
    mcp_servers = payload.get("mcp_servers")
    if not isinstance(mcp_servers, dict):
        mcp_servers = {}
    payload["mcp_servers"] = mcp_servers
    mcp_servers["autoagent"] = _autoagent_toml_payload()["mcp_servers"]["autoagent"]
    path.write_text(_dump_toml(payload), encoding="utf-8")


def _has_autoagent_entry(spec: MCPClientSpec) -> bool:
    """Return whether the given client already exposes the AutoAgent server."""
    path = spec.path_factory()
    if not path.exists():
        return False
    if spec.file_format == "json":
        payload = _load_json(path)
        servers = payload.get("mcpServers", {})
        return isinstance(servers, dict) and "autoagent" in servers
    payload = _load_toml(path)
    servers = payload.get("mcp_servers", {})
    return isinstance(servers, dict) and "autoagent" in servers


def _write_client_config(spec: MCPClientSpec) -> tuple[Path, Path | None]:
    """Create or update a client MCP config file for AutoAgent."""
    path = spec.path_factory()
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = _backup_file(path)
    if spec.file_format == "json":
        _merge_json_config(path)
    elif spec.file_format == "toml":
        _merge_toml_config(path)
    else:  # pragma: no cover - defensive
        raise click.ClickException(f"Unsupported MCP config format: {spec.file_format}")
    return path, backup_path


@click.group("mcp")
def mcp_group() -> None:
    """Configure AutoAgent MCP integration for supported coding tools."""


@mcp_group.command("init")
@click.argument("client_name", type=click.Choice(tuple(_client_specs().keys()), case_sensitive=False))
def init_client(client_name: str) -> None:
    """Write AutoAgent MCP config for a supported client."""
    spec = _client_specs()[client_name.lower()]
    config_path, backup_path = _write_client_config(spec)

    click.echo(f"Configured AutoAgent MCP for {spec.client_name}.")
    click.echo(f"Config path: {config_path}")
    if backup_path is not None:
        click.echo(f"Backup: {backup_path}")
    click.echo("Verification:")
    for step in spec.verification_steps:
        click.echo(f"  - {step}")


@mcp_group.command("status")
def mcp_status() -> None:
    """Show which supported clients currently expose AutoAgent MCP config."""
    click.echo("MCP client status")
    for name, spec in _client_specs().items():
        status = "configured" if _has_autoagent_entry(spec) else "not configured"
        click.echo(f"  {name:<12} {status:<14} {spec.path_factory()}")
