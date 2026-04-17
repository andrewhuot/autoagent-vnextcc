"""MCP Streamable-HTTP transport.

The Streamable-HTTP flavour of MCP collapses the SSE transport's two
endpoints into one: the client POSTs JSON-RPC to a single URL, and the
server responds with *either*

* a single ``application/json`` body — one JSON-RPC reply, one request,
  done; or
* a ``text/event-stream`` body — a series of SSE frames that carry one
  or more JSON-RPC messages (useful when the server streams progress
  notifications before the final response).

On top of that, the server MAY also accept a long-lived ``GET`` request
on the same URL (``Accept: text/event-stream``) for server-initiated
messages — think sampling requests or server-side ``notifications/*``.
Servers that do not support this just return ``405 Method Not Allowed``;
we tolerate that and keep the POST path usable.

Session state flows through a single header: the first server response
carries ``Mcp-Session-Id`` and the client echoes it on every subsequent
request. We only write ``_session_id`` once — the spec allows the server
to rotate, but in practice rotation happens at the HTTP layer (new
response, same request in flight) and would race the outgoing POST
anyway. If/when a real server in the wild rotates mid-session, this is
the spot to grow a reader-writer lock around ``_session_id``.

Resumption via ``Last-Event-ID`` is **not** implemented in this first
cut. The hook — ``_last_event_id`` is tracked by the shared framing
parser — is in place; wiring it into a reconnect loop is a TODO."""

from __future__ import annotations

import json
import queue
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from cli.mcp.transports._sse_framing import parse_events


