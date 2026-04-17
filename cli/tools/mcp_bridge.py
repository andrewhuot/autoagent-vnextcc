"""Bridge MCP-server tools into :class:`ToolRegistry`.

The workbench already manages MCP server config at :mod:`cli.mcp_runtime`
(workspace ``.mcp.json`` list + CLI commands to add/remove servers).
This module takes that list and produces :class:`Tool` subclasses the
LLM can invoke directly — closing the gap where an MCP server was
configured but its tools weren't in the registry.

Design decisions:

* **Dynamic Tool subclasses.** Each MCP tool gets its own class rather
  than one generic ``McpTool`` with a dispatcher — this keeps the tool
  name, schema, and permission action distinct per tool, so rules in
  ``settings.json`` can target a specific MCP tool without broad
  wildcards.
* **Transport-agnostic client.** The bridge accepts any object that
  implements :class:`McpClient` (list_tools + call_tool). Production
  will supply the stdio-based ``mcp`` SDK client; tests pass a fake.
  The SDK import stays lazy so the bridge loads even when the user
  hasn't installed ``mcp``.
* **Errors never crash registration.** A broken server surfaces a
  warning on :attr:`McpBridge.warnings` and its tools are skipped —
  the workbench keeps running with the servers that do work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Protocol

from cli.tools.base import Tool, ToolContext, ToolResult
from cli.tools.registry import ToolRegistry


PERMISSION_ACTION_PREFIX = "tool:mcp"
"""Permission-action prefix for MCP tools. Rules like
``tool:mcp:notion:*`` target every tool from the ``notion`` server;
``tool:mcp:github:search_issues`` targets one. Kept as a module-level
constant so the REPL can display the schema to users authoring rules."""


class McpClient(Protocol):
    """Minimal transport-agnostic MCP client contract.

    Production implementations wrap the ``mcp`` SDK; tests pass a fake.
    The bridge only needs two operations, which keeps the surface small
    and mock-friendly."""

    def list_tools(self) -> list[dict[str, Any]]:  # pragma: no cover - protocol
        """Return tool descriptors for ``name / description / inputSchema``."""
        ...

    def call_tool(
        self, name: str, arguments: Mapping[str, Any]
    ) -> dict[str, Any]:  # pragma: no cover - protocol
        """Call a tool and return its structured result.

        Expected shape: ``{"content": [{"type": "text", "text": "..."}], "isError": bool}``.
        The bridge flattens this to :class:`ToolResult`."""
        ...


McpClientFactory = Callable[["McpServerSpec"], McpClient]
"""Callable that returns an :class:`McpClient` for a given server spec.

Keeping this as an injectable factory means the bridge module doesn't
import the live SDK at module load time. Production factories spawn the
server via stdio; tests inject a fake that returns a pre-populated
:class:`FakeMcpClient`."""


@dataclass
class McpServerSpec:
    """Description of one MCP server the bridge should connect to.

    Mirrors the ``.mcp.json`` schema. The full workspace config comes
    from :func:`cli.mcp_runtime.list_mcp_servers`; the bridge accepts it
    as a list of these dataclasses so non-config call sites (tests,
    programmatic setup) can build spec lists directly."""

    name: str
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class McpToolSpec:
    """Descriptor returned from an MCP server's ``list_tools``."""

    server_name: str
    name: str
    description: str
    input_schema: dict[str, Any]

    @property
    def qualified_name(self) -> str:
        """Collision-safe id — ``mcp__<server>__<tool>``.

        The prefix ensures no MCP tool shadows a bundled tool and the
        double underscore avoids clashing with legitimate tool names that
        contain a single underscore."""
        return f"mcp__{self.server_name}__{self.name}"


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------


