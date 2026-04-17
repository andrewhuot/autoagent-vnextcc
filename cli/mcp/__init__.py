"""MCP transport + JSON-RPC client package.

This package hosts the transport-layer abstraction for MCP (Model Context
Protocol) servers. :mod:`cli.mcp.transports` defines the :class:`Transport`
Protocol; concrete transports (stdio today, HTTP/SSE tomorrow) live in
submodules. :mod:`cli.mcp.transport_client` wraps any :class:`Transport`
with a JSON-RPC client that satisfies the existing
:class:`cli.tools.mcp_bridge.McpClient` contract — keeping the new layer
strictly additive so existing bridge call sites stay untouched."""