@dataclass
class HttpStreamableTransport:
    """POST-based MCP transport with optional server-push over SSE.

    ``url`` is the single endpoint. ``client`` is the httpx.Client
    injection hook — tests pass a MockTransport-backed client; production
    code leaves it ``None`` and we build our own on :meth:`connect`.

    Timeouts are split: ``connect_timeout`` bounds TCP + TLS setup;
    ``request_timeout`` bounds *non-streaming* POSTs. Streaming POSTs
    (event-stream response) intentionally use ``read=None`` — the server
    can legitimately take seconds to emit the next SSE frame and we do
    not want a 30s read timeout to tear down a slow-but-healthy stream.
    """

    url: str
    headers: dict[str, str] = field(default_factory=dict)
    connect_timeout: float = 5.0
    request_timeout: float = 30.0
    client: Optional[httpx.Client] = None
    _owns_client: bool = field(default=False, init=False, repr=False)
    _session_id: Optional[str] = field(default=None, init=False, repr=False)
    _queue: "queue.Queue[dict]" = field(default_factory=queue.Queue, init=False, repr=False)
    _closed: bool = field(default=True, init=False, repr=False)
    _connected: bool = field(default=False, init=False, repr=False)
    # GET-channel bookkeeping — None when the server returned 405 or we
    # have not started one yet.
    _get_stream_ctx: Any = field(default=None, init=False, repr=False)
    _get_response: Optional[httpx.Response] = field(default=None, init=False, repr=False)
    _get_reader: Optional[threading.Thread] = field(default=None, init=False, repr=False)
    # POST-streaming bookkeeping — at most one streamed POST in flight
    # at a time in this first cut (simpler; MCP clients do request/reply
    # serially via the JSON-RPC adapter above us).
    _post_stream_ctx: Any = field(default=None, init=False, repr=False)
    _post_response: Optional[httpx.Response] = field(default=None, init=False, repr=False)
    _post_reader: Optional[threading.Thread] = field(default=None, init=False, repr=False)
    # Tracked for future Last-Event-ID resumption; wiring is TODO.
    _last_event_id: Optional[str] = field(default=None, init=False, repr=False)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open the httpx.Client and probe the optional GET SSE channel.

        We try the GET once; if the server answers 405 (or any non-2xx)
        we silently fall back to POST-only mode, which is the majority
        case for simple tool servers. A 2xx GET response is assumed to
        be an event-stream and handed off to a reader thread."""
        if self._connected:
            return
        if self.client is None:
            # read=None lets streaming POSTs stay open indefinitely; the
            # non-streaming path passes an explicit timeout= to request().
            self.client = httpx.Client(
                timeout=httpx.Timeout(
                    connect=self.connect_timeout,
                    read=None,
                    write=5.0,
                    pool=5.0,
                )
            )
            self._owns_client = True
        self._closed = False
        self._connected = True

        # Optional server-push channel. Failures here must not break the
        # transport — POST-only is a valid mode.
        self._try_open_get_channel()

    def close(self) -> None:
        """Tear down all streams + owned client. Idempotent."""
        if self._closed:
            return
        self._closed = True
        self._connected = False

        self._teardown_get_stream()
        self._teardown_post_stream()

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
        """Connected iff :meth:`connect` succeeded and we have not closed.

        Unlike the plain SSE transport we do NOT track staleness — the
        Streamable-HTTP channel is request/reply at its core, and the
        optional GET stream may simply be idle between server pushes.
        The JSON-RPC client above us already surfaces request-level
        failures (raised from :meth:`send`); a staleness timer here
        would add false negatives without adding real signal."""
        return self._connected and not self._closed

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------

    def send(self, payload: dict) -> None:
        """POST one JSON-RPC payload and route the response to :attr:`_queue`.

        The response content-type determines the handling path:

        * ``application/json`` → parse once, enqueue, done.
        * ``text/event-stream`` → spawn (or reuse) a reader thread that
          parses SSE frames until the stream closes, enqueueing each
          ``message`` event's JSON payload. The server may emit multiple
          responses per request here.
        * anything else → :class:`RuntimeError` — surfaced so the caller
          knows the server violated the spec rather than silently hanging.

        Non-2xx statuses also raise :class:`RuntimeError` so the JSON-RPC
        adapter has a fast-fail path for bad sessions / malformed bodies.
        """
        if self.client is None or not self._connected or self._closed:
            raise RuntimeError("HttpStreamableTransport is not connected")

        headers = {
            "Content-Type": "application/json",
            # Accept both shapes so the server picks whichever fits the
            # method it's answering — spec-compliant behaviour.
            "Accept": "application/json, text/event-stream",
        }
        headers.update(self.headers)
        if self._session_id is not None:
            headers["Mcp-Session-Id"] = self._session_id

        # We open a streaming request so that an event-stream response
        # doesn't buffer the entire body before we start parsing. For
        # application/json responses we just read() the (small) body
        # inside the same context and return.
        stream_ctx = self.client.stream(
            "POST", self.url, json=payload, headers=headers
        )
        response = stream_ctx.__enter__()
        try:
            if response.status_code >= 300:
                # Drain for a sane error message, then raise. ``read()``
                # on a small error body is fine; we are not yet committed
                # to the streaming path.
                try:
                    body = response.read().decode("utf-8", errors="replace")
                except Exception:
                    body = ""
                raise RuntimeError(
                    f"MCP HTTP POST to {self.url} failed: "
                    f"{response.status_code} {body[:200]}"
                )

            # Capture the session id on the first response that carries
            # one — the spec guarantees this on the initialize reply but
            # some servers send it on every response; either way we only
            # need to latch once.
            if self._session_id is None:
                server_sid = response.headers.get("mcp-session-id")
                if server_sid:
                    self._session_id = server_sid

            content_type = response.headers.get("content-type", "")
            ct_main = content_type.split(";", 1)[0].strip().lower()

            if ct_main == "application/json":
                body_bytes = response.read()
                try:
                    parsed = json.loads(body_bytes.decode("utf-8"))
                except ValueError as exc:
                    raise RuntimeError(
                        f"MCP HTTP response was not valid JSON: {exc}"
                    ) from exc
                if isinstance(parsed, dict):
                    self._queue.put(parsed)
                elif isinstance(parsed, list):
                    # Batched JSON-RPC: spec permits an array of replies.
                    # Enqueue in order so the JSON-RPC adapter sees each.
                    for item in parsed:
                        if isinstance(item, dict):
                            self._queue.put(item)
                # Close the context — the body has been consumed.
                stream_ctx.__exit__(None, None, None)
                return

            if ct_main == "text/event-stream":
                # Tear down any previous streamed POST before starting a
                # new one. In serial request/reply use this is a no-op.
                self._teardown_post_stream()
                self._post_stream_ctx = stream_ctx
                self._post_response = response
                reader = threading.Thread(
                    target=self._pump_stream,
                    args=(response, "post"),
                    name=f"mcp-http-post-{self.url}",
                    daemon=True,
                )
                self._post_reader = reader
                reader.start()
                # Deliberately DO NOT exit the stream_ctx here — the
                # reader thread owns it until EOF, at which point
                # :meth:`_pump_stream` closes it via _teardown_post_stream.
                return

            # Any other content type is a spec violation — surface it.
            stream_ctx.__exit__(None, None, None)
            raise RuntimeError(
                f"MCP HTTP response had unexpected Content-Type: {content_type!r}"
            )
        except Exception:
            # On any failure in the synchronous branch, make sure we did
            # not leak the stream context. The event-stream branch above
            # returns without raising, so we only reach here on the json
            # / error / bad-content-type paths.
            try:
                stream_ctx.__exit__(None, None, None)
            except Exception:
                pass
            raise

    def receive(self, timeout: float) -> dict | None:
        """Pop the next JSON-RPC message, or ``None`` on timeout.

        Messages come from three sources — JSON POST replies, streamed
        POST replies, and the optional server-push GET channel — all of
        which feed the same queue. The JSON-RPC adapter above filters by
        id/method, so interleaving is fine here."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _try_open_get_channel(self) -> None:
        """Attempt the long-lived GET SSE channel. Tolerate 405 cleanly."""
        assert self.client is not None
        headers = {"Accept": "text/event-stream", **self.headers}
        if self._session_id is not None:
            headers["Mcp-Session-Id"] = self._session_id
        if self._last_event_id is not None:
            # Hook for future resumption; harmless on a fresh connect
            # (value stays None until we ship resume).
            headers["Last-Event-ID"] = self._last_event_id
        try:
            ctx = self.client.stream("GET", self.url, headers=headers)
            response = ctx.__enter__()
        except Exception:
            # Transport-level failure (DNS, refused connect, etc.) —
            # POST path can still succeed against a different host; do
            # not promote this into a hard connect() failure.
            return
        if response.status_code == 405 or response.status_code >= 400:
            # Server declines the server-push channel. Close cleanly.
            try:
                ctx.__exit__(None, None, None)
            except Exception:
                pass
            return
        # Latch session id off the GET response too — some servers send
        # it here when the client reconnects into an existing session.
        if self._session_id is None:
            server_sid = response.headers.get("mcp-session-id")
            if server_sid:
                self._session_id = server_sid
        self._get_stream_ctx = ctx
        self._get_response = response
        reader = threading.Thread(
            target=self._pump_stream,
            args=(response, "get"),
            name=f"mcp-http-get-{self.url}",
            daemon=True,
        )
        self._get_reader = reader
        reader.start()

    def _pump_stream(self, response: httpx.Response, which: str) -> None:
        """Reader thread: parse ``response``'s SSE body into :attr:`_queue`.

        ``which`` distinguishes the POST-streaming path from the GET
        server-push path purely for teardown — when the iterator ends we
        clear the corresponding ``_*_stream_ctx`` slot so :meth:`close`
        knows the thread is done and :meth:`send` can start a new stream."""
        try:
            for event_name, data, event_id in parse_events(response.iter_bytes()):
                if event_id is not None:
                    # Stash for future Last-Event-ID resumption.
                    self._last_event_id = event_id
                if event_name != "message" or not data:
                    continue
                try:
                    payload = json.loads(data)
                except ValueError:
                    # Malformed frame — skip rather than crash the
                    # stream. The JSON-RPC layer only wants dicts.
                    continue
                if isinstance(payload, dict):
                    self._queue.put(payload)
        except Exception:
            # Reader must not raise across the thread boundary.
            return
        finally:
            # Close our owned context so close() sees a clean slot.
            if which == "post":
                ctx = self._post_stream_ctx
                self._post_stream_ctx = None
                self._post_response = None
                if ctx is not None:
                    try:
                        ctx.__exit__(None, None, None)
                    except Exception:
                        pass
            elif which == "get":
                ctx = self._get_stream_ctx
                self._get_stream_ctx = None
                self._get_response = None
                if ctx is not None:
                    try:
                        ctx.__exit__(None, None, None)
                    except Exception:
                        pass

    def _teardown_get_stream(self) -> None:
        ctx = self._get_stream_ctx
        self._get_stream_ctx = None
        self._get_response = None
        if ctx is not None:
            try:
                ctx.__exit__(None, None, None)
            except Exception:
                pass
        reader = self._get_reader
        self._get_reader = None
        if (
            reader is not None
            and reader.is_alive()
            and reader is not threading.current_thread()
        ):
            reader.join(timeout=1.0)

    def _teardown_post_stream(self) -> None:
        ctx = self._post_stream_ctx
        self._post_stream_ctx = None
        self._post_response = None
        if ctx is not None:
            try:
                ctx.__exit__(None, None, None)
            except Exception:
                pass
        reader = self._post_reader
        self._post_reader = None
        if (
            reader is not None
            and reader.is_alive()
            and reader is not threading.current_thread()
        ):
            reader.join(timeout=1.0)


__all__ = ["HttpStreamableTransport"]