@dataclass
class McpBridge:
    """Bridge that registers MCP tools into a :class:`ToolRegistry`.

    Usage::

        bridge = McpBridge(client_factory=my_factory)
        bridge.register_all(specs, tool_registry)

    Clients produced during registration are cached by server name so
    ``call_tool`` invocations reuse the connection. Failures during
    ``list_tools`` for one server do not affect the others."""

    client_factory: McpClientFactory
    clients: dict[str, McpClient] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    registered_tools: list[str] = field(default_factory=list)

    def register_all(
        self,
        servers: Iterable[McpServerSpec],
        tool_registry: ToolRegistry,
    ) -> list[str]:
        """Register every tool from every server. Return the qualified
        names that landed in the registry.

        The registration order follows the iteration order of ``servers``
        so users who sort their config alphabetically get predictable
        command-listing output downstream."""
        for spec in servers:
            try:
                client = self.client_factory(spec)
                self.clients[spec.name] = client
                tools = client.list_tools() or []
            except Exception as exc:  # noqa: BLE001
                # Per-server resilience: one broken server must not keep
                # the rest of the MCP fleet out of the registry.
                self.warnings.append(
                    f"MCP server {spec.name!r} unavailable: {exc}"
                )
                continue

            for descriptor in tools:
                try:
                    tool_spec = _coerce_tool_spec(spec.name, descriptor)
                except ValueError as exc:
                    self.warnings.append(
                        f"MCP server {spec.name!r} sent invalid tool descriptor: {exc}"
                    )
                    continue
                try:
                    tool = _build_mcp_tool(tool_spec, self._client_lookup)
                    tool_registry.register(tool)
                except Exception as exc:  # noqa: BLE001
                    self.warnings.append(
                        f"Failed to register MCP tool {tool_spec.qualified_name!r}: {exc}"
                    )
                    continue
                self.registered_tools.append(tool_spec.qualified_name)
        return list(self.registered_tools)

    def _client_lookup(self, server_name: str) -> McpClient:
        return self.clients[server_name]


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------


def _build_mcp_tool(
    spec: McpToolSpec,
    client_lookup: Callable[[str], McpClient],
) -> Tool:
    """Return a :class:`Tool` instance backed by an MCP server call.

    We build a fresh subclass per spec so ``tool.name`` and
    ``tool.input_schema`` are the MCP-reported values — not a shared
    dispatcher that would look the schema up at invocation time."""

    class _McpTool(Tool):
        name = spec.qualified_name
        description = spec.description or f"MCP tool from {spec.server_name}"
        input_schema = spec.input_schema or {"type": "object", "properties": {}}

        # Read-only is unknowable without extra metadata; default to
        # False so the permission dialog fires. MCP server authors who
        # want a tool to auto-allow can add a dedicated allow rule in
        # ``settings.json`` — safer than assuming.
        read_only = False
        is_concurrency_safe = False

        _server_name = spec.server_name
        _tool_name = spec.name

        def permission_action(self, tool_input: Mapping[str, Any]) -> str:
            return f"{PERMISSION_ACTION_PREFIX}:{self._server_name}:{self._tool_name}"

        def render_preview(self, tool_input: Mapping[str, Any]) -> str:
            # Truncate long input dumps so the permission dialog stays
            # scannable — 160 chars is enough for typical payload peek.
            input_str = str(tool_input)
            if len(input_str) > 160:
                input_str = input_str[:157] + "…"
            return f"MCP {self._server_name}.{self._tool_name}({input_str})"

        def run(self, tool_input: Mapping[str, Any], context: ToolContext) -> ToolResult:
            try:
                client = client_lookup(self._server_name)
            except KeyError:
                return ToolResult.failure(
                    f"MCP server {self._server_name!r} is no longer connected."
                )
            try:
                response = client.call_tool(self._tool_name, dict(tool_input))
            except Exception as exc:  # noqa: BLE001 - surface to model
                return ToolResult.failure(
                    f"MCP call to {self._server_name}.{self._tool_name} failed: {exc}"
                )
            return _coerce_response(response)

    _McpTool.__name__ = spec.qualified_name
    _McpTool.__qualname__ = spec.qualified_name
    return _McpTool()


