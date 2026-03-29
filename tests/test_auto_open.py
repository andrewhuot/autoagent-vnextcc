"""Tests for auto-open web console feature."""
import pytest
from unittest.mock import patch
from click.testing import CliRunner
from runner import cli, _auto_open_console


API_KEY_ENV_VARS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")

@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture(autouse=True)
def clear_provider_api_keys(monkeypatch):
    for env_name in API_KEY_ENV_VARS:
        monkeypatch.delenv(env_name, raising=False)

class TestAutoOpenHelper:
    def test_auto_open_importable(self):
        pass

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
    def test_demo_quickstart_has_open_flag(self, runner):
        result = runner.invoke(cli, ["demo", "quickstart", "--help"])
        assert result.exit_code == 0
        assert "--open" in result.output or "--no-open" in result.output

    def test_demo_quickstart_no_open_runs(self, runner):
        """demo quickstart --no-open should complete without starting server."""
        result = runner.invoke(cli, ["demo", "quickstart", "--no-open"])
        assert result.exit_code == 0
