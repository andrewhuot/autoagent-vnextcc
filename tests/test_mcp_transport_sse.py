"""Tests for :class:`cli.mcp.transports.sse.SseTransport`.

We exercise the transport against an :class:`httpx.MockTransport`-backed
client rather than a live HTTP server — that gives us deterministic byte
framing for SSE parser edge cases (pings, multi-line data, absolute POST
URLs) without booting a loopback server per test. The ``client`` kwarg on
:class:`SseTransport` is the injection hook that makes this possible."""

from __future__ import annotations

import json
import threading
import time

import httpx
import pytest

from cli.mcp.transports.sse import SseTransport


def _sse_body(events: list[bytes]) -> bytes:
    """Concatenate pre-formatted SSE frames into one response body."""
    return b"".join(events)


def _build_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _wait_until(predicate, timeout: float = 1.0, interval: float = 0.01) -> bool:
    """Poll ``predicate`` until truthy or timeout. Avoids a naked sleep
    in tests that depend on the reader thread making progress."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


# ---------------------------------------------------------------------------
# Basic wiring: endpoint discovery, message parsing, POST routing.
# ---------------------------------------------------------------------------


def test_sse_transport_parses_endpoint_and_message():
    events = [
        b"event: endpoint\ndata: /messages\n\n",
        b'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{}}\n\n',
    ]

    def handler(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=_sse_body(events),
            )
        return httpx.Response(202)

    client = _build_client(handler)
    t = SseTransport(url="http://srv.example/sse", client=client)
    t.connect()
    try:
        assert t._post_url == "http://srv.example/messages"
        msg = t.receive(timeout=1.0)
        assert msg is not None
        assert msg["id"] == 1
        assert msg["result"] == {}
    finally:
        t.close()


def test_sse_transport_send_posts_to_endpoint():
    posts: list[tuple[httpx.URL, dict]] = []

    def handler(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=b"event: endpoint\ndata: /m\n\n",
            )
        posts.append((request.url, json.loads(request.content)))
        return httpx.Response(202)

    client = _build_client(handler)
    t = SseTransport(url="http://srv.example/sse", client=client)
    t.connect()
    try:
        t.send({"jsonrpc": "2.0", "id": 1, "method": "ping"})
    finally:
        t.close()

    assert posts == [
        (httpx.URL("http://srv.example/m"), {"jsonrpc": "2.0", "id": 1, "method": "ping"})
    ]


def test_sse_transport_absolute_post_url():
    """An absolute URL in the endpoint event is used verbatim."""
    events = [b"event: endpoint\ndata: https://other.example/m\n\n"]
    posts: list[httpx.URL] = []

    def handler(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=_sse_body(events),
            )
        posts.append(request.url)
        return httpx.Response(202)

    client = _build_client(handler)
    t = SseTransport(url="http://srv.example/sse", client=client)
    t.connect()
    try:
        assert t._post_url == "https://other.example/m"
        t.send({"jsonrpc": "2.0", "id": 1, "method": "ping"})
    finally:
        t.close()

    assert posts == [httpx.URL("https://other.example/m")]


# ---------------------------------------------------------------------------
# Parser edge cases: pings, unknown events, multi-line data.
# ---------------------------------------------------------------------------


def test_sse_transport_ignores_pings_and_unknown_events():
    """Comment lines and non-``message`` events never surface on receive()."""
    events = [
        b"event: endpoint\ndata: /m\n\n",
        b":ping\n\n",
        b":keepalive\n\n",
        b"event: notice\ndata: something-else\n\n",
        b'event: message\ndata: {"jsonrpc":"2.0","id":1}\n\n',
    ]

    def handler(request):
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse_body(events),
        )

    client = _build_client(handler)
    t = SseTransport(url="http://srv/sse", client=client)
    t.connect()
    try:
        msg = t.receive(timeout=1.0)
        assert msg is not None
        assert msg["id"] == 1
        # Nothing else should be waiting in the queue.
        assert t.receive(timeout=0.05) is None
    finally:
        t.close()


def test_sse_transport_multi_line_data_concatenates():
    """Per the SSE spec, multi-line ``data:`` joins with ``\\n``."""
    events = [
        b"event: endpoint\ndata: /m\n\n",
        b"event: message\n"
        b'data: {"jsonrpc":"2.0",\n'
        b'data: "id":1}\n\n',
    ]

    def handler(request):
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse_body(events),
        )

    client = _build_client(handler)
    t = SseTransport(url="http://srv/sse", client=client)
    t.connect()
    try:
        msg = t.receive(timeout=1.0)
        assert msg is not None
        assert msg["id"] == 1
    finally:
        t.close()


def test_sse_transport_default_event_is_message():
    """An SSE frame with ``data:`` but no ``event:`` defaults to ``message``."""
    events = [
        b"event: endpoint\ndata: /m\n\n",
        b'data: {"jsonrpc":"2.0","id":9}\n\n',
    ]

    def handler(request):
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse_body(events),
        )

    client = _build_client(handler)
    t = SseTransport(url="http://srv/sse", client=client)
    t.connect()
    try:
        msg = t.receive(timeout=1.0)
        assert msg is not None
        assert msg["id"] == 9
    finally:
        t.close()


# ---------------------------------------------------------------------------
# Lifecycle + timeout + connection state.
# ---------------------------------------------------------------------------


def test_sse_transport_receive_none_on_timeout():
    """With no events after endpoint, receive(timeout=small) returns None."""
    # The server sends only the endpoint event, then the stream closes —
    # but close doesn't enqueue anything, so receive must time out cleanly.
    events = [b"event: endpoint\ndata: /m\n\n"]

    # We use a server that BLOCKS on reads to simulate an idle stream:
    # MockTransport delivers the whole body at once, so wrap it in a
    # generator that yields the endpoint event then hangs on a threading
    # Event that we never set. This way the reader thread stays parked
    # waiting for bytes, which is exactly the real-world idle case.
    hold = threading.Event()

    def body_iter():
        yield events[0]
        # Block until the test is done — this keeps the stream "open but
        # silent" so receive() has to depend on its own timeout.
        hold.wait(timeout=2.0)

    def handler(request):
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=body_iter(),
        )

    client = _build_client(handler)
    t = SseTransport(url="http://srv/sse", client=client)
    t.connect()
    try:
        start = time.monotonic()
        assert t.receive(timeout=0.05) is None
        elapsed = time.monotonic() - start
        # Sanity: we timed out quickly, not after the 2s hold expiry.
        assert elapsed < 0.5
    finally:
        hold.set()
        t.close()


def test_sse_transport_close_is_idempotent():
    events = [b"event: endpoint\ndata: /m\n\n"]

    def handler(request):
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse_body(events),
        )

    client = _build_client(handler)
    t = SseTransport(url="http://srv/sse", client=client)
    t.connect()
    t.close()
    # Second close must not raise.
    t.close()
    assert not t.is_connected


def test_sse_transport_is_connected_reflects_staleness(monkeypatch):
    """After ``ping_interval_seconds * 2`` of silence, is_connected flips False."""
    # A fake monotonic clock lets us leap forward past the staleness
    # threshold without actually sleeping. We patch it at the module
    # level because SseTransport reads it through ``time.monotonic``.
    from cli.mcp.transports import sse as sse_mod

    clock = {"t": 1000.0}

    def fake_monotonic():
        return clock["t"]

    monkeypatch.setattr(sse_mod.time, "monotonic", fake_monotonic)

    events = [b"event: endpoint\ndata: /m\n\n"]

    def handler(request):
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse_body(events),
        )

    client = _build_client(handler)
    t = SseTransport(
        url="http://srv/sse", client=client, ping_interval_seconds=1.0
    )
    t.connect()
    try:
        # Fresh connection is alive.
        assert t.is_connected
        # Jump forward less than 2x ping interval — still alive.
        clock["t"] += 1.5
        assert t.is_connected
        # Jump past the 2x threshold — stale, so not connected.
        clock["t"] += 1.0
        assert not t.is_connected
    finally:
        t.close()


def test_sse_transport_connect_twice_is_noop():
    """A second connect() on a live transport should short-circuit."""
    events = [b"event: endpoint\ndata: /m\n\n"]

    def handler(request):
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse_body(events),
        )

    client = _build_client(handler)
    t = SseTransport(url="http://srv/sse", client=client)
    t.connect()
    try:
        post_url_first = t._post_url
        t.connect()  # must not re-open or re-consume endpoint
        assert t._post_url == post_url_first
    finally:
        t.close()


# ---------------------------------------------------------------------------
# Error paths.
# ---------------------------------------------------------------------------


def test_sse_transport_send_before_connect_raises():
    t = SseTransport(url="http://srv/sse")
    with pytest.raises(RuntimeError):
        t.send({"jsonrpc": "2.0", "id": 1, "method": "ping"})


def test_sse_transport_post_failure_raises():
    """A non-2xx POST surfaces as RuntimeError so JSON-RPC can retry/fail."""
    events = [b"event: endpoint\ndata: /m\n\n"]

    def handler(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=_sse_body(events),
            )
        return httpx.Response(500)

    client = _build_client(handler)
    t = SseTransport(url="http://srv/sse", client=client)
    t.connect()
    try:
        with pytest.raises(RuntimeError):
            t.send({"jsonrpc": "2.0", "id": 1, "method": "ping"})
    finally:
        t.close()


def test_sse_transport_non_2xx_get_raises_on_connect():
    """A 4xx/5xx on the GET means the server rejected the session."""

    def handler(request):
        return httpx.Response(404)

    client = _build_client(handler)
    t = SseTransport(url="http://srv/sse", client=client)
    with pytest.raises(httpx.HTTPStatusError):
        t.connect()
