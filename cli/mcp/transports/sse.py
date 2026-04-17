"""HTTP + Server-Sent-Events MCP transport.

The MCP "SSE" transport shape is a split channel:

* A long-lived ``GET`` request whose body is a stream of SSE events — the
  server pushes JSON-RPC responses and notifications through it.
* A sibling ``POST`` endpoint — the client posts JSON-RPC requests to it.

The initial event on the stream is ``event: endpoint`` whose ``data:`` is
the POST URL (absolute or relative to the SSE URL). After that the server
emits ``event: message`` frames carrying JSON payloads, plus occasional
``:ping`` comment lines used purely as keep-alives. We mirror the
:class:`~cli.mcp.transports.stdio.StdioTransport` design: a background
reader thread parses the byte stream into dicts and drops them onto a
:class:`queue.Queue`, so the synchronous :meth:`receive` API can block on
a bounded timeout the same way the stdio path does. Symmetry between
transports keeps the JSON-RPC adapter framing-agnostic and gives the
bridge one mental model for both.

This module deliberately ships a tiny hand-rolled SSE parser instead of
pulling in ``httpx-sse`` — the protocol is 20 lines and we only care about
three field names (``event``, ``data``, and comments). Staying with the
stdlib for parsing keeps the dep tree identical to T5."""

from __future__ import annotations

import json
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urljoin

import httpx

from cli.mcp.transports._sse_framing import parse_events, parse_one_frame


