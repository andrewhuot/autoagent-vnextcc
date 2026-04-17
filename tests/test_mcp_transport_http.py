"""Tests for :class:`cli.mcp.transports.http.HttpStreamableTransport`.

Same style as the SSE suite: we back the transport with an
:class:`httpx.MockTransport`-handler rather than a real server so that
we can pin down the wire framing (Content-Type, headers, SSE body) per
test. The Streamable-HTTP spec allows a POST response to be *either* a
single ``application/json`` body or a ``text/event-stream`` stream, so
the handler in each test picks whichever shape the scenario exercises."""

from __future__ import annotations

import json
import threading
import time

import httpx
import pytest

from cli.mcp.transports.http import HttpStreamableTransport


# ---------------------------------------------------------------------------
# Shared helpers, mirrored from tests/test_mcp_transport_sse.py on purpose
# so the two suites read the same way.
# ---------------------------------------------------------------------------


def _build_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _wait_until(predicate, timeout: float = 1.0, interval: float = 0.01) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _sse_body(events: list[bytes]) -> bytes:
    return b"".join(events)


# ---------------------------------------------------------------------------
# POST with application/json body — the single-response fast path.
# ---------------------------------------------------------------------------


def test_http_post_json_response_is_enqueued():
    """A POST that returns application/json surfaces via receive()."""
    reply = {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}

    def handler(request):
        if request.method == "POST":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                content=json.dumps(reply).encode(),
            )
        # Optional GET channel — server declines.
        return httpx.Response(405)

    client = _build_client(handler)
    t = HttpStreamableTransport(url="http://srv.example/mcp", client=client)
    t.connect()
    try:
        t.send({"jsonrpc": "2.0", "id": 1, "method": "ping"})
        msg = t.receive(timeout=1.0)
        assert msg == reply
    finally:
        t.close()


def test_http_post_body_is_json_serialised():
    """The POST body is the JSON-RPC payload verbatim."""
    seen: list[dict] = []

    def handler(request):
        if request.method == "POST":
            seen.append(json.loads(request.content))
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                content=b'{"jsonrpc":"2.0","id":1,"result":{}}',
            )
        return httpx.Response(405)

    client = _build_client(handler)
    t = HttpStreamableTransport(url="http://srv.example/mcp", client=client)
    t.connect()
    try:
        t.send({"jsonrpc": "2.0", "id": 1, "method": "ping"})
    finally:
        t.close()

    assert seen == [{"jsonrpc": "2.0", "id": 1, "method": "ping"}]


# ---------------------------------------------------------------------------
# POST with text/event-stream body — the streaming multi-response path.
# ---------------------------------------------------------------------------


def test_http_post_event_stream_response_yields_messages_in_order():
    """An SSE-framed POST response enqueues each message event."""
    events = [
        b'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"step":1}}\n\n',
        b'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"step":2}}\n\n',
    ]

    def handler(request):
        if request.method == "POST":
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=_sse_body(events),
            )
        return httpx.Response(405)

    client = _build_client(handler)
    t = HttpStreamableTransport(url="http://srv.example/mcp", client=client)
    t.connect()
    try:
        t.send({"jsonrpc": "2.0", "id": 1, "method": "slow"})
        first = t.receive(timeout=1.0)
        second = t.receive(timeout=1.0)
        assert first is not None and first["result"] == {"step": 1}
        assert second is not None and second["result"] == {"step": 2}
    finally:
        t.close()


def test_http_post_event_stream_multi_line_data_concatenates():
    """Multi-line ``data:`` in an event-stream response joins with ``\\n``."""
    events = [
        b"event: message\n"
        b'data: {"jsonrpc":"2.0",\n'
        b'data: "id":1}\n\n',
    ]

    def handler(request):
        if request.method == "POST":
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=_sse_body(events),
            )
        return httpx.Response(405)

    client = _build_client(handler)
    t = HttpStreamableTransport(url="http://srv.example/mcp", client=client)
    t.connect()
    try:
        t.send({"jsonrpc": "2.0", "id": 1, "method": "ping"})
        msg = t.receive(timeout=1.0)
        assert msg is not None
        assert msg["id"] == 1
    finally:
        t.close()


# ---------------------------------------------------------------------------
# Session id header round-trip.
# ---------------------------------------------------------------------------


