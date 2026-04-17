"""Tests for the transport-aware MCP runtime helpers and `mcp add` CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.mcp_runtime import (
    add_mcp_server,
    inspect_mcp_server,
    list_mcp_servers,
    mcp_status_snapshot,
)
from runner import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# Helper-function tests (typed add_mcp_server)
# ---------------------------------------------------------------------------


def test_add_mcp_server_writes_stdio_shape(tmp_path: Path) -> None:
    add_mcp_server(
        "browser",
        transport="stdio",
        command="python",
        args=["-m", "browser_mcp"],
        env={"FOO": "bar"},
        root=tmp_path,
    )

    on_disk = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    entry = on_disk["mcpServers"]["browser"]
    assert entry["transport"] == "stdio"
    assert entry["command"] == "python"
    assert entry["args"] == ["-m", "browser_mcp"]
    assert entry["env"] == {"FOO": "bar"}


def test_add_mcp_server_writes_sse_shape(tmp_path: Path) -> None:
    add_mcp_server(
        "remote",
        transport="sse",
        url="https://mcp.example.com/sse",
        headers={"X-Key": "v"},
        ping_interval_seconds=15.0,
        root=tmp_path,
    )

    on_disk = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    entry = on_disk["mcpServers"]["remote"]
    assert entry["transport"] == "sse"
    assert entry["url"] == "https://mcp.example.com/sse"
    assert entry["headers"] == {"X-Key": "v"}
    assert entry["ping_interval_seconds"] == 15.0


def test_add_mcp_server_writes_http_shape(tmp_path: Path) -> None:
    add_mcp_server(
        "remote",
        transport="http",
        url="https://mcp.example.com/",
        headers={"X-Key": "v"},
        root=tmp_path,
    )

    on_disk = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    entry = on_disk["mcpServers"]["remote"]
    assert entry["transport"] == "http"
    assert entry["url"] == "https://mcp.example.com/"
    assert entry["headers"] == {"X-Key": "v"}


def test_add_mcp_server_rejects_unknown_transport(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        add_mcp_server("x", transport="telepathy", root=tmp_path)


def test_inspect_mcp_server_includes_transport(tmp_path: Path) -> None:
    add_mcp_server(
        "remote",
        transport="http",
        url="https://mcp.example.com/",
        root=tmp_path,
    )

    item = inspect_mcp_server("remote", root=tmp_path)
    assert item is not None
    assert item["transport"] == "http"
    assert item["url"] == "https://mcp.example.com/"


def test_list_mcp_servers_includes_transport(tmp_path: Path) -> None:
    add_mcp_server("a", transport="stdio", command="python", root=tmp_path)
    add_mcp_server("b", transport="sse", url="https://e/sse", root=tmp_path)

    items = list_mcp_servers(root=tmp_path)
    by_name = {i["name"]: i for i in items}
    assert by_name["a"]["transport"] == "stdio"
    assert by_name["b"]["transport"] == "sse"


def test_mcp_status_snapshot_includes_transport(tmp_path: Path) -> None:
    add_mcp_server("a", transport="stdio", command="python", root=tmp_path)
    add_mcp_server("b", transport="sse", url="https://e/sse", root=tmp_path)

    snap = mcp_status_snapshot(root=tmp_path)
    assert snap["server_count"] == 2
    for entry in snap["servers"]:
        assert "transport" in entry


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


def test_cli_mcp_add_default_is_stdio(runner: CliRunner) -> None:
    """Legacy invocation with no --transport must still default to stdio."""
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli,
            ["mcp", "add", "browser", "--command", "python", "--arg", "-m", "--arg", "browser_mcp"],
        )
        assert result.exit_code == 0, result.output

        on_disk = json.loads(Path(".mcp.json").read_text(encoding="utf-8"))
        entry = on_disk["mcpServers"]["browser"]
        assert entry["transport"] == "stdio"
        assert entry["command"] == "python"
        assert entry["args"] == ["-m", "browser_mcp"]


def test_cli_mcp_add_sse(runner: CliRunner) -> None:
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli,
            [
                "mcp",
                "add",
                "remote",
                "--transport",
                "sse",
                "--url",
                "https://mcp.example.com/sse",
                "--header",
                "X-Key: secret",
            ],
        )
        assert result.exit_code == 0, result.output

        on_disk = json.loads(Path(".mcp.json").read_text(encoding="utf-8"))
        entry = on_disk["mcpServers"]["remote"]
        assert entry["transport"] == "sse"
        assert entry["url"] == "https://mcp.example.com/sse"
        assert entry["headers"] == {"X-Key": "secret"}


def test_cli_mcp_add_http(runner: CliRunner) -> None:
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli,
            [
                "mcp",
                "add",
                "remote",
                "--transport",
                "http",
                "--url",
                "https://mcp.example.com/",
            ],
        )
        assert result.exit_code == 0, result.output

        on_disk = json.loads(Path(".mcp.json").read_text(encoding="utf-8"))
        entry = on_disk["mcpServers"]["remote"]
        assert entry["transport"] == "http"
        assert entry["url"] == "https://mcp.example.com/"


def test_cli_mcp_add_stdio_rejects_url(runner: CliRunner) -> None:
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli,
            [
                "mcp",
                "add",
                "x",
                "--transport",
                "stdio",
                "--command",
                "python",
                "--url",
                "https://nope/",
            ],
        )
        assert result.exit_code != 0
        assert "--url" in result.output


def test_cli_mcp_add_sse_rejects_command(runner: CliRunner) -> None:
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli,
            [
                "mcp",
                "add",
                "x",
                "--transport",
                "sse",
                "--url",
                "https://e/sse",
                "--command",
                "python",
            ],
        )
        assert result.exit_code != 0
        assert "--command" in result.output


def test_cli_mcp_add_sse_requires_url(runner: CliRunner) -> None:
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["mcp", "add", "x", "--transport", "sse"])
        assert result.exit_code != 0
        assert "--url" in result.output


def test_cli_mcp_add_malformed_header(runner: CliRunner) -> None:
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli,
            [
                "mcp",
                "add",
                "x",
                "--transport",
                "sse",
                "--url",
                "https://e/sse",
                "--header",
                "no-colon-here",
            ],
        )
        assert result.exit_code != 0
        assert "--header" in result.output


def test_cli_mcp_status_shows_transport(runner: CliRunner) -> None:
    with runner.isolated_filesystem():
        Path(".mcp.json").write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "a": {"command": "x"},
                        "b": {"transport": "sse", "url": "https://e/sse"},
                    }
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        result = runner.invoke(cli, ["mcp", "status"])
        assert result.exit_code == 0, result.output
        assert "stdio" in result.output
        assert "sse" in result.output
