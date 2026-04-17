"""Tests for ``agentlab mcp test <name>`` — live connectivity probe.

P5 polish task. The `/doctor` classifier-and-MCP section intentionally
refuses to probe transports because probing can hang; `mcp test` is the
counterpart — a user-invoked, timeout-bounded connectivity check that
exercises the full stack:

    .mcp.json → typed config → build_transport → transport.connect()
      → McpTransportClient.list_tools() → rendered report

The subject under test is a pure function `run_mcp_test(name, root,
*, transport_factory, client_factory, timeout) -> McpTestResult` plus
a thin Click adapter. We inject the factories so these tests don't
open network connections or spawn subprocesses.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pytest
from click.testing import CliRunner

from cli.mcp.test_command import McpTestResult, run_mcp_test


class _FakeTransport:
    """Satisfies the duck-typed `connect/close` contract used by the probe."""

    def __init__(self, *, raise_on_connect: Exception | None = None) -> None:
        self.raise_on_connect = raise_on_connect
        self.connected = False
        self.closed = False

    def connect(self) -> None:
        if self.raise_on_connect is not None:
            raise self.raise_on_connect
        self.connected = True

    def close(self) -> None:
        self.closed = True


class _FakeClient:
    """Satisfies the `list_tools` duck-typed contract."""

    def __init__(self, tools: list[dict[str, Any]]) -> None:
        self.tools = tools
        self.list_calls = 0

    def list_tools(self) -> list[dict[str, Any]]:
        self.list_calls += 1
        return list(self.tools)


def _write_config(root: Path, payload: Mapping[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / ".mcp.json").write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_run_mcp_test_returns_success_and_tool_names(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        {
            "mcpServers": {
                "notion": {
                    "transport": "streamable-http",
                    "url": "https://mcp.notion.com/",
                }
            }
        },
    )
    transport = _FakeTransport()
    client = _FakeClient(
        tools=[
            {"name": "search", "description": "Search Notion"},
            {"name": "fetch", "description": "Fetch a page"},
        ]
    )

    result = run_mcp_test(
        "notion",
        root=tmp_path,
        transport_factory=lambda cfg: transport,
        client_factory=lambda t: client,
    )

    assert isinstance(result, McpTestResult)
    assert result.ok is True
    assert result.transport_type == "streamable-http"
    assert result.tool_count == 2
    assert result.tool_names == ("search", "fetch")
    assert result.error is None
    assert result.latency_seconds is not None
    assert transport.connected is True
    assert transport.closed is True  # probe always closes even on success


def test_run_mcp_test_stdio_config(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        {
            "mcpServers": {
                "local": {
                    "transport": "stdio",
                    "command": "mcp-server-local",
                    "args": ["--port", "9999"],
                }
            }
        },
    )
    transport = _FakeTransport()
    client = _FakeClient(tools=[])
    result = run_mcp_test(
        "local",
        root=tmp_path,
        transport_factory=lambda cfg: transport,
        client_factory=lambda t: client,
    )
    assert result.ok is True
    assert result.transport_type == "stdio"
    assert result.tool_count == 0
    assert result.tool_names == ()


def test_run_mcp_test_legacy_stdio_config(tmp_path: Path) -> None:
    """A legacy .mcp.json with no `transport` key still probes as stdio."""
    _write_config(
        tmp_path,
        {"mcpServers": {"legacy": {"command": "old-server"}}},
    )
    transport = _FakeTransport()
    client = _FakeClient(tools=[{"name": "x"}])
    result = run_mcp_test(
        "legacy",
        root=tmp_path,
        transport_factory=lambda cfg: transport,
        client_factory=lambda t: client,
    )
    assert result.ok is True
    assert result.transport_type == "stdio"


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


def test_run_mcp_test_unknown_server_returns_error(tmp_path: Path) -> None:
    _write_config(tmp_path, {"mcpServers": {"other": {"command": "x"}}})
    result = run_mcp_test(
        "missing",
        root=tmp_path,
        transport_factory=lambda cfg: _FakeTransport(),
        client_factory=lambda t: _FakeClient(tools=[]),
    )
    assert result.ok is False
    assert result.error is not None
    assert "missing" in result.error
    assert result.transport_type is None


def test_run_mcp_test_connect_failure_is_reported(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        {
            "mcpServers": {
                "dead": {"transport": "sse", "url": "http://dead.example/sse"}
            }
        },
    )
    transport = _FakeTransport(raise_on_connect=ConnectionError("refused"))
    result = run_mcp_test(
        "dead",
        root=tmp_path,
        transport_factory=lambda cfg: transport,
        client_factory=lambda t: _FakeClient(tools=[]),
    )
    assert result.ok is False
    assert result.transport_type == "sse"
    assert result.error is not None
    assert "refused" in result.error
    # Failed connects don't create a client, so close() should still be
    # called on the transport we DID build (best-effort cleanup).
    assert transport.closed is True


def test_run_mcp_test_list_tools_failure_is_reported(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        {"mcpServers": {"flaky": {"command": "x"}}},
    )
    transport = _FakeTransport()

    class _RaisingClient:
        def list_tools(self) -> list[dict[str, Any]]:
            raise TimeoutError("no reply")

    result = run_mcp_test(
        "flaky",
        root=tmp_path,
        transport_factory=lambda cfg: transport,
        client_factory=lambda t: _RaisingClient(),
    )
    assert result.ok is False
    assert "no reply" in (result.error or "")
    assert transport.closed is True


def test_run_mcp_test_missing_config_file_reports_error(tmp_path: Path) -> None:
    # No .mcp.json at all.
    result = run_mcp_test(
        "anything",
        root=tmp_path,
        transport_factory=lambda cfg: _FakeTransport(),
        client_factory=lambda t: _FakeClient(tools=[]),
    )
    assert result.ok is False
    assert result.error is not None


# ---------------------------------------------------------------------------
# CLI adapter
# ---------------------------------------------------------------------------


def _invoke_mcp_test_cli(
    tmp_path: Path,
    name: str,
    *,
    transport_factory,
    client_factory,
    json_output: bool = False,
):
    """Invoke the registered `agentlab mcp test <name>` command.

    We reach into the click group via ``cli.mcp_runtime.register_runtime_commands``
    the same way other tests do; if a direct entry point exists, use it
    instead. The point is to prove the CLI wiring — not to re-test the
    core logic, which `run_mcp_test` tests already cover.
    """
    import click
    from cli.mcp.test_command import register_mcp_test_command

    group = click.Group("mcp")
    register_mcp_test_command(
        group,
        root_factory=lambda: tmp_path,
        transport_factory=transport_factory,
        client_factory=client_factory,
    )
    runner = CliRunner()
    args = ["test", name]
    if json_output:
        args.append("--json")
    return runner.invoke(group, args)


def test_mcp_test_cli_prints_human_report(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        {"mcpServers": {"notion": {"transport": "sse", "url": "https://x/sse"}}},
    )
    transport = _FakeTransport()
    client = _FakeClient(tools=[{"name": "search"}, {"name": "fetch"}])
    result = _invoke_mcp_test_cli(
        tmp_path,
        "notion",
        transport_factory=lambda cfg: transport,
        client_factory=lambda t: client,
    )
    assert result.exit_code == 0, result.output
    # Human output surfaces transport type, tool count, at least one tool name.
    assert "sse" in result.output
    assert "search" in result.output
    assert "2 tool" in result.output


def test_mcp_test_cli_json_output(tmp_path: Path) -> None:
    _write_config(tmp_path, {"mcpServers": {"s": {"command": "x"}}})
    transport = _FakeTransport()
    client = _FakeClient(tools=[{"name": "a"}])
    result = _invoke_mcp_test_cli(
        tmp_path,
        "s",
        transport_factory=lambda cfg: transport,
        client_factory=lambda t: client,
        json_output=True,
    )
    assert result.exit_code == 0, result.output
    # Every envelope-style JSON output on this CLI parses cleanly.
    payload = json.loads(result.output.strip())
    assert payload["status"] == "ok"
    assert payload["data"]["ok"] is True
    assert payload["data"]["tool_count"] == 1
    assert payload["data"]["tool_names"] == ["a"]


def test_mcp_test_cli_exit_code_nonzero_on_failure(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        {"mcpServers": {"broken": {"transport": "sse", "url": "http://x/sse"}}},
    )
    transport = _FakeTransport(raise_on_connect=RuntimeError("boom"))
    result = _invoke_mcp_test_cli(
        tmp_path,
        "broken",
        transport_factory=lambda cfg: transport,
        client_factory=lambda t: _FakeClient(tools=[]),
    )
    assert result.exit_code != 0
    assert "boom" in result.output