@dataclass
class SseTransport:
    """Stream MCP JSON-RPC over an HTTP SSE + POST pair.

    ``url`` is the SSE endpoint; the POST URL is advertised by the server
    in the initial ``endpoint`` event and stored in :attr:`_post_url`.
    ``ping_interval_seconds`` is only used to derive the staleness
    threshold — we do not send pings ourselves; it is the server's
    keep-alive cadence. Connections are considered stale after
    ``ping_interval_seconds * 2`` without any event (pings included), so a
    single missed keep-alive still looks alive."""

    url: str
    headers: dict[str, str] = field(default_factory=dict)
    ping_interval_seconds: float = 30.0
    connect_timeout: float = 5.0
    # ``client`` is a public injection hook so tests can hand us an
    # :class:`httpx.MockTransport`-backed client; production code leaves
    # it ``None`` and we build our own in :meth:`connect`.
    client: Optional[httpx.Client] = None
    _owns_client: bool = field(default=False, init=False, repr=False)
    _stream_ctx: Any = field(default=None, init=False, repr=False)
    _response: Optional[httpx.Response] = field(default=None, init=False, repr=False)
    _event_iter: Any = field(default=None, init=False, repr=False)
    _post_url: Optional[str] = field(default=None, init=False, repr=False)
    _queue: "queue.Queue[dict]" = field(default_factory=queue.Queue, init=False, repr=False)
    _reader: Optional[threading.Thread] = field(default=None, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)
    _stream_alive: bool = field(default=False, init=False, repr=False)
    _last_event_time: float = field(default=0.0, init=False, repr=False)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open the SSE stream and consume the initial endpoint event.

        We build the httpx.Client lazily if the caller did not inject one,
        so the default constructor stays cheap (important for spec loading
        where we instantiate transports that may never be connected). The
        ``read=None`` timeout lets the GET stay open indefinitely — an
        SSE connection is supposed to be long-lived — while connect and
        write still have bounded timeouts so a wedged server cannot hang
        startup."""
        if self._stream_alive:
            return
        if self.client is None:
            self.client = httpx.Client(
                timeout=httpx.Timeout(
                    connect=self.connect_timeout, read=None, write=5.0, pool=5.0
                )
            )
            self._owns_client = True
        self._closed = False
        self._stream_ctx = self.client.stream(
            "GET",
            self.url,
            headers={**self.headers, "Accept": "text/event-stream"},
        )
        self._response = self._stream_ctx.__enter__()
        # Raise early on a non-2xx so the caller sees a clean failure
        # rather than an empty queue a few receive() calls later.
        self._response.raise_for_status()
        self._stream_alive = True
        self._last_event_time = time.monotonic()

        # We have to consume the endpoint event synchronously (before we
        # spawn the reader thread) so callers can send() immediately after
        # connect() returns. Doing it on the thread would race every first
        # request against the reader's first parse.
        endpoint = self._read_endpoint_event()
        if endpoint is None:
            raise RuntimeError(
                "SSE server closed stream before advertising an endpoint"
            )
        self._post_url = self._resolve_post_url(endpoint)

        self._reader = threading.Thread(
            target=self._pump, name=f"mcp-sse-{self.url}", daemon=True
        )
        self._reader.start()

    def close(self) -> None:
        """Tear down stream + client. Idempotent."""
        if self._closed:
            return
        self._closed = True
        self._stream_alive = False

        ctx = self._stream_ctx
        self._stream_ctx = None
        if ctx is not None:
            try:
                ctx.__exit__(None, None, None)
            except Exception:
                # The server closing mid-stream raises here; we already
                # flagged the stream dead, so swallowing is correct.
                pass
        self._response = None

        reader = self._reader
        self._reader = None
        if reader is not None and reader.is_alive() and reader is not threading.current_thread():
            reader.join(timeout=1.0)

        if self._owns_client and self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None
            self._owns_client = False

    # ------------------------------------------------------------------
    # Connection state
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """True iff the stream is open AND recently active.

        "Recently" means within ``ping_interval_seconds * 2`` of the last
        observed event or ping. We tolerate one missed keep-alive before
        declaring the connection stale, matching common SSE client
        heuristics and the cadence real MCP servers use (30s default,
        probe at 60s)."""
        if not self._stream_alive:
            return False
        stale_threshold = self.ping_interval_seconds * 2
        return (time.monotonic() - self._last_event_time) < stale_threshold

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------

    def send(self, payload: dict) -> None:
        """POST one JSON-RPC payload to the server's messages endpoint.

        We ignore the response body — real MCP SSE servers respond with
        202 Accepted and deliver the JSON-RPC reply on the SSE stream.
        We do still check the status: a 4xx/5xx here is a real error the
        client layer should surface (missing session, malformed request)."""
        if self._post_url is None or self.client is None:
            raise RuntimeError("SseTransport is not connected")
        response = self.client.post(self._post_url, json=payload, headers=dict(self.headers))
        # Any 2xx is fine; 202 Accepted is canonical. We raise on
        # everything else so the JSON-RPC layer gets a fast failure path.
        if response.status_code >= 300:
            raise RuntimeError(
                f"SSE POST to {self._post_url} failed: {response.status_code}"
            )

    def receive(self, timeout: float) -> dict | None:
        """Pop the next message event, or ``None`` on timeout.

        ``endpoint`` events after the first one, unknown event names, and
        SSE comment lines are filtered out by the reader thread — this
        queue only contains JSON bodies from ``event: message`` frames."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_post_url(self, endpoint: str) -> str:
        """Resolve the POST endpoint string against :attr:`url`.

        A server may advertise either a full URL (cross-origin proxies do
        this) or a path-only reference. ``urljoin`` handles both: given an
        absolute URL it returns it verbatim, given a relative path it
        joins it against the SSE URL's origin."""
        return urljoin(self.url, endpoint)

    def _read_endpoint_event(self) -> Optional[str]:
        """Block until we see the first event; return its data string.

        We must consume the endpoint event before :meth:`connect` returns
        so callers can :meth:`send` immediately after. We create the
        long-lived event generator here and stash it on the instance —
        the reader thread later resumes from the same generator, which
        preserves any frames that arrived in the same byte chunk as the
        endpoint event (MockTransport-backed tests, small servers, and
        anyone doing chunked transfer encoding all hit this path)."""
        if self._response is None:
            return None
        self._event_iter = parse_events(self._response.iter_bytes())
        for event_name, data, _event_id in self._event_iter:
            self._last_event_time = time.monotonic()
            if event_name == "endpoint":
                return data
            # Servers SHOULD lead with endpoint, but if they send keep-
            # alive comments first _parse_events has already filtered
            # them out; any other early non-endpoint event is dropped
            # here so we don't block forever on an impolite server.
        return None

    # NB: framing primitives live in :mod:`cli.mcp.transports._sse_framing`
    # so the Streamable-HTTP transport can reuse them without subclassing.
    # We keep thin method wrappers here so any external code that
    # patched ``SseTransport._parse_events`` / ``_parse_one_frame`` (none
    # currently, but the symmetry is cheap) continues to work.

    def _parse_events(self, iterator):
        """Delegating wrapper: yield ``(event_name, data)`` pairs.

        The shared parser yields 3-tuples (with an ``id:`` field for
        resume support); plain SSE ignores ``id`` so we drop it here to
        preserve the historical 2-tuple shape."""
        for event_name, data, _event_id in parse_events(iterator):
            yield event_name, data

    @staticmethod
    def _parse_one_frame(frame: str) -> Optional[tuple[str, str]]:
        """Delegating wrapper for a single frame (2-tuple for back-compat)."""
        parsed = parse_one_frame(frame)
        if parsed is None:
            return None
        event_name, data, _event_id = parsed
        return event_name, data

    def _pump(self) -> None:
        """Reader thread: parse events forever, enqueue message payloads.

        We resume the generator created in :meth:`_read_endpoint_event`
        (stashed on ``self._event_iter``) so any frames that arrived in
        the same byte chunk as the endpoint event are not lost. We
        ignore ``endpoint`` events here (the POST URL was already locked
        in during connect), drop unknown event types, and silently skip
        payloads that fail JSON decoding — the JSON-RPC layer only needs
        well-formed dicts. Every observed frame (including ones we drop)
        refreshes :attr:`_last_event_time`, which is what
        :attr:`is_connected` consults to detect staleness."""
        iterator = self._event_iter
        if iterator is None:
            return
        try:
            for event_name, data, _event_id in iterator:
                self._last_event_time = time.monotonic()
                if event_name != "message":
                    # endpoint (late re-announce), unknown event types —
                    # refresh-the-clock only, no payload.
                    continue
                if not data:
                    continue
                try:
                    payload = json.loads(data)
                except ValueError:
                    continue
                if isinstance(payload, dict):
                    self._queue.put(payload)
        except Exception:
            return


__all__ = ["SseTransport"]
