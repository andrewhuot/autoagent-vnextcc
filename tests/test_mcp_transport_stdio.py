"""Integration tests for :class:`cli.mcp.transports.stdio.StdioTransport`.

These tests spawn tiny inline Python "echo servers" via
``sys.executable -c ...`` so we exercise the real subprocess + pipe +
reader-thread path without pulling in an external MCP server. Skipped
on Windows because pipe/threading semantics differ enough that the
timeout test would need a separate implementation."""

from __future__ import annotations

import sys

import pytest

from cli.mcp.transports.stdio import StdioTransport


pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="stdio transport tests are POSIX-only"
)


_ECHO_SERVER = r"""
import sys, json
for line in sys.stdin:
    try:
        msg = json.loads(line)
    except Exception:
        continue
    msg["result"] = {"echoed": msg.get("params", {})}
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()
"""


_ENV_ECHO_SERVER = r"""
import sys, os, json
for line in sys.stdin:
    try:
        msg = json.loads(line)
    except Exception:
        continue
    msg["result"] = {"env_val": os.environ.get("MCP_TEST_VAR", "")}
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()
"""


_NOISY_SERVER = r"""
import sys, json
sys.stdout.write("banner: starting up\n")  # not JSON — should be dropped
sys.stdout.flush()
for line in sys.stdin:
    try:
        msg = json.loads(line)
    except Exception:
        continue
    msg["result"] = {"ok": True}
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()
"""


def test_stdio_connect_send_receive():
    t = StdioTransport(command=[sys.executable, "-c", _ECHO_SERVER])
    t.connect()
    try:
        assert t.is_connected
        t.send({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {"x": 1}})
        msg = t.receive(timeout=5.0)
        assert msg is not None
        assert msg["id"] == 1
        assert msg["result"]["echoed"] == {"x": 1}
    finally:
        t.close()
    assert not t.is_connected


def test_stdio_close_is_idempotent():
    t = StdioTransport(command=[sys.executable, "-c", _ECHO_SERVER])
    t.close()
    t.close()
    assert not t.is_connected


def test_stdio_close_without_connect():
    t = StdioTransport(command=[sys.executable, "-c", _ECHO_SERVER])
    # Never called connect — close should still be safe.
    t.close()
    assert not t.is_connected


def test_stdio_receive_timeout_returns_none():
    t = StdioTransport(
        command=[sys.executable, "-c", "import time; time.sleep(10)"]
    )
    t.connect()
    try:
        assert t.receive(timeout=0.05) is None
    finally:
        t.close()


def test_stdio_env_propagates():
    t = StdioTransport(
        command=[sys.executable, "-c", _ENV_ECHO_SERVER],
        env={"MCP_TEST_VAR": "hello-world"},
    )
    t.connect()
    try:
        t.send({"jsonrpc": "2.0", "id": 7, "method": "probe"})
        msg = t.receive(timeout=5.0)
        assert msg is not None
        assert msg["id"] == 7
        assert msg["result"]["env_val"] == "hello-world"
    finally:
        t.close()


def test_stdio_non_json_lines_are_dropped():
    t = StdioTransport(command=[sys.executable, "-c", _NOISY_SERVER])
    t.connect()
    try:
        t.send({"jsonrpc": "2.0", "id": 3, "method": "probe"})
        # The banner line comes first but should be silently ignored —
        # the next dict we receive must be the real response.
        msg = t.receive(timeout=5.0)
        assert msg is not None
        assert msg["id"] == 3
        assert msg["result"] == {"ok": True}
    finally:
        t.close()


def test_stdio_connect_requires_non_empty_command():
    t = StdioTransport(command=[])
    with pytest.raises(ValueError):
        t.connect()


def test_stdio_send_before_connect_raises():
    t = StdioTransport(command=[sys.executable, "-c", _ECHO_SERVER])
    with pytest.raises(RuntimeError):
        t.send({"jsonrpc": "2.0", "id": 1, "method": "ping"})


def test_stdio_is_connected_false_after_process_exits():
    # Launch a process that exits immediately; is_connected should flip
    # to False once the OS reaps it (which poll() reflects).
    t = StdioTransport(command=[sys.executable, "-c", "pass"])
    t.connect()
    try:
        # Give the child a moment to exit + the pipe to close.
        # receive() with a small timeout happens to be a convenient wait
        # without a naked sleep.
        for _ in range(20):
            if not t.is_connected:
                break
            t.receive(timeout=0.05)
        assert not t.is_connected
    finally:
        t.close()


def test_stdio_connect_twice_is_noop():
    t = StdioTransport(command=[sys.executable, "-c", _ECHO_SERVER])
    t.connect()
    try:
        pid_before = t._process.pid if t._process else None
        t.connect()
        pid_after = t._process.pid if t._process else None
        assert pid_before == pid_after
    finally:
        t.close()


def test_stdio_args_are_appended_to_command():
    """args list should be concatenated after command for Popen."""
    t = StdioTransport(
        command=[sys.executable, "-c"],
        args=[_ECHO_SERVER],
    )
    t.connect()
    try:
        t.send({"jsonrpc": "2.0", "id": 42, "method": "ping", "params": {"a": 1}})
        msg = t.receive(timeout=5.0)
        assert msg is not None
        assert msg["id"] == 42
        assert msg["result"]["echoed"] == {"a": 1}
    finally:
        t.close()
