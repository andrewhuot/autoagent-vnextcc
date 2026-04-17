"""JSON-RPC client adapter over a :class:`Transport`.

This adapter converts the framing-agnostic :class:`Transport` into the
same two-method surface that :class:`cli.tools.mcp_bridge.McpClient`
expects — :meth:`list_tools` and :meth:`call_tool`. Keeping the adapter
its own class means the bridge never imports a transport directly;
production code wires one at the :class:`McpClientFactory` boundary and
tests can sub in any fake transport they like.

Design notes:

* **Synchronous id matching.** MCP servers may emit notifications
  (``method`` without ``id``) and unrelated pings concurrently with a
  reply. :meth:`_request` loops on :meth:`Transport.receive` until it
  sees a response whose ``id`` matches the request we just sent, or the
  cumulative timeout elapses. Non-matching frames are simply dropped —
  this adapter doesn't service notifications; a higher-level runtime
  would need that.
* **Monotonic id counter.** Ids stay unique for the lifetime of the
  client instance. We don't reuse ids after a timeout because a late
  reply under the reused id could confuse the next call."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Mapping

from cli.mcp.transports import Transport


@dataclass
class McpTransportClient:
    """JSON-RPC adapter. Satisfies :class:`McpClient` via a :class:`Transport`.

    The default 5-second timeout is enough for typical local MCP servers
    (list_tools replies in milliseconds) while short enough that a wedged
    server surfaces as an error instead of hanging the workbench."""

    transport: Transport
    timeout: float = 5.0
    _next_id: int = field(default=1, init=False, repr=False)

    # ------------------------------------------------------------------
    # Public API (matches cli.tools.mcp_bridge.McpClient)
    # ------------------------------------------------------------------

    def list_tools(self) -> list[dict[str, Any]]:
        """Send ``tools/list`` and return the server's tool descriptors.

        The MCP spec says the result carries a ``tools`` array, each item
        with ``name`` / ``description`` / ``inputSchema``. We pass the
        raw list through — the bridge's ``_coerce_tool_spec`` already
        normalises keys."""
        result = self._request("tools/list", None)
        tools = result.get("tools") if isinstance(result, Mapping) else None
        if not isinstance(tools, list):
            return []
        return [t for t in tools if isinstance(t, dict)]

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Send ``tools/call`` and return the ``result`` object verbatim.

        We don't flatten the ``content`` array here — that's the bridge's
        job (:func:`cli.tools.mcp_bridge._coerce_response`). Returning
        the raw result keeps this adapter reusable by any future caller
        that wants the structured blocks."""
        result = self._request(
            "tools/call",
            {"name": str(name), "arguments": dict(arguments)},
        )
        if isinstance(result, dict):
            return result
        # MCP servers must return an object; coerce degenerate shapes to
        # an empty dict rather than crashing callers with a type error.
        return {}

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _request(self, method: str, params: Mapping[str, Any] | None) -> Any:
        """One round-trip: send, then drain receives until id matches.

        Raises :class:`TimeoutError` if no matching response arrives
        before ``self.timeout`` seconds elapse, and :class:`RuntimeError`
        if the server returns a JSON-RPC error envelope."""
        request_id = self._next_id
        self._next_id += 1

        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            payload["params"] = dict(params)

        # Best-effort connect — transports that opened at construction
        # time make this a no-op, but lazy callers benefit.
        if not self.transport.is_connected:
            self.transport.connect()

        self.transport.send(payload)

        deadline = time.monotonic() + max(0.0, float(self.timeout))
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"MCP request {method!r} (id={request_id}) timed out "
                    f"after {self.timeout}s"
                )
            message = self.transport.receive(timeout=remaining)
            if message is None:
                # Timeout from the transport — loop will re-check the
                # deadline and raise TimeoutError on the next iteration.
                continue
            # Notifications (no id) and other unrelated frames are
            # dropped; only a matching id counts as "our response".
            if message.get("id") != request_id:
                continue
            if "error" in message and message["error"] is not None:
                err = message["error"]
                msg = ""
                if isinstance(err, Mapping):
                    msg = str(err.get("message") or err)
                else:
                    msg = str(err)
                raise RuntimeError(msg or "MCP server returned an error")
            return message.get("result")


__all__ = ["McpTransportClient"]
