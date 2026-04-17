"""Transport protocol for MCP servers.

A :class:`Transport` is the plumbing that carries JSON payloads to and
from one MCP server. It intentionally knows nothing about JSON-RPC — the
framing (ids, methods, results, notifications) lives one layer up in
:mod:`cli.mcp.transport_client`. Splitting the two means we can add
HTTP/SSE or WebSocket transports later without changing the client
adapter, and makes unit-testing the JSON-RPC layer trivial via a fake
transport that just records sends and replays queued receives."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Transport(Protocol):
    """Minimal byte/frame pipe to an MCP server.

    Implementations must:

    * Expose :attr:`is_connected` — truthy once :meth:`connect` succeeded
      and the underlying channel is still alive. Used by the client to
      decide whether to short-circuit a call.
    * Be safe to :meth:`close` more than once — the bridge may invoke
      close during shutdown after the subprocess already exited.
    * Emit dicts from :meth:`receive`, not raw bytes — parsing is the
      transport's job so the JSON-RPC client stays framing-agnostic.
    * Return ``None`` on receive timeout (rather than raising) so the
      client layer can distinguish "no data yet" from "peer disconnected"
      and retry / give up as it sees fit."""

    is_connected: bool

    def connect(self) -> None:
        """Open the channel. Idempotent-friendly: calling twice should be
        safe, though re-connecting after :meth:`close` is not required."""
        ...

    def close(self) -> None:
        """Tear down the channel. Must be idempotent — the bridge calls
        this from finally-blocks during partial failures."""
        ...

    def send(self, payload: dict) -> None:
        """Ship one JSON-serialisable dict to the peer. Framing (newline,
        length-prefix, HTTP body) is the transport's responsibility."""
        ...

    def receive(self, timeout: float) -> dict | None:
        """Return the next dict from the peer, or ``None`` on timeout.

        Raising on timeout would force every caller to catch the same
        exception; returning None lets the JSON-RPC layer loop cheaply
        while it filters out unrelated notifications."""
        ...


__all__ = ["Transport"]
