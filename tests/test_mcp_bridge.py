"""Tests for the Phase-F.3 MCP tool bridge."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import pytest

from cli.permissions import PermissionManager
from cli.tools.base import ToolContext
from cli.tools.executor import execute_tool_call
from cli.tools.mcp_bridge import (
    PERMISSION_ACTION_PREFIX,
    McpBridge,
    McpServerSpec,
    McpToolSpec,
    _coerce_response,
    _coerce_tool_spec,
    _flatten_content_blocks,
    load_specs_from_workspace,
)
from cli.tools.registry import ToolRegistry
from cli.workbench_app.permission_dialog import DialogChoice, DialogOutcome


# ---------------------------------------------------------------------------
# Fake MCP client
# ---------------------------------------------------------------------------


@dataclass
class FakeMcpClient:
    """In-memory MCP client for tests.

    Records every ``call_tool`` invocation so tests can assert the bridge
    forwarded inputs unchanged."""

    tools: list[dict[str, Any]]
    responses: dict[str, Any] = field(default_factory=dict)
    raise_on_list: Exception | None = None
    raise_on_call: Exception | None = None
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def list_tools(self) -> list[dict[str, Any]]:
        if self.raise_on_list is not None:
            raise self.raise_on_list
        return list(self.tools)

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        self.calls.append((name, dict(arguments)))
        if self.raise_on_call is not None:
            raise self.raise_on_call
        return self.responses.get(name, {"content": [{"type": "text", "text": "ok"}]})


# ---------------------------------------------------------------------------
# Descriptor coercion
# ---------------------------------------------------------------------------


def test_coerce_tool_spec_accepts_camel_case_schema() -> None:
    spec = _coerce_tool_spec(
        "github",
        {
            "name": "search",
            "description": "Search GitHub",
            "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}},
        },
    )
    assert spec.qualified_name == "mcp__github__search"
    assert spec.input_schema["properties"]["q"] == {"type": "string"}


def test_coerce_tool_spec_accepts_snake_case_schema() -> None:
    spec = _coerce_tool_spec(
        "github", {"name": "list", "description": "", "input_schema": {"type": "object"}}
    )
    assert spec.name == "list"


def test_coerce_tool_spec_rejects_missing_name() -> None:
    with pytest.raises(ValueError):
        _coerce_tool_spec("srv", {"description": "no name"})


def test_coerce_tool_spec_defaults_schema_when_missing() -> None:
    spec = _coerce_tool_spec("srv", {"name": "bare"})
    assert spec.input_schema == {"type": "object", "properties": {}}


# ---------------------------------------------------------------------------
# Response flattening
# ---------------------------------------------------------------------------


def test_coerce_response_text_blocks_concatenate() -> None:
    result = _coerce_response(
        {
            "content": [
                {"type": "text", "text": "line one"},
                {"type": "text", "text": "line two"},
            ]
        }
    )
    assert result.ok
    assert result.content == "line one\nline two"


def test_coerce_response_handles_image_block() -> None:
    result = _coerce_response(
        {"content": [{"type": "image", "mimeType": "image/png", "data": "abc"}]}
    )
    assert result.ok
    assert "[image: image/png]" in result.content


def test_coerce_response_is_error_flag_maps_to_failure() -> None:
    result = _coerce_response(
        {
            "isError": True,
            "content": [{"type": "text", "text": "boom"}],
        }
    )
    assert not result.ok
    assert "boom" in result.content


def test_coerce_response_plain_string_passes_through() -> None:
    result = _coerce_response("hello")
    assert result.ok
    assert result.content == "hello"


def test_flatten_content_blocks_resource_ref() -> None:
    flat = _flatten_content_blocks(
        [{"type": "resource", "uri": "file:///tmp/x"}]
    )
    assert "[resource: file:///tmp/x]" in flat


# ---------------------------------------------------------------------------
# Bridge registration
# ---------------------------------------------------------------------------


def test_bridge_registers_tools_per_server() -> None:
    client_factory_calls: list[str] = []

    def factory(spec: McpServerSpec) -> FakeMcpClient:
        client_factory_calls.append(spec.name)
        if spec.name == "github":
            return FakeMcpClient(
                tools=[
                    {"name": "search", "description": "Search repos", "inputSchema": {"type": "object"}},
                    {"name": "list_prs", "description": "", "inputSchema": {"type": "object"}},
                ]
            )
        return FakeMcpClient(
            tools=[{"name": "get_page", "description": "", "inputSchema": {"type": "object"}}]
        )

    bridge = McpBridge(client_factory=factory)
    registry = ToolRegistry()
    registered = bridge.register_all(
        [McpServerSpec(name="github"), McpServerSpec(name="notion")],
        registry,
    )
    assert registered == [
        "mcp__github__search",
        "mcp__github__list_prs",
        "mcp__notion__get_page",
    ]
    assert set(client_factory_calls) == {"github", "notion"}
    assert len(registry.list()) == 3


def test_bridge_warns_when_server_list_tools_fails() -> None:
    def factory(spec: McpServerSpec) -> FakeMcpClient:
        if spec.name == "broken":
            return FakeMcpClient(tools=[], raise_on_list=RuntimeError("connection refused"))
        return FakeMcpClient(
            tools=[{"name": "ok", "description": "", "inputSchema": {}}]
        )

    bridge = McpBridge(client_factory=factory)
    registry = ToolRegistry()
    bridge.register_all(
        [McpServerSpec(name="broken"), McpServerSpec(name="healthy")],
        registry,
    )
    assert any("broken" in warning for warning in bridge.warnings)
    # Healthy server's tool still lands in the registry.
    assert registry.has("mcp__healthy__ok")


def test_bridge_skips_malformed_descriptor() -> None:
    def factory(spec: McpServerSpec) -> FakeMcpClient:
        return FakeMcpClient(
            tools=[
                {"description": "missing name"},
                {"name": "valid", "description": "", "inputSchema": {}},
            ]
        )

    bridge = McpBridge(client_factory=factory)
    registry = ToolRegistry()
    bridge.register_all([McpServerSpec(name="srv")], registry)
    assert registry.has("mcp__srv__valid")
    assert registry.has("mcp__srv__missing") is False
    assert any("invalid tool descriptor" in warning for warning in bridge.warnings)


# ---------------------------------------------------------------------------
# Dynamic tool behaviour
# ---------------------------------------------------------------------------


def test_mcp_tool_permission_action_uses_server_and_tool() -> None:
    spec = McpToolSpec(
        server_name="notion",
        name="create_page",
        description="Create a page",
        input_schema={"type": "object"},
    )
    bridge = McpBridge(
        client_factory=lambda _spec: FakeMcpClient(tools=[spec.__dict__]),
    )
    registry = ToolRegistry()
    bridge.register_all(
        [McpServerSpec(name="notion")],
        registry,
    )
    # We didn't register via the real tool list — do it manually.
    # (The real path is exercised in the registration tests above.)

    fake_client = FakeMcpClient(tools=[])
    bridge.clients["notion"] = fake_client
    from cli.tools.mcp_bridge import _build_mcp_tool

    tool = _build_mcp_tool(spec, lambda name: bridge.clients[name])
    action = tool.permission_action({})
    assert action == f"{PERMISSION_ACTION_PREFIX}:notion:create_page"


def test_mcp_tool_run_forwards_input_and_returns_content(tmp_path: Path) -> None:
    responses = {"echo": {"content": [{"type": "text", "text": "heard: hello"}]}}
    client = FakeMcpClient(
        tools=[{"name": "echo", "description": "", "inputSchema": {"type": "object"}}],
        responses=responses,
    )
    bridge = McpBridge(client_factory=lambda _spec: client)
    registry = ToolRegistry()
    bridge.register_all([McpServerSpec(name="demo")], registry)

    (tmp_path / ".agentlab").mkdir()
    ctx = ToolContext(workspace_root=tmp_path)
    tool = registry.get("mcp__demo__echo")
    result = tool.run({"msg": "hello"}, ctx)
    assert result.ok
    assert "heard: hello" in result.content
    assert client.calls == [("echo", {"msg": "hello"})]


def test_mcp_tool_run_surfaces_transport_error(tmp_path: Path) -> None:
    client = FakeMcpClient(
        tools=[{"name": "crash", "description": "", "inputSchema": {"type": "object"}}],
        raise_on_call=RuntimeError("socket closed"),
    )
    bridge = McpBridge(client_factory=lambda _spec: client)
    registry = ToolRegistry()
    bridge.register_all([McpServerSpec(name="demo")], registry)

    (tmp_path / ".agentlab").mkdir()
    ctx = ToolContext(workspace_root=tmp_path)
    tool = registry.get("mcp__demo__crash")
    result = tool.run({}, ctx)
    assert not result.ok
    assert "socket closed" in result.content


# ---------------------------------------------------------------------------
# End-to-end via execute_tool_call
# ---------------------------------------------------------------------------


def test_execute_tool_call_routes_through_mcp_bridge(tmp_path: Path) -> None:
    client = FakeMcpClient(
        tools=[{"name": "echo", "description": "", "inputSchema": {"type": "object"}}],
        responses={"echo": {"content": [{"type": "text", "text": "pong"}]}},
    )
    bridge = McpBridge(client_factory=lambda _spec: client)
    registry = ToolRegistry()
    bridge.register_all([McpServerSpec(name="demo")], registry)

    (tmp_path / ".agentlab").mkdir()
    ctx = ToolContext(workspace_root=tmp_path)
    manager = PermissionManager(root=tmp_path)

    def approve(*_a, **_k):
        return DialogOutcome(
            choice=DialogChoice.APPROVE, allow=True, persist_rule=None, persist_scope=None
        )

    execution = execute_tool_call(
        "mcp__demo__echo",
        {"message": "ping"},
        registry=registry,
        permissions=manager,
        context=ctx,
        dialog_runner=approve,
    )
    assert execution.decision.value == "allow"
    assert execution.result is not None
    assert "pong" in execution.result.content


# ---------------------------------------------------------------------------
# Workspace loader reads .mcp.json
# ---------------------------------------------------------------------------


def test_load_specs_from_workspace_parses_mcp_json(tmp_path: Path) -> None:
    (tmp_path / ".mcp.json").write_text(
        """{
            "mcpServers": {
                "notion": {"command": "notion-mcp", "args": ["--stdio"], "env": {"NOTION_TOKEN": "abc"}},
                "github": {"command": "github-mcp"}
            }
        }""",
        encoding="utf-8",
    )
    specs = load_specs_from_workspace(tmp_path)
    names = sorted(spec.name for spec in specs)
    assert names == ["github", "notion"]
    notion = next(spec for spec in specs if spec.name == "notion")
    assert notion.command == "notion-mcp"
    assert notion.args == ["--stdio"]
    assert notion.env == {"NOTION_TOKEN": "abc"}


def test_load_specs_from_workspace_handles_missing_file(tmp_path: Path) -> None:
    assert load_specs_from_workspace(tmp_path) == []
