"""Production :class:`McpClientFactory` for the workbench MCP bridge.

The bridge (:mod:`cli.tools.mcp_bridge`) accepts any callable that takes
an :class:`McpServerSpec` and returns something with ``list_tools`` /
``call_tool``. For a long time the workbench never actually supplied
one at the :func:`build_workbench_runtime` boundary, so even a
well-formed ``.mcp.json`` with a hosted server never registered its
tools with the LLM. :func:`build_live_client_factory` fills that gap.

What the factory does, per call:

1. Look up the spec by name in a typed ``McpConfig`` loaded up front
   from the workspace's ``.mcp.json``.
2. Build the concrete :class:`Transport` via
   :func:`cli.mcp.config.build_transport`.
3. If the transport is **hosted** (SSE or Streamable-HTTP), wrap it in
   a :class:`ReconnectingTransport` so transient drops don't kill the
   workbench session. Stdio servers are left raw — the OS supervises
   the subprocess and a wrapper would just add a poll thread with
   nothing useful to do.
4. Connect the (possibly wrapped) transport and hand it to
   :class:`McpTransportClient`.

Everything that can vary is injectable: the transport factory, the
reconnect wrapper. Production wires real implementations; tests drop
in fakes and verify the wiring.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from cli.mcp.config import (
    HttpServerConfig,
    McpConfig,
    ServerConfig,
    SseServerConfig,
    StdioServerConfig,
    build_transport,
    load_config,
)
from cli.mcp.reconnect import ReconnectingTransport
from cli.mcp.transport_client import McpTransportClient
from cli.tools.mcp_bridge import McpClient, McpServerSpec


TransportFactory = Callable[[ServerConfig], Any]
"""Build a concrete :class:`Transport` from a typed server config.
Production points at :func:`cli.mcp.config.build_transport`; tests inject
a fake that returns a deterministic stand-in."""

ReconnectWrapper = Callable[[Any], Any]
"""Wrap a hosted transport in a supervised reconnecter. Production
points at :class:`ReconnectingTransport`; tests replace this to assert
the wrapping decision without spawning a supervisor thread."""


def build_live_client_factory(
    *,
    workspace_root: Path,
    transport_factory: TransportFactory = build_transport,
    reconnect_wrapper: ReconnectWrapper | None = None,
    client_timeout: float = 10.0,
) -> Callable[[McpServerSpec], McpClient]:
    """Return a callable the bridge can use as its ``client_factory``.

    We load the typed MCP config once, up front, so subsequent calls
    (one per MCP server at bridge-register time) don't re-parse the
    JSON. The returned callable raises :class:`KeyError` if it's asked
    for a name the workspace config doesn't know about — an explicit
    error is friendlier than lazily failing later with a silent empty
    tool list.
    """
    config: McpConfig = load_config(workspace_root / ".mcp.json")

    def _default_wrapper(inner: Any) -> Any:
        # ReconnectingTransport is a dataclass with only ``inner`` as a
        # required positional — defaults for the rest match the upstream
        # Claude Code client's ping cadence and backoff shape.
        return ReconnectingTransport(inner=inner)

    wrapper: ReconnectWrapper = reconnect_wrapper or _default_wrapper

    def factory(spec: McpServerSpec) -> McpClient:
        if spec.name not in config.mcp_servers:
            configured = ", ".join(sorted(config.mcp_servers)) or "<none>"
            raise KeyError(
                f"No MCP server named {spec.name!r} in .mcp.json "
                f"(configured: {configured})"
            )
        server_cfg = config.mcp_servers[spec.name]
        transport = transport_factory(server_cfg)

        # Only hosted transports benefit from supervised reconnect.
        # Stdio subprocesses are OS-supervised — a dead child shows up
        # as a closed pipe, and the bridge's per-server error handling
        # already surfaces that as a registration warning. Wrapping
        # stdio would just add a background thread with nothing useful
        # to do.
        if isinstance(server_cfg, (SseServerConfig, HttpServerConfig)):
            transport = wrapper(transport)

        # Connect before returning — the bridge calls list_tools
        # immediately and has no retry of its own. If connect raises,
        # the bridge catches it at the per-server boundary and records
        # a warning rather than failing all registrations.
        transport.connect()
        return McpTransportClient(transport=transport, timeout=client_timeout)

    return factory


__all__ = [
    "ReconnectWrapper",
    "TransportFactory",
    "build_live_client_factory",
]
