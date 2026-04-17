"""Typed pydantic config for `.mcp.json`.

The on-disk `.mcp.json` file has to stay compatible with Claude Code so
we preserve the top-level ``mcpServers`` key and the legacy entry shape
(``{command, args, env}`` with no ``transport`` field, which means
stdio). On top of that legacy baseline we add an explicit ``transport``
discriminator so a single file can describe stdio, SSE, and Streamable
HTTP servers side-by-side.

Backwards compatibility is handled by a pre-validator on
:class:`McpConfig` that injects ``transport: "stdio"`` into any server
entry missing the key before the discriminated-union machinery runs.
Round-tripping: :func:`save_config` always writes the transport field
explicitly (even for stdio) so ambiguity never surfaces in a file written
by modern agentlab. Hand-authored files and files written by previous
agentlab versions still load via the legacy injector.

The discriminator key is ``transport`` (literal string) rather than a
structural union so pydantic gives us a precise "this server's
``transport`` was X, expected one of Y" error message rather than a
generic union-mismatch blob.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from cli.mcp.transports import (
    HttpStreamableTransport,
    SseTransport,
    StdioTransport,
    Transport,
)


class StdioServerConfig(BaseModel):
    """Local subprocess transport — the original `.mcp.json` shape."""

    transport: Literal["stdio"] = "stdio"
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)


class SseServerConfig(BaseModel):
    """HTTP + Server-Sent-Events transport."""

    transport: Literal["sse"]
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    ping_interval_seconds: float = 30.0


class HttpServerConfig(BaseModel):
    """MCP Streamable-HTTP transport."""

    transport: Literal["streamable-http"]
    url: str
    headers: dict[str, str] = Field(default_factory=dict)


ServerConfig = Annotated[
    Union[StdioServerConfig, SseServerConfig, HttpServerConfig],
    Field(discriminator="transport"),
]


class McpConfig(BaseModel):
    """Typed wrapper around `.mcp.json`.

    Accepts either ``mcp_servers`` or ``mcpServers`` on construction
    (``populate_by_name``), but serialises with ``by_alias=True`` in
    :func:`save_config` so the on-disk file keeps the Claude-Code-
    compatible ``mcpServers`` key.
    """

    model_config = ConfigDict(populate_by_name=True)

    mcp_servers: dict[str, ServerConfig] = Field(
        default_factory=dict, alias="mcpServers"
    )

    @model_validator(mode="before")
    @classmethod
    def _inject_legacy_stdio_transport(cls, data: Any) -> Any:
        """Inject ``transport: "stdio"`` into legacy-shape server entries.

        A legacy entry is any dict missing the ``transport`` key — those
        are stdio servers written by an older agentlab / Claude Code /
        hand-authored files. Rather than relying on the discriminated
        union to guess the right branch we make the intent explicit here
        so the validator downstream sees a well-formed entry and can
        surface precise errors like "command is required" instead of a
        union-mismatch firehose.
        """
        if not isinstance(data, dict):
            return data
        servers_key = "mcpServers" if "mcpServers" in data else "mcp_servers"
        servers = data.get(servers_key)
        if not isinstance(servers, dict):
            return data
        patched: dict[str, Any] = {}
        for name, entry in servers.items():
            if isinstance(entry, dict) and "transport" not in entry:
                entry = {**entry, "transport": "stdio"}
            patched[name] = entry
        data = dict(data)
        data[servers_key] = patched
        return data


def load_config(path: Path) -> McpConfig:
    """Parse `.mcp.json` at ``path``.

    A missing file yields an empty :class:`McpConfig`. Malformed JSON or
    a pydantic validation failure is re-raised as :class:`ValueError`
    with a message that names the offending server so operators can find
    the bad entry without re-parsing the traceback.
    """
    if not path.exists():
        return McpConfig()
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return McpConfig()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        # Tolerate top-level lists / scalars from hand-edits by returning
        # an empty config rather than exploding — matches the legacy
        # loader's behaviour.
        return McpConfig()
    try:
        return McpConfig.model_validate(data)
    except ValidationError as exc:
        raise ValueError(_friendly_validation_message(path, exc)) from exc


def save_config(path: Path, config: McpConfig) -> None:
    """Persist ``config`` as `.mcp.json` at ``path``.

    We always write the ``transport`` field explicitly (including for
    stdio) so round-tripped files are unambiguous; legacy tools that
    only understand ``{command, args, env}`` still read stdio entries
    correctly because every other field is present and well-known.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = config.model_dump(by_alias=True, exclude_none=False)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def build_transport(server: ServerConfig) -> Transport:
    """Construct the concrete :class:`Transport` for a typed server config.

    The config model carries every knob the transport needs, so this
    factory deliberately takes no other arguments — callers that want
    the thing that should run don't have to remember any protocol-
    specific kwargs.
    """
    if isinstance(server, StdioServerConfig):
        return StdioTransport(
            command=[server.command],
            args=list(server.args),
            env=dict(server.env),
        )
    if isinstance(server, SseServerConfig):
        return SseTransport(
            url=server.url,
            ping_interval_seconds=server.ping_interval_seconds,
        )
    if isinstance(server, HttpServerConfig):
        return HttpStreamableTransport(url=server.url)
    raise TypeError(f"Unsupported server config: {type(server).__name__}")


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _friendly_validation_message(path: Path, exc: ValidationError) -> str:
    """Turn a pydantic ValidationError into an operator-friendly string.

    The first error's location path goes ``("mcpServers", <name>, ...)``
    which lets us surface the offending server name up front.
    """
    errors = exc.errors()
    if not errors:
        return f"Invalid MCP config at {path}: {exc}"
    first = errors[0]
    loc = first.get("loc", ())
    server_name: str | None = None
    for idx, token in enumerate(loc):
        if token in ("mcpServers", "mcp_servers") and idx + 1 < len(loc):
            nxt = loc[idx + 1]
            if isinstance(nxt, str):
                server_name = nxt
            break
    message = first.get("msg", "validation error")
    if server_name:
        return (
            f"Invalid MCP config at {path}: server '{server_name}' - {message}"
        )
    return f"Invalid MCP config at {path}: {message}"


__all__ = [
    "HttpServerConfig",
    "McpConfig",
    "ServerConfig",
    "SseServerConfig",
    "StdioServerConfig",
    "build_transport",
    "load_config",
    "save_config",
]
