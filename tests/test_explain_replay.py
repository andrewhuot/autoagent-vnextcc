"""Tests for explain and replay commands."""
import time
import pytest
from click.testing import CliRunner
from runner import cli, _format_relative_time


@pytest.fixture
def runner():
    return CliRunner()


class TestFormatRelativeTime:
    def test_just_now(self):
        assert _format_relative_time(time.time()) == "just now"

    def test_minutes_ago(self):
        result = _format_relative_time(time.time() - 300)
        assert "m ago" in result

    def test_hours_ago(self):
        result = _format_relative_time(time.time() - 7200)
        assert "h ago" in result

    def test_days_ago(self):
        result = _format_relative_time(time.time() - 172800)
        assert "d ago" in result


class TestExplainCommand:
    def test_explain_help(self, runner):
        result = runner.invoke(cli, ["explain", "--help"])
        assert result.exit_code == 0
        assert "plain-English summary" in result.output

    def test_explain_runs(self, runner):
        result = runner.invoke(cli, ["explain"])
        assert result.exit_code == 0

    def test_explain_verbose(self, runner):
        result = runner.invoke(cli, ["explain", "--verbose"])
        assert result.exit_code == 0


class TestReplayCommand:
    def test_replay_help(self, runner):
        result = runner.invoke(cli, ["replay", "--help"])
        assert result.exit_code == 0
        assert "optimization history" in result.output.lower() or "history" in result.output.lower()

    def test_replay_runs(self, runner):
        result = runner.invoke(cli, ["replay"])
        assert result.exit_code == 0
        assert "Optimization History" in result.output

    def test_replay_with_limit(self, runner):
        result = runner.invoke(cli, ["replay", "--limit", "5"])
        assert result.exit_code == 0


class TestCLIRegistration:
    def test_explain_in_help(self, runner):
        # explain is hidden from default help but still registered and functional
        assert "explain" in cli.commands
        result = runner.invoke(cli, ["explain", "--help"])
        assert result.exit_code == 0

    def test_replay_in_help(self, runner):
        # replay is hidden from default help but still registered and functional
        assert "replay" in cli.commands
        result = runner.invoke(cli, ["replay", "--help"])
        assert result.exit_code == 0
