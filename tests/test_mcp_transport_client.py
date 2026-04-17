"""Unit tests for :class:`cli.mcp.transport_client.McpTransportClient`.

These tests exercise the JSON-RPC framing in isolation via a
``FakeTransport`` that records sends and replays a pre-built queue of
responses. Anything that touches real subprocesses lives in
:mod:`tests.test_mcp_transport_stdio`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from cli.mcp.transport_client import McpTransportClient


@dataclass
class FakeTransport:
    """In-memory transport that records outgoing payloads and replays
    pre-seeded responses. Mirrors the :class:`Transport` Protocol."""

    sent: list[dict] = field(default_factory=list)
    recv_queue: list[Any] = field(default_factory=list)
    is_connected: bool = True
    connect_calls: int = 0
    close_calls: int = 0

    def connect(self) -> None:
        self.connect_calls += 1
        self.is_connected = True

    def close(self) -> None:
        self.close_calls += 1
        self.is_connected = False

    def send(self, payload: dict) -> None:
        self.sent.append(payload)

    def receive(self, timeout: float) -> dict | None:  # noqa: ARG002
        if not self.recv_queue:
            return None
        msg = self.recv_queue.pop(0)
        # Sentinel that represents "transport returned None this turn".
        if msg is None:
            return None
        return msg


def test_list_tools_issues_json_rpc_and_parses_result():
    sent: list[dict] = []
    fake = FakeTransport(
        sent=sent,
        recv_queue=[
            {"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "foo"}]}}
        ],
    )
    client = McpTransportClient(transport=fake)
    tools = client.list_tools()
    assert tools == [{"name": "foo"}]
    assert sent[0]["method"] == "tools/list"
    assert sent[0]["id"] == 1
    assert sent[0]["jsonrpc"] == "2.0"


def test_call_tool_passes_arguments():
    sent: list[dict] = []
    fake = FakeTransport(
        sent=sent,
        recv_queue=[
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"content": [{"type": "text", "text": "ok"}]},
            }
        ],
    )
    client = McpTransportClient(transport=fake)
    result = client.call_tool("echo", {"msg": "hi"})
    assert result["content"][0]["text"] == "ok"
    assert sent[0]["method"] == "tools/call"
    assert sent[0]["params"]["name"] == "echo"
    assert sent[0]["params"]["arguments"] == {"msg": "hi"}


def test_json_rpc_error_raises():
    fake = FakeTransport(
        sent=[],
        recv_queue=[
            {
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -1, "message": "nope"},
            }
        ],
    )
    client = McpTransportClient(transport=fake)
    with pytest.raises(RuntimeError, match="nope"):
        client.list_tools()


def test_timeout_raises():
    fake = FakeTransport(sent=[], recv_queue=[])  # never responds
    client = McpTransportClient(transport=fake, timeout=0.01)
    with pytest.raises(TimeoutError):
        client.list_tools()


def test_unrelated_notifications_are_ignored():
    """Server may emit a notification (no id) + unrelated id before ours."""
    fake = FakeTransport(
        sent=[],
        recv_queue=[
            # Notification — no id.
            {"jsonrpc": "2.0", "method": "log", "params": {"level": "info"}},
            # A response to some OTHER request we never made (bogus id).
            {"jsonrpc": "2.0", "id": 999, "result": {"tools": [{"name": "ghost"}]}},
            # Finally the one we care about.
            {"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "real"}]}},
        ],
    )
    client = McpTransportClient(transport=fake)
    tools = client.list_tools()
    assert tools == [{"name": "real"}]


def test_id_counter_advances():
    """Each request must carry a fresh monotonically-increasing id."""
    sent: list[dict] = []
    fake = FakeTransport(
        sent=sent,
        recv_queue=[
            {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}},
            {"jsonrpc": "2.0", "id": 2, "result": {"tools": []}},
            {"jsonrpc": "2.0", "id": 3, "result": {"content": []}},
        ],
    )
    client = McpTransportClient(transport=fake)
    client.list_tools()
    client.list_tools()
    client.call_tool("x", {})
    assert [p["id"] for p in sent] == [1, 2, 3]


def test_connect_called_when_disconnected():
    """Client should opportunistically connect a lazy transport."""
    fake = FakeTransport(
        sent=[],
        recv_queue=[{"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}],
        is_connected=False,
    )
    client = McpTransportClient(transport=fake)
    client.list_tools()
    assert fake.connect_calls == 1


def test_connect_not_called_when_already_connected():
    fake = FakeTransport(
        sent=[],
        recv_queue=[{"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}],
        is_connected=True,
    )
    client = McpTransportClient(transport=fake)
    client.list_tools()
    assert fake.connect_calls == 0


def test_call_tool_returns_empty_dict_on_degenerate_result():
    """If the server returns a non-object result, return {}."""
    fake = FakeTransport(
        sent=[],
        recv_queue=[{"jsonrpc": "2.0", "id": 1, "result": "not-an-object"}],
    )
    client = McpTransportClient(transport=fake)
    assert client.call_tool("x", {}) == {}


def test_list_tools_returns_empty_when_result_missing_tools_key():
    fake = FakeTransport(
        sent=[],
        recv_queue=[{"jsonrpc": "2.0", "id": 1, "result": {}}],
    )
    client = McpTransportClient(transport=fake)
    assert client.list_tools() == []


def test_error_without_message_still_raises_runtime_error():
    fake = FakeTransport(
        sent=[],
        recv_queue=[{"jsonrpc": "2.0", "id": 1, "error": {"code": -32000}}],
    )
    client = McpTransportClient(transport=fake)
    with pytest.raises(RuntimeError):
        client.list_tools()
