"""MCP Server — JSON-RPC 2.0 over stdio.

Implements the Model Context Protocol for AI coding tool integration.
Start with: autoagent mcp-server
"""
from __future__ import annotations

import json
import sys
from typing import Any

from mcp_server.tools import TOOL_REGISTRY
from mcp_server.resources import ResourceProvider
from mcp_server.prompts import PromptProvider
from mcp_server.transport import StreamableHttpTransport

_resource_provider = ResourceProvider()
_prompt_provider = PromptProvider()


def handle_request(request: dict[str, Any]) -> dict[str, Any]:
    """Handle a single JSON-RPC 2.0 request."""
    method = request.get("method", "")
    params = request.get("params", {})
    request_id = request.get("id")

    if method == "initialize":
        return _success(request_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"listChanged": False, "subscribe": False},
                "prompts": {"listChanged": False},
            },
            "serverInfo": {"name": "autoagent", "version": "1.0.0"},
        })

    if method == "tools/list":
        tools = [defn.to_schema() for _, defn in TOOL_REGISTRY.values()]
        return _success(request_id, {"tools": tools})

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        if tool_name not in TOOL_REGISTRY:
            return _error(request_id, -32601, f"Tool not found: {tool_name}")
        fn, _ = TOOL_REGISTRY[tool_name]
        try:
            result = fn(**arguments)
            content = json.dumps(result, default=str)
            return _success(request_id, {
                "content": [{"type": "text", "text": content}],
            })
        except Exception as exc:
            return _success(request_id, {
                "content": [{"type": "text", "text": f"Error: {exc}"}],
                "isError": True,
            })

    # ------------------------------------------------------------------
    # Resources
    # ------------------------------------------------------------------
    if method == "resources/list":
        all_resources = (
            _resource_provider.get_agent_configs()
            + _resource_provider.get_trace_summaries()
            + _resource_provider.get_eval_results()
            + _resource_provider.get_skill_catalog()
            + _resource_provider.get_dataset_stats()
        )
        return _success(request_id, {"resources": [r.to_dict() for r in all_resources]})

    if method == "resources/read":
        uri = params.get("uri", "")
        if not uri:
            return _error(request_id, -32602, "Missing required parameter: uri")
        try:
            content = _resource_provider.read_resource(uri)
            return _success(request_id, {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": json.dumps(content, default=str),
                    }
                ]
            })
        except Exception as exc:
            return _error(request_id, -32603, f"Resource read error: {exc}")

    # ------------------------------------------------------------------
    # Prompts
    # ------------------------------------------------------------------
    if method == "prompts/list":
        prompts = _prompt_provider.list_prompts()
        return _success(request_id, {
            "prompts": [
                {
                    "name": p.name,
                    "description": p.description,
                    "arguments": p.arguments,
                }
                for p in prompts
            ]
        })

    if method == "prompts/get":
        prompt_name = params.get("name", "")
        arguments = params.get("arguments", {})
        if not prompt_name:
            return _error(request_id, -32602, "Missing required parameter: name")
        try:
            rendered = _prompt_provider.get_prompt(prompt_name, arguments)
            return _success(request_id, {
                "description": prompt_name,
                "messages": [
                    {"role": "user", "content": {"type": "text", "text": rendered}}
                ],
            })
        except ValueError as exc:
            return _error(request_id, -32602, str(exc))
        except Exception as exc:
            return _error(request_id, -32603, f"Prompt render error: {exc}")

    # ------------------------------------------------------------------

    if method == "notifications/initialized":
        return None  # Notification, no response

    return _error(request_id, -32601, f"Method not found: {method}")


def _success(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def run_stdio() -> None:
    """Run the MCP server in stdio mode (read JSON-RPC from stdin, write to stdout)."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            response = _error(None, -32700, "Parse error")
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
            continue

        response = handle_request(request)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
