"""``agentlab mcp test <name>`` — live connectivity probe for one MCP server.

This is the user-invoked counterpart to the intentionally no-probe
``/doctor`` MCP section: ``/doctor`` refuses to open network sockets
because a wedged server would hang a health check the operator wanted
to be cheap, so connectivity validation lives here instead where the
user is consenting to block on the probe.

The happy path exercises the entire P3 stack in one command:

    .mcp.json
       → cli.mcp.config.load_config           (typed pydantic parse)
       → cli.mcp.config.build_transport       (Stdio/Sse/Http factory)
       → Transport.connect()                  (opens the channel)
       → McpTransportClient.list_tools()      (JSON-RPC roundtrip)
       → rendered report                      (human or --json)
       → Transport.close()                    (always, best-effort)

The module exports:

* :class:`McpTestResult` — immutable outcome record, used both by the
  pure function and the JSON renderer.
* :func:`run_mcp_test` — the pure function. Factories for transport and
  client are injected so tests don't touch real servers.
* :func:`register_mcp_test_command` — Click adapter. Registered on the
  existing ``agentlab mcp`` group from :mod:`cli.mcp_runtime`.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import click

from cli.json_envelope import render_json_envelope
from cli.mcp.config import (
    HttpServerConfig,
    McpConfig,
    ServerConfig,
    SseServerConfig,
    StdioServerConfig,
    build_transport,
    load_config,
)


logger = logging.getLogger(__name__)


# Type aliases kept narrow on purpose — the probe only needs two
# operations from each collaborator. Anything richer would just make the
# test doubles louder.
TransportFactory = Callable[[ServerConfig], Any]
"""Build a Transport for a given typed server config. Production points
at :func:`cli.mcp.config.build_transport`; tests inject a fake."""

ClientFactory = Callable[[Any], Any]
"""Wrap a connected Transport in something with ``list_tools()``.
Production points at :class:`cli.mcp.transport_client.McpTransportClient`;
tests inject a fake."""


@dataclass(frozen=True)
class McpTestResult:
    """Outcome of one :func:`run_mcp_test` call.

    ``ok`` mirrors the high-level success flag — both the transport
    connect and the ``tools/list`` roundtrip succeeded. ``error`` carries
    a short, operator-friendly description on failure (never ``None``
    when ``ok`` is ``False``, and always ``None`` when ``ok`` is
    ``True``)."""

    ok: bool
    server_name: str
    transport_type: str | None
    tool_count: int
    tool_names: tuple[str, ...]
    latency_seconds: float | None
    error: str | None


def _transport_label(config: ServerConfig) -> str:
    """Map typed config class to the canonical ``.mcp.json`` transport string."""
    if isinstance(config, StdioServerConfig):
        return "stdio"
    if isinstance(config, SseServerConfig):
        return "sse"
    if isinstance(config, HttpServerConfig):
        return "streamable-http"
    return "unknown"


def run_mcp_test(
    name: str,
    *,
    root: Path,
    transport_factory: TransportFactory = build_transport,
    client_factory: ClientFactory | None = None,
    timeout: float = 10.0,
) -> McpTestResult:
    """Probe one configured MCP server and report the outcome.

    The function never raises — every failure (missing server, malformed
    config, connect exception, tools/list exception) surfaces as a
    failing :class:`McpTestResult`. This keeps the CLI layer simple: a
    single branch on ``result.ok`` decides the exit code."""

    # 1. Load config. ------------------------------------------------------
    config_path = root / ".mcp.json"
    try:
        config: McpConfig = load_config(config_path)
    except FileNotFoundError:
        return McpTestResult(
            ok=False,
            server_name=name,
            transport_type=None,
            tool_count=0,
            tool_names=(),
            latency_seconds=None,
            error=f"No .mcp.json found at {config_path}",
        )
    except Exception as exc:
        return McpTestResult(
            ok=False,
            server_name=name,
            transport_type=None,
            tool_count=0,
            tool_names=(),
            latency_seconds=None,
            error=f"Failed to load {config_path}: {exc}",
        )

    # 2. Look up the named server. ----------------------------------------
    servers = config.mcp_servers
    if name not in servers:
        configured = ", ".join(sorted(servers)) or "<none>"
        return McpTestResult(
            ok=False,
            server_name=name,
            transport_type=None,
            tool_count=0,
            tool_names=(),
            latency_seconds=None,
            error=f"No MCP server named '{name}' in .mcp.json (configured: {configured})",
        )

    server_cfg = servers[name]
    transport_label = _transport_label(server_cfg)

    # 3. Build transport + probe. -----------------------------------------
    #    We wrap connect → list_tools → close in one try/except so the
    #    close() call always runs via finally. Any failure point produces
    #    a single, tidy error string for the operator.
    if client_factory is None:
        # Lazy import — production callers go through this branch, but the
        # symbol isn't needed for the tests (which inject a fake client).
        from cli.mcp.transport_client import McpTransportClient

        def client_factory(transport: Any) -> Any:
            return McpTransportClient(transport=transport, timeout=timeout)

    transport = transport_factory(server_cfg)
    started = time.monotonic()
    try:
        try:
            transport.connect()
        except Exception as exc:
            return McpTestResult(
                ok=False,
                server_name=name,
                transport_type=transport_label,
                tool_count=0,
                tool_names=(),
                latency_seconds=None,
                error=f"Connect failed: {exc}",
            )

        try:
            client = client_factory(transport)
            tools = client.list_tools()
        except Exception as exc:
            return McpTestResult(
                ok=False,
                server_name=name,
                transport_type=transport_label,
                tool_count=0,
                tool_names=(),
                latency_seconds=None,
                error=f"tools/list failed: {exc}",
            )

        tool_names = tuple(
            str(t.get("name", "")) for t in tools if isinstance(t, dict) and t.get("name")
        )
        return McpTestResult(
            ok=True,
            server_name=name,
            transport_type=transport_label,
            tool_count=len(tool_names),
            tool_names=tool_names,
            latency_seconds=time.monotonic() - started,
            error=None,
        )
    finally:
        # Best-effort close — never surface a close-time error, we've
        # already recorded the interesting outcome above.
        try:
            transport.close()
        except Exception:  # pragma: no cover - close errors are not interesting
            logger.debug("Transport close failed during mcp test", exc_info=True)


# ---------------------------------------------------------------------------
# Click adapter
# ---------------------------------------------------------------------------


def _render_human(result: McpTestResult) -> str:
    """Human-readable multi-line report. Matches the tone of other
    ``agentlab mcp`` commands — plain lines, two-space indent for
    details, no ANSI colour in the base renderer (callers add colour)."""
    lines: list[str] = []
    if result.ok:
        lines.append(f"MCP server '{result.server_name}': OK")
        lines.append(f"  Transport: {result.transport_type}")
        lines.append(f"  {result.tool_count} tool(s) advertised")
        if result.tool_names:
            # Keep the preview short — an MCP server with 40 tools would
            # otherwise blow past a terminal screen.
            preview = ", ".join(result.tool_names[:8])
            suffix = "" if len(result.tool_names) <= 8 else f", ... (+{len(result.tool_names) - 8} more)"
            lines.append(f"  Tools: {preview}{suffix}")
        if result.latency_seconds is not None:
            lines.append(f"  Latency: {result.latency_seconds*1000:.0f} ms")
    else:
        lines.append(f"MCP server '{result.server_name}': FAILED")
        if result.transport_type is not None:
            lines.append(f"  Transport: {result.transport_type}")
        lines.append(f"  Error: {result.error}")
    return "\n".join(lines)


def register_mcp_test_command(
    group: click.Group,
    *,
    root_factory: Callable[[], Path] = lambda: Path("."),
    transport_factory: TransportFactory = build_transport,
    client_factory: ClientFactory | None = None,
) -> None:
    """Attach ``test`` to the existing ``agentlab mcp`` click group.

    Separated from the existing :func:`cli.mcp_runtime.register_runtime_commands`
    because it depends on the typed-config stack (``cli.mcp.config``)
    that the other workspace runtime commands don't — keeping them apart
    lets an older vendored copy of ``mcp_runtime`` still register without
    pulling in the transport machinery."""

    @group.command("test")
    @click.argument("name")
    @click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
    @click.option(
        "--timeout",
        type=float,
        default=10.0,
        show_default=True,
        help="Probe timeout in seconds (connect + tools/list).",
    )
    def test_cmd(name: str, json_output: bool, timeout: float) -> None:
        """Probe a configured MCP server (connect + tools/list)."""
        result = run_mcp_test(
            name,
            root=root_factory(),
            transport_factory=transport_factory,
            client_factory=client_factory,
            timeout=timeout,
        )
        if json_output:
            data = {
                "ok": result.ok,
                "server_name": result.server_name,
                "transport_type": result.transport_type,
                "tool_count": result.tool_count,
                "tool_names": list(result.tool_names),
                "latency_seconds": result.latency_seconds,
                "error": result.error,
            }
            click.echo(
                render_json_envelope(
                    "ok" if result.ok else "error",
                    data,
                    next_command=None if result.ok else "agentlab mcp inspect " + name,
                )
            )
        else:
            click.echo(_render_human(result))
        if not result.ok:
            raise click.exceptions.Exit(code=1)


__all__ = [
    "McpTestResult",
    "TransportFactory",
    "ClientFactory",
    "run_mcp_test",
    "register_mcp_test_command",
]
