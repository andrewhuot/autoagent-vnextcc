"""Tests for the tool-schema cache on :class:`McpTransportClient`.

Slice 4 of the P5 MCP polish arc. The bridge calls ``list_tools()``
once at registration time and never again — so why cache? Two
reasons:

1. **/mcp inspect, /mcp refresh, and the schema-rewrite hook call
   list_tools() repeatedly within one session.** Without a cache, each
   call sends a fresh JSON-RPC roundtrip; with one, refresh stays
   cheap and inspect is instantaneous.

2. **ReconnectingTransport fires on_reconnect after a drop.** That
   hook exists precisely so callers can invalidate caller-side caches
   that may have gone stale while the transport was down (a reboot
   could have changed the tool list). Without the cache, there's
   nothing to invalidate; with it, the hook flips us back into
   "ask the server next time" mode without touching the wire.

The cache is trivial: a single cached list, invalidated by
:meth:`invalidate_schemas`. No TTL, no LRU — the typical workbench
session has one MCP server and one schema snapshot per connection.
"""

from __future__ import annotations

from typing import Any

import pytest

from cli.mcp.transport_client import McpTransportClient


class _RecordingTransport:
    """Minimal transport fake that replays a canned JSON-RPC tools/list.

    ``send()`` records the frame; ``receive()`` returns the pre-queued
    reply matched by id. This keeps us honest about roundtrip counts
    while staying oblivious to the real wire format.
    """

    def __init__(self) -> None:
        self.connected = True
        self.sent: list[dict[str, Any]] = []
        self.canned_tools: list[dict[str, Any]] = [
            {"name": "search", "description": "Search", "inputSchema": {"type": "object"}},
            {"name": "fetch", "description": "Fetch",  "inputSchema": {"type": "object"}},
        ]

    def connect(self) -> None:
        self.connected = True

    def close(self) -> None:
        self.connected = False

    def send(self, payload: dict) -> None:
        self.sent.append(dict(payload))

    def receive(self, timeout: float) -> dict | None:
        if not self.sent:
            return None
        last = self.sent[-1]
        # Only match tools/list for this fake — tools/call would use a
        # different canned reply; we don't need that for cache tests.
        if last.get("method") != "tools/list":
            return None
        return {
            "jsonrpc": "2.0",
            "id": last["id"],
            "result": {"tools": list(self.canned_tools)},
        }

    @property
    def is_connected(self) -> bool:
        return self.connected


# ---------------------------------------------------------------------------
# Cache behaviour
# ---------------------------------------------------------------------------


def test_list_tools_caches_result_and_skips_second_roundtrip() -> None:
    transport = _RecordingTransport()
    client = McpTransportClient(transport=transport)

    first = client.list_tools()
    second = client.list_tools()

    assert first == second
    # Exactly ONE tools/list frame went on the wire.
    tools_list_sent = [p for p in transport.sent if p.get("method") == "tools/list"]
    assert len(tools_list_sent) == 1


def test_invalidate_schemas_forces_a_fresh_roundtrip() -> None:
    transport = _RecordingTransport()
    client = McpTransportClient(transport=transport)

    client.list_tools()
    # The bridge doesn't mutate the server's tool list — but a reconnect
    # COULD drop us onto a restarted server with a different set. We
    # simulate that here by swapping the canned reply before invalidate.
    transport.canned_tools = [
        {"name": "new_tool", "description": "post-reconnect", "inputSchema": {}}
    ]
    client.invalidate_schemas()
    refreshed = client.list_tools()

    assert [t["name"] for t in refreshed] == ["new_tool"]
    tools_list_sent = [p for p in transport.sent if p.get("method") == "tools/list"]
    assert len(tools_list_sent) == 2


def test_invalidate_schemas_before_first_call_is_a_noop() -> None:
    """Calling invalidate on a fresh client must not raise — this is
    what an eager ``on_reconnect`` hook does if the user reconnects
    before anyone has called ``list_tools()`` yet."""
    client = McpTransportClient(transport=_RecordingTransport())
    client.invalidate_schemas()  # no error
    # And a subsequent list_tools still works.
    tools = client.list_tools()
    assert [t["name"] for t in tools] == ["search", "fetch"]


def test_cache_returns_independent_list_not_shared_mutable() -> None:
    """Callers must not be able to corrupt the cache by mutating the
    returned list. Otherwise, a well-meaning consumer doing
    ``tools.pop(0)`` would silently shrink every future caller's view."""
    client = McpTransportClient(transport=_RecordingTransport())
    first = client.list_tools()
    first.clear()
    second = client.list_tools()
    assert len(second) == 2


# ---------------------------------------------------------------------------
# Integration: live factory wires invalidate_schemas as on_reconnect
# ---------------------------------------------------------------------------


def test_live_factory_registers_invalidate_schemas_as_on_reconnect(
    tmp_path: Any,
) -> None:
    """The slice 3 live factory must close the loop by registering the
    slice 4 invalidator as the transport's on_reconnect hook. This is
    the whole point of combining these slices — the schema cache is
    only safe in a reconnecting world if reconnects clear it."""
    import json

    from cli.mcp.live_factory import build_live_client_factory
    from cli.tools.mcp_bridge import McpServerSpec

    (tmp_path / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "notion": {
                        "transport": "sse",
                        "url": "https://mcp.notion.com/sse",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    class _FakeWrapper:
        on_reconnect: Any = None

        def __init__(self, inner: Any) -> None:
            self.inner = inner
            self.connected = False

        def connect(self) -> None:
            self.connected = True

        def close(self) -> None:
            self.connected = False

        def send(self, payload: dict) -> None:  # pragma: no cover
            pass

        def receive(self, timeout: float) -> dict | None:  # pragma: no cover
            return None

        @property
        def is_connected(self) -> bool:
            return self.connected

    wrapper_holder: list[_FakeWrapper] = []

    def fake_reconnect_wrapper(inner: Any) -> _FakeWrapper:
        w = _FakeWrapper(inner)
        wrapper_holder.append(w)
        return w

    factory = build_live_client_factory(
        workspace_root=tmp_path,
        transport_factory=lambda cfg: _RecordingTransport(),
        reconnect_wrapper=fake_reconnect_wrapper,
    )
    client = factory(McpServerSpec(name="notion"))

    # The wrapper was built AND its on_reconnect is the client's
    # invalidator — so a supervised reconnect will flush the cache.
    assert len(wrapper_holder) == 1
    assert wrapper_holder[0].on_reconnect == client.invalidate_schemas