def _coerce_tool_spec(server_name: str, descriptor: Mapping[str, Any]) -> McpToolSpec:
    """Validate a server-supplied tool descriptor.

    The MCP spec uses ``inputSchema`` (camelCase); we accept the Pythonic
    ``input_schema`` too so tests and legacy clients both work. Missing
    ``name`` is a fatal descriptor error — without it we can't route
    calls back to the server."""
    if not isinstance(descriptor, Mapping):
        raise ValueError("descriptor is not a mapping")
    name = str(descriptor.get("name") or "").strip()
    if not name:
        raise ValueError("descriptor missing 'name'")
    description = str(descriptor.get("description") or "")
    schema = descriptor.get("inputSchema") or descriptor.get("input_schema")
    if not isinstance(schema, Mapping) or not schema:
        # Empty or missing schemas would let the model submit anything;
        # fall back to a permissive object schema so tools still receive
        # a well-formed call rather than refusing at the boundary.
        schema = {"type": "object", "properties": {}}
    return McpToolSpec(
        server_name=server_name,
        name=name,
        description=description,
        input_schema=dict(schema),
    )


def _coerce_response(response: Any) -> ToolResult:
    """Flatten an MCP ``call_tool`` response into a :class:`ToolResult`.

    MCP servers return a list of content blocks (text, image, resource);
    we concatenate text blocks and wrap image/resource blocks as a
    structured placeholder line so the model at least knows something
    was returned. An ``isError`` flag maps to a ToolResult failure."""
    if isinstance(response, Mapping):
        is_error = bool(response.get("isError") or response.get("is_error"))
        content = response.get("content")
    else:
        is_error = False
        content = response

    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = _flatten_content_blocks(content)
    elif isinstance(content, Mapping):
        text = _flatten_content_blocks([content])
    else:
        text = str(content or "")

    if is_error:
        return ToolResult.failure(text or "MCP tool reported an error.")
    return ToolResult.success(text or "(no content)")


def _flatten_content_blocks(blocks: Iterable[Any]) -> str:
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, Mapping):
            block_type = block.get("type", "text")
            if block_type == "text":
                parts.append(str(block.get("text", "")))
            elif block_type == "image":
                parts.append(f"[image: {block.get('mimeType', 'unknown')}]")
            elif block_type == "resource":
                uri = block.get("uri") or block.get("resource", {}).get("uri", "")
                parts.append(f"[resource: {uri}]")
            else:
                parts.append(f"[{block_type} block]")
        else:
            parts.append(str(block))
    return "\n".join(part for part in parts if part)


# ---------------------------------------------------------------------------
# Workspace integration
# ---------------------------------------------------------------------------


def load_specs_from_workspace(workspace_root: str | Any = ".") -> list[McpServerSpec]:
    """Build :class:`McpServerSpec` records from ``.mcp.json``.

    Lives here (rather than in :mod:`cli.mcp_runtime`) because the
    dataclass is bridge-specific — keeping the MCP runtime module free
    of tool-registry concerns preserves its boundary."""
    from cli.mcp_runtime import list_mcp_servers

    specs: list[McpServerSpec] = []
    for entry in list_mcp_servers(workspace_root):
        # The stdio bridge spec cannot represent SSE / Streamable-HTTP
        # servers (no command to spawn). Skip non-stdio entries here;
        # remote transports are wired through cli.mcp.config.build_transport
        # by the parts of the stack that speak Transport rather than
        # McpServerSpec.
        if entry.get("transport", "stdio") != "stdio":
            continue
        specs.append(
            McpServerSpec(
                name=str(entry.get("name") or ""),
                command=str(entry.get("command") or ""),
                args=list(entry.get("args") or []),
                env={str(k): str(v) for k, v in (entry.get("env") or {}).items()},
            )
        )
    return specs


__all__ = [
    "McpBridge",
    "McpClient",
    "McpClientFactory",
    "McpServerSpec",
    "McpToolSpec",
    "PERMISSION_ACTION_PREFIX",
    "load_specs_from_workspace",
]
