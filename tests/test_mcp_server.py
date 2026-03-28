"""Tests for MCP server — tool schemas, request handling, tool execution."""
from __future__ import annotations
import json
from mcp_server.server import handle_request
from mcp_server.tools import TOOL_REGISTRY
from mcp_server.types import MCPToolDef, MCPToolParam


class TestMCPTypes:
    def test_tool_def_to_schema(self):
        tool = MCPToolDef(
            name="test_tool",
            description="A test tool",
            parameters=[
                MCPToolParam(name="arg1", description="First arg", type="string", required=True),
                MCPToolParam(name="arg2", description="Second arg", type="integer"),
            ],
        )
        schema = tool.to_schema()
        assert schema["name"] == "test_tool"
        assert schema["description"] == "A test tool"
        assert "arg1" in schema["inputSchema"]["properties"]
        assert schema["inputSchema"]["required"] == ["arg1"]

    def test_tool_def_no_params(self):
        tool = MCPToolDef(name="simple", description="Simple tool")
        schema = tool.to_schema()
        assert schema["inputSchema"]["properties"] == {}


class TestMCPServer:
    def test_initialize(self):
        resp = handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert resp["id"] == 1
        assert resp["result"]["serverInfo"]["name"] == "autoagent"

    def test_tools_list(self):
        resp = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        assert resp["id"] == 2
        tools = resp["result"]["tools"]
        assert len(tools) >= 12  # 12 original + P0-10 build surface tools
        names = {t["name"] for t in tools}
        assert "autoagent_status" in names
        assert "autoagent_edit" in names
        assert "autoagent_diagnose" in names

    def test_tool_call_unknown(self):
        resp = handle_request({
            "jsonrpc": "2.0", "id": 3,
            "method": "tools/call",
            "params": {"name": "nonexistent", "arguments": {}},
        })
        assert "error" in resp

    def test_tool_call_replay(self):
        resp = handle_request({
            "jsonrpc": "2.0", "id": 4,
            "method": "tools/call",
            "params": {"name": "autoagent_replay", "arguments": {"limit": 5}},
        })
        assert resp["id"] == 4
        assert "result" in resp
        content = resp["result"]["content"]
        assert len(content) == 1
        assert content[0]["type"] == "text"

    def test_tool_call_diagnose(self):
        resp = handle_request({
            "jsonrpc": "2.0", "id": 5,
            "method": "tools/call",
            "params": {"name": "autoagent_diagnose", "arguments": {}},
        })
        assert "result" in resp
        text = resp["result"]["content"][0]["text"]
        data = json.loads(text)
        assert "session_id" in data
        assert "clusters" in data

    def test_unknown_method(self):
        resp = handle_request({"jsonrpc": "2.0", "id": 6, "method": "bogus/method", "params": {}})
        assert "error" in resp

    def test_notification_no_response(self):
        resp = handle_request({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        assert resp is None


class TestMCPToolRegistry:
    def test_registry_has_tools(self):
        assert len(TOOL_REGISTRY) >= 12  # 12 original + P0-10 build surface tools

    def test_all_tools_have_functions(self):
        for name, (fn, defn) in TOOL_REGISTRY.items():
            assert callable(fn), f"{name} function is not callable"
            assert isinstance(defn, MCPToolDef), f"{name} definition is not MCPToolDef"

    def test_tool_names_match(self):
        for name, (_, defn) in TOOL_REGISTRY.items():
            assert name == defn.name
