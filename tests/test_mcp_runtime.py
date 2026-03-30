"""Tests for workspace-scoped MCP runtime management."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from runner import cli


@pytest.fixture
def runner() -> CliRunner:
    """Return a CLI runner."""
    return CliRunner()


def test_mcp_add_list_inspect_and_remove_round_trip(runner: CliRunner) -> None:
    """The Stream B MCP runtime commands should manage `.mcp.json` in-place."""
    with runner.isolated_filesystem():
        add_result = runner.invoke(
            cli,
            [
                "mcp",
                "add",
                "browser",
                "--command",
                "python",
                "--arg",
                "-m",
                "--arg",
                "browser_mcp",
            ],
        )
        assert add_result.exit_code == 0, add_result.output
        assert Path(".mcp.json").exists()

        list_result = runner.invoke(cli, ["mcp", "list", "--json"])
        assert list_result.exit_code == 0, list_result.output
        payload = json.loads(list_result.output)
        assert payload["status"] == "ok"
        assert payload["data"][0]["name"] == "browser"
        assert payload["data"][0]["command"] == "python"

        inspect_result = runner.invoke(cli, ["mcp", "inspect", "browser", "--json"])
        assert inspect_result.exit_code == 0, inspect_result.output
        inspect_payload = json.loads(inspect_result.output)
        assert inspect_payload["data"]["name"] == "browser"
        assert inspect_payload["data"]["args"] == ["-m", "browser_mcp"]

        remove_result = runner.invoke(cli, ["mcp", "remove", "browser"])
        assert remove_result.exit_code == 0, remove_result.output

        config = json.loads(Path(".mcp.json").read_text(encoding="utf-8"))
        assert config["mcpServers"] == {}


def test_mcp_status_reports_workspace_runtime_state(runner: CliRunner) -> None:
    """`mcp status` should summarize the workspace runtime config, not just client installers."""
    with runner.isolated_filesystem():
        Path(".mcp.json").write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "autoagent": {"command": "autoagent", "args": ["mcp-server"]},
                        "browser": {"command": "python", "args": ["-m", "browser_mcp"]},
                    }
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        result = runner.invoke(cli, ["mcp", "status"])

        assert result.exit_code == 0, result.output
        assert "2 workspace MCP server" in result.output
        assert "autoagent" in result.output
        assert ".mcp.json" in result.output
