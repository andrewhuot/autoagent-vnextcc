"""Tests for ``cli.mcp.live_factory.build_live_client_factory``.

Slice 3 of the P5 MCP polish arc. The bridge already accepts any
``McpClientFactory`` callable; historically we never supplied a real
one, so even a well-formed ``.mcp.json`` with a hosted (SSE / HTTP)
server never made it into the workbench registry. This module fills
that gap by building a factory that:

1. Loads the typed `.mcp.json` once, up front.
2. Per-spec, constructs the right transport via ``build_transport``.
3. Wraps **hosted** transports (SSE + Streamable-HTTP) with
   :class:`ReconnectingTransport` — stdio subprocess transports are
   supervised by the OS already, so re-wrapping them just adds a thread
   with nothing useful to do.
4. Returns a connected :class:`McpTransportClient` — the bridge's
   duck-typed ``list_tools`` / ``call_tool`` surface.

We inject the transport factory and the reconnecting wrapper so the
tests don't open sockets or spawn subprocesses.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cli.mcp.config import (
    HttpServerConfig,
    SseServerConfig,
    StdioServerConfig,
)
from cli.mcp.live_factory import build_live_client_factory
from cli.tools.mcp_bridge import McpServerSpec


class _FakeTransport:
    def __init__(self, label: str = "stdio") -> None:
        self.label = label
        self.connected = False
        self.closed = False

    def connect(self) -> None:
        self.connected = True

    def close(self) -> None:
        self.closed = True

    def send(self, payload: dict) -> None:  # pragma: no cover - unused here
        raise AssertionError("no JSON-RPC in these tests")

    def receive(self, timeout: float) -> dict | None:  # pragma: no cover
        return None

    @property
    def is_connected(self) -> bool:
        return self.connected and not self.closed


def _write_config(root: Path, payload: dict[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / ".mcp.json").write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# Core behaviour
# ---------------------------------------------------------------------------


def test_factory_builds_client_for_stdio_without_reconnecting_wrapper(
    tmp_path: Path,
) -> None:
    """Stdio subprocesses are OS-supervised — no reconnect wrapper needed."""
    _write_config(
        tmp_path,
        {"mcpServers": {"local": {"transport": "stdio", "command": "x"}}},
    )
    built: list[tuple[str, Any]] = []

    def fake_transport_factory(server: Any) -> _FakeTransport:
        built.append(("transport", type(server).__name__))
        return _FakeTransport("stdio")

    def fake_reconnect_wrapper(inner: Any) -> Any:
        built.append(("wrap", type(inner).__name__))
        return inner

    factory = build_live_client_factory(
        workspace_root=tmp_path,
        transport_factory=fake_transport_factory,
        reconnect_wrapper=fake_reconnect_wrapper,
    )
    spec = McpServerSpec(name="local", command="x")
    client = factory(spec)

    # One transport built, zero reconnect wrappers applied.
    assert [b[0] for b in built] == ["transport"]
    assert hasattr(client, "list_tools")
    assert hasattr(client, "call_tool")


def test_factory_wraps_hosted_sse_with_reconnecting_transport(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        {
            "mcpServers": {
                "notion": {
                    "transport": "sse",
                    "url": "https://mcp.notion.com/sse",
                }
            }
        },
    )
    wrapped: list[Any] = []

    def fake_transport_factory(server: Any) -> _FakeTransport:
        assert isinstance(server, SseServerConfig)
        return _FakeTransport("sse")

    def fake_reconnect_wrapper(inner: Any) -> _FakeTransport:
        wrapped.append(inner)
        return _FakeTransport("reconnecting")

    factory = build_live_client_factory(
        workspace_root=tmp_path,
        transport_factory=fake_transport_factory,
        reconnect_wrapper=fake_reconnect_wrapper,
    )
    spec = McpServerSpec(name="notion")
    client = factory(spec)

    # The reconnect wrapper saw the raw SSE transport.
    assert len(wrapped) == 1
    assert wrapped[0].label == "sse"
    # And the client wound up holding the wrapped transport.
    assert client.transport.label == "reconnecting"  # type: ignore[attr-defined]


def test_factory_wraps_hosted_http_with_reconnecting_transport(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        {
            "mcpServers": {
                "remote": {
                    "transport": "streamable-http",
                    "url": "https://mcp.example/",
                }
            }
        },
    )
    wraps: list[Any] = []

    def fake_transport_factory(server: Any) -> _FakeTransport:
        assert isinstance(server, HttpServerConfig)
        return _FakeTransport("http")

    def fake_reconnect_wrapper(inner: Any) -> _FakeTransport:
        wraps.append(inner)
        return _FakeTransport("reconnecting")

    factory = build_live_client_factory(
        workspace_root=tmp_path,
        transport_factory=fake_transport_factory,
        reconnect_wrapper=fake_reconnect_wrapper,
    )
    factory(McpServerSpec(name="remote"))
    assert len(wraps) == 1
    assert wraps[0].label == "http"


def test_factory_raises_for_unknown_server(tmp_path: Path) -> None:
    _write_config(tmp_path, {"mcpServers": {"known": {"command": "x"}}})

    factory = build_live_client_factory(
        workspace_root=tmp_path,
        transport_factory=lambda s: _FakeTransport(),
        reconnect_wrapper=lambda t: t,
    )
    with pytest.raises(KeyError) as exc:
        factory(McpServerSpec(name="missing"))
    assert "missing" in str(exc.value)


def test_factory_connects_the_transport_before_returning(tmp_path: Path) -> None:
    """The bridge expects a READY client — so the factory must connect."""
    _write_config(
        tmp_path,
        {"mcpServers": {"s": {"command": "x"}}},
    )
    built: list[_FakeTransport] = []

    def fake_transport_factory(server: Any) -> _FakeTransport:
        t = _FakeTransport()
        built.append(t)
        return t

    factory = build_live_client_factory(
        workspace_root=tmp_path,
        transport_factory=fake_transport_factory,
        reconnect_wrapper=lambda t: t,
    )
    factory(McpServerSpec(name="s"))
    assert built and built[0].connected is True
