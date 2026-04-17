"""Stdio-based MCP transport.

The MCP reference transport launches a server as a subprocess and frames
JSON-RPC messages as newline-delimited JSON on stdin/stdout. This module
wraps :class:`subprocess.Popen` with a reader thread that parses incoming
lines into a :class:`queue.Queue`, so the synchronous :meth:`receive`
API can block on a bounded timeout without polling.

Why a thread-fed queue rather than selectors? The standard-library
``selectors`` module is awkward on Windows for pipes, and the pure-thread
approach keeps the implementation portable. We isolate the thread so the
rest of the system stays blissfully synchronous — the MCP tool call
graph lives inside the tool-execution path, and that path is not async
today."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StdioTransport:
    """Launch an MCP server as a child process and frame JSON over its pipes.

    The ``command`` is the executable plus any prefix arguments the user
    listed in ``.mcp.json`` (pre-combined by :mod:`cli.mcp_runtime` when
    it hands us the spec). ``args`` stays separate so callers that build
    specs programmatically can keep executable-vs-argument semantics
    clear. Both lists are concatenated at spawn time.

    ``env`` merges onto the parent environment — we do not replace it,
    because MCP servers typically need ``PATH`` and other basics. Users
    who want a clean environment can pass an explicit value that
    overrides the host entries."""

    command: list[str]
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    _process: Optional[subprocess.Popen] = field(default=None, init=False, repr=False)
    _queue: "queue.Queue[dict]" = field(default_factory=queue.Queue, init=False, repr=False)
    _reader: Optional[threading.Thread] = field(default=None, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    @property
    def is_connected(self) -> bool:
        """True iff the child process is spawned and still running.

        We probe with :meth:`Popen.poll` so the answer reflects reality
        — a server that crashed after ``connect`` should no longer
        report itself connected, and the bridge will surface that as a
        failed call rather than silently hanging on a dead pipe."""
        proc = self._process
        if proc is None:
            return False
        return proc.poll() is None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Spawn the server and start the reader thread.

        Calling connect twice is a no-op (short-circuits on an already
        alive process) so the bridge can defensively connect before a
        call without juggling state."""
        if self.is_connected:
            return
        cmd = list(self.command) + list(self.args)
        if not cmd:
            raise ValueError("StdioTransport requires a non-empty command")
        merged_env = dict(os.environ)
        merged_env.update({str(k): str(v) for k, v in self.env.items()})
        self._process = subprocess.Popen(  # noqa: S603 - user-provided MCP binary
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=merged_env,
            bufsize=1,  # line-buffered; MCP frames on newlines
            text=True,
        )
        self._closed = False
        self._reader = threading.Thread(
            target=self._pump, name=f"mcp-stdio-{cmd[0]}", daemon=True
        )
        self._reader.start()

    def close(self) -> None:
        """Shut the child down and drop the reader thread.

        Idempotent by design — after the first call, subsequent calls
        fall through the early return. We give the process one second to
        exit cleanly on terminate, then fall back to kill so a buggy
        server cannot wedge the workbench during shutdown."""
        if self._closed:
            return
        self._closed = True
        proc = self._process
        if proc is not None:
            try:
                if proc.stdin and not proc.stdin.closed:
                    try:
                        proc.stdin.close()
                    except Exception:
                        pass
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        try:
                            proc.wait(timeout=1.0)
                        except subprocess.TimeoutExpired:
                            pass
            finally:
                # Close stdout/stderr so the reader thread's readline
                # returns quickly; otherwise it would block on a dead
                # pipe until Python finalises the file object.
                for stream in (proc.stdout, proc.stderr):
                    if stream is not None and not stream.closed:
                        try:
                            stream.close()
                        except Exception:
                            pass
        reader = self._reader
        if reader is not None and reader.is_alive():
            reader.join(timeout=1.0)
        self._reader = None

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------

    def send(self, payload: dict) -> None:
        """Serialise ``payload`` as one JSON line and write it to stdin.

        We flush immediately — MCP servers are line-framed, so buffering
        would deadlock a request/response pair where the server only
        reads after our whole line lands."""
        proc = self._process
        if proc is None or proc.stdin is None:
            raise RuntimeError("StdioTransport is not connected")
        if proc.poll() is not None:
            raise RuntimeError("StdioTransport child process has exited")
        line = json.dumps(payload) + "\n"
        proc.stdin.write(line)
        proc.stdin.flush()

    def receive(self, timeout: float) -> dict | None:
        """Pop one parsed message from the queue, or ``None`` on timeout.

        The reader thread puts parsed dicts on :attr:`_queue`; we block
        on :meth:`queue.Queue.get` for at most ``timeout`` seconds. Return
        None on Empty so callers can loop without handling an exception
        on the hot path (JSON-RPC id matching retries several times)."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _pump(self) -> None:
        """Reader thread: parse each stdout line and enqueue it.

        Non-JSON lines are silently dropped — servers occasionally print
        banner text before honouring the protocol, and surfacing that as
        a parse error here would be noise."""
        proc = self._process
        if proc is None or proc.stdout is None:
            return
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if isinstance(msg, dict):
                    self._queue.put(msg)
        except Exception:
            # A pipe closed mid-read is the normal shutdown path — we
            # don't want an error from the reader thread to crash the
            # workbench. The queue simply stops receiving new messages.
            return


__all__ = ["StdioTransport"]