def test_http_captures_session_id_from_first_response():
    """The server's Mcp-Session-Id on the first response is echoed thereafter."""
    sent_headers: list[dict] = []

    def handler(request):
        if request.method == "POST":
            sent_headers.append(dict(request.headers))
            # First response seeds the session id; subsequent ones simply
            # mirror the JSON-RPC reply. We keep it identical for both so
            # the test asserts purely on the outgoing header behaviour.
            return httpx.Response(
                200,
                headers={
                    "content-type": "application/json",
                    "mcp-session-id": "sess-42",
                },
                content=b'{"jsonrpc":"2.0","id":1,"result":{}}',
            )
        return httpx.Response(405)

    client = _build_client(handler)
    t = HttpStreamableTransport(url="http://srv.example/mcp", client=client)
    t.connect()
    try:
        t.send({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        # Drain so the first response is fully processed (session id set).
        assert t.receive(timeout=1.0) is not None
        t.send({"jsonrpc": "2.0", "id": 2, "method": "ping"})
    finally:
        t.close()

    assert "mcp-session-id" not in sent_headers[0]
    assert sent_headers[1].get("mcp-session-id") == "sess-42"


# ---------------------------------------------------------------------------
# Error paths.
# ---------------------------------------------------------------------------


def test_http_non_2xx_post_raises_runtime_error():
    def handler(request):
        if request.method == "POST":
            return httpx.Response(500, content=b"boom")
        return httpx.Response(405)

    client = _build_client(handler)
    t = HttpStreamableTransport(url="http://srv.example/mcp", client=client)
    t.connect()
    try:
        with pytest.raises(RuntimeError):
            t.send({"jsonrpc": "2.0", "id": 1, "method": "ping"})
    finally:
        t.close()


def test_http_unexpected_content_type_raises_runtime_error():
    def handler(request):
        if request.method == "POST":
            return httpx.Response(
                200,
                headers={"content-type": "text/plain"},
                content=b"not-json",
            )
        return httpx.Response(405)

    client = _build_client(handler)
    t = HttpStreamableTransport(url="http://srv.example/mcp", client=client)
    t.connect()
    try:
        with pytest.raises(RuntimeError):
            t.send({"jsonrpc": "2.0", "id": 1, "method": "ping"})
    finally:
        t.close()


def test_http_send_before_connect_raises():
    t = HttpStreamableTransport(url="http://srv.example/mcp")
    with pytest.raises(RuntimeError):
        t.send({"jsonrpc": "2.0", "id": 1, "method": "ping"})


# ---------------------------------------------------------------------------
# Lifecycle: close, receive-after-close, connect-twice.
# ---------------------------------------------------------------------------


def test_http_close_is_idempotent():
    def handler(request):
        if request.method == "POST":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                content=b'{"jsonrpc":"2.0","id":1,"result":{}}',
            )
        return httpx.Response(405)

    client = _build_client(handler)
    t = HttpStreamableTransport(url="http://srv.example/mcp", client=client)
    t.connect()
    t.close()
    # Second close must not raise.
    t.close()
    assert not t.is_connected


def test_http_receive_after_close_returns_none_promptly():
    def handler(request):
        if request.method == "POST":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                content=b'{"jsonrpc":"2.0","id":1,"result":{}}',
            )
        return httpx.Response(405)

    client = _build_client(handler)
    t = HttpStreamableTransport(url="http://srv.example/mcp", client=client)
    t.connect()
    t.close()
    start = time.monotonic()
    assert t.receive(timeout=0.05) is None
    assert time.monotonic() - start < 0.5


def test_http_connect_twice_is_noop():
    def handler(request):
        return httpx.Response(405)

    client = _build_client(handler)
    t = HttpStreamableTransport(url="http://srv.example/mcp", client=client)
    t.connect()
    try:
        t.connect()  # must not raise or re-open anything
        assert t.is_connected
    finally:
        t.close()


# ---------------------------------------------------------------------------
# Optional GET SSE channel for server-initiated messages.
# ---------------------------------------------------------------------------


def test_http_tolerates_405_on_optional_get_channel():
    """If the server rejects the GET SSE channel, POSTs still work."""
    def handler(request):
        if request.method == "GET":
            return httpx.Response(405)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=b'{"jsonrpc":"2.0","id":1,"result":{}}',
        )

    client = _build_client(handler)
    t = HttpStreamableTransport(url="http://srv.example/mcp", client=client)
    t.connect()  # must not raise despite the 405
    try:
        t.send({"jsonrpc": "2.0", "id": 1, "method": "ping"})
        msg = t.receive(timeout=1.0)
        assert msg is not None
    finally:
        t.close()


def test_http_server_initiated_messages_surface_via_get_channel():
    """If the GET SSE channel is supported, pushed messages hit receive()."""
    server_events = [
        b'event: message\ndata: {"jsonrpc":"2.0","method":"ping","params":{}}\n\n',
    ]

    # We need the GET body to stay open long enough for the reader thread
    # to parse it. MockTransport delivers the body synchronously, so a
    # plain bytes body works — the event is already fully buffered.
    def handler(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=_sse_body(server_events),
            )
        return httpx.Response(405)

    client = _build_client(handler)
    t = HttpStreamableTransport(url="http://srv.example/mcp", client=client)
    t.connect()
    try:
        msg = t.receive(timeout=1.0)
        assert msg is not None
        assert msg.get("method") == "ping"
    finally:
        t.close()


# ---------------------------------------------------------------------------
# is_connected
# ---------------------------------------------------------------------------


def test_http_is_connected_flips_false_after_close():
    def handler(request):
        return httpx.Response(405)

    client = _build_client(handler)
    t = HttpStreamableTransport(url="http://srv.example/mcp", client=client)
    t.connect()
    assert t.is_connected
    t.close()
    assert not t.is_connected
