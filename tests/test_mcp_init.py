"""Smoke test for MCP project initialization."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from runner import cli


def test_mcp_init_writes_valid_config_files() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["mcp", "init"])

        assert result.exit_code == 0, result.output
        assert Path(".mcp.json").exists()
        assert Path(".cursor/mcp.json").exists()

        root_config = json.loads(Path(".mcp.json").read_text(encoding="utf-8"))
        cursor_config = json.loads(Path(".cursor/mcp.json").read_text(encoding="utf-8"))

        for payload in [root_config, cursor_config]:
            assert "mcpServers" in payload
            assert "autoagent" in payload["mcpServers"]
            autoagent = payload["mcpServers"]["autoagent"]
            assert autoagent["command"]
            assert autoagent["args"]
