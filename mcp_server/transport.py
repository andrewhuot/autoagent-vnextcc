"""Streamable HTTP transport for the MCP server.

Implements MCP JSON-RPC 2.0 over HTTP with optional Server-Sent Events (SSE)
streaming for long-running operations.  The transport layer is decoupled from
the protocol handler so the same handle_request() logic works over stdio and
HTTP alike.
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)


class StreamableHttpTransport:
    """HTTP transport that wraps a JSON-RPC handler.

    Usage::

        from mcp_server.server import handle_request
        transport = StreamableHttpTransport(host="0.0.0.0", port=3000)
        transport.start()          # non-blocking; runs in background thread
        ...
        transport.stop()
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 3000,
        handler: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        # Allow injection of a custom JSON-RPC handler; default to the MCP one.
        if handler is None:
            from mcp_server.server import handle_request
            handler = handle_request
        self._handler = handler
        self._server: Any = None  # will hold HTTPServer instance
        self._thread: threading.Thread | None = None
        self._running = False

    # ------------------------------------------------------------------
    # JSON-RPC handler
    # ------------------------------------------------------------------

    def handle_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle a single JSON-RPC 2.0 request dict and return a response dict."""
        try:
            result = self._handler(request)
            if result is None:
                # Notification — no response
                return {}
            return result
        except Exception as exc:
            logger.exception("Unhandled error in JSON-RPC handler")
            return {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "error": {"code": -32603, "message": f"Internal error: {exc}"},
            }

    # ------------------------------------------------------------------
    # HTTP server lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the HTTP server in a daemon background thread."""
        if self._running:
            raise RuntimeError("Transport is already running")
        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True, name="mcp-http-transport")
        self._thread.start()
        logger.info("MCP HTTP transport started on %s:%d", self.host, self.port)

    def stop(self) -> None:
        """Gracefully shut down the HTTP server."""
        self._running = False
        if self._server is not None:
            self._server.shutdown()
            self._server = None
        logger.info("MCP HTTP transport stopped")

    # ------------------------------------------------------------------
    # Internal HTTP serving
    # ------------------------------------------------------------------

    def _serve(self) -> None:
        """Target function for the background thread."""
        from http.server import BaseHTTPRequestHandler, HTTPServer

        transport = self  # capture for closure

        class _RequestHandler(BaseHTTPRequestHandler):
            """Minimal HTTP handler that routes POST to JSON-RPC and GET to SSE."""

            def log_message(self, fmt: str, *args: Any) -> None:  # type: ignore[override]
                logger.debug(fmt, *args)

            def do_POST(self) -> None:  # noqa: N802
                """Handle JSON-RPC POST requests."""
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(length)
                    request = json.loads(body)
                except (json.JSONDecodeError, ValueError) as exc:
                    self._send_json(
                        {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {exc}"}},
                        status=400,
                    )
                    return

                response = transport.handle_request(request)
                if not response:
                    # Notification — 204 No Content
                    self.send_response(204)
                    self.end_headers()
                    return
                self._send_json(response)

            def do_GET(self) -> None:  # noqa: N802
                """Handle SSE stream requests (path must contain /sse)."""
                if "/sse" not in self.path:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                # Send an initial keepalive comment and then keep the connection
                # open.  In a production implementation the server would push
                # JSON-RPC notifications here.
                try:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    # Block until the client disconnects (transport stopped).
                    while transport._running:
                        import time
                        time.sleep(15)
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_OPTIONS(self) -> None:  # noqa: N802
                """Handle CORS pre-flight."""
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()

            def _send_json(self, data: dict[str, Any], status: int = 200) -> None:
                payload = json.dumps(data, default=str).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(payload)

        try:
            self._server = HTTPServer((self.host, self.port), _RequestHandler)
            self._server.serve_forever()
        except Exception as exc:
            logger.error("HTTP transport error: %s", exc)
            self._running = False
