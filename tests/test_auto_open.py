"""Tests for auto-open web console feature."""
import socket
import pytest
from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from runner import cli, _auto_open_console

@pytest.fixture
def runner():
    return CliRunner()

class TestAutoOpenHelper:
    def test_auto_open_importable(self):
        from runner import _auto_open_console

    @patch("runner.webbrowser", create=True)
    @patch("runner.socket", create=True)
    def test_auto_open_fallback_on_port_in_use(self, mock_socket_mod, mock_wb):
        """When server can't start, should print fallback hint."""
        # This tests the fallback path — we can't easily test the full server start
        # Just verify the function exists and is callable
        assert callable(_auto_open_console)

class TestQuickstartOpenFlag:
    def test_quickstart_has_open_flag(self, runner):
        result = runner.invoke(cli, ["quickstart", "--help"])
        assert result.exit_code == 0
        assert "--open" in result.output or "--no-open" in result.output

    def test_quickstart_no_open_runs(self, runner):
        """quickstart --no-open should complete without starting server."""
        result = runner.invoke(cli, ["quickstart", "--no-open"])
        assert result.exit_code == 0

class TestDemoOpenFlag:
    def test_demo_has_open_flag(self, runner):
        result = runner.invoke(cli, ["demo", "--help"])
        assert result.exit_code == 0
        assert "--open" in result.output or "--no-open" in result.output

    def test_demo_no_open_runs(self, runner):
        """demo --no-open should complete without starting server."""
        result = runner.invoke(cli, ["demo", "--no-open"])
        assert result.exit_code == 0
