"""Tests for quickstart, demo, and improved init commands."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from runner import cli

API_KEY_ENV_VARS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture(autouse=True)
def clear_provider_api_keys(monkeypatch):
    for env_name in API_KEY_ENV_VARS:
        monkeypatch.delenv(env_name, raising=False)


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


# ---------------------------------------------------------------------------
# Improved init
# ---------------------------------------------------------------------------

class TestImprovedInit:
    def test_init_shows_checkmarks(self, runner, tmp_dir):
        result = runner.invoke(cli, ["init", "--dir", tmp_dir])
        assert result.exit_code == 0
        assert "✓" in result.output

    def test_init_with_agent_name(self, runner, tmp_dir):
        result = runner.invoke(cli, ["init", "--dir", tmp_dir, "--agent-name", "Test Bot"])
        assert result.exit_code == 0
        assert "Test Bot" in result.output
        md = (Path(tmp_dir) / "AUTOAGENT.md").read_text()
        assert "Test Bot" in md

    def test_init_with_platform(self, runner, tmp_dir):
        result = runner.invoke(cli, ["init", "--dir", tmp_dir, "--platform", "LangChain"])
        assert result.exit_code == 0
        md = (Path(tmp_dir) / "AUTOAGENT.md").read_text()
        assert "LangChain" in md

    def test_init_with_synthetic_data(self, runner, tmp_dir):
        result = runner.invoke(cli, ["init", "--dir", tmp_dir, "--with-synthetic-data"])
        assert result.exit_code == 0
        assert "synthetic conversations" in result.output
        assert (Path(tmp_dir) / "conversations.db").exists()

    def test_init_no_synthetic_data(self, runner, tmp_dir):
        result = runner.invoke(cli, ["init", "--dir", tmp_dir, "--no-synthetic-data"])
        assert result.exit_code == 0
        assert "synthetic conversations" not in result.output

    def test_init_seeds_runbooks(self, runner, tmp_dir):
        result = runner.invoke(cli, ["init", "--dir", tmp_dir])
        assert result.exit_code == 0
        assert "runbook" in result.output.lower()

    def test_init_shows_quickstart_hint(self, runner, tmp_dir):
        result = runner.invoke(cli, ["init", "--dir", tmp_dir])
        assert result.exit_code == 0
        # init now shows autoagent status and eval run as the recommended next steps
        assert "autoagent status" in result.output
        assert "autoagent eval run" in result.output

    def test_init_creates_all_directories(self, runner, tmp_dir):
        runner.invoke(cli, ["init", "--dir", tmp_dir])
        assert (Path(tmp_dir) / "configs").is_dir()
        assert (Path(tmp_dir) / "evals" / "cases").is_dir()
        assert (Path(tmp_dir) / "agent" / "config").is_dir()


# ---------------------------------------------------------------------------
# Quickstart command
# ---------------------------------------------------------------------------

class TestQuickstartCommand:
    def test_quickstart_exists(self, runner):
        result = runner.invoke(cli, ["quickstart", "--help"])
        assert result.exit_code == 0
        assert "golden path" in result.output.lower()

    def test_quickstart_has_agent_name_option(self, runner):
        result = runner.invoke(cli, ["quickstart", "--help"])
        assert "--agent-name" in result.output

    def test_quickstart_has_verbose_option(self, runner):
        result = runner.invoke(cli, ["quickstart", "--help"])
        assert "--verbose" in result.output

    def test_quickstart_runs(self, runner, tmp_dir):
        result = runner.invoke(cli, ["quickstart", "--dir", tmp_dir])
        assert result.exit_code == 0
        assert "Quickstart complete" in result.output

    def test_quickstart_shows_branded_banner(self, runner, tmp_dir):
        result = runner.invoke(cli, ["quickstart", "--dir", tmp_dir, "--no-open"])
        assert result.exit_code == 0
        assert "Continuous Agent Optimization Platform" in result.output
        assert "Created by Andrew Huot" in result.output

    def test_quickstart_no_banner_flag_suppresses_banner(self, runner, tmp_dir):
        result = runner.invoke(cli, ["quickstart", "--dir", tmp_dir, "--no-open", "--no-banner"])
        assert result.exit_code == 0
        assert "Continuous Agent Optimization Platform" not in result.output

    def test_quickstart_shows_steps(self, runner, tmp_dir):
        result = runner.invoke(cli, ["quickstart", "--dir", tmp_dir])
        assert "Step 1/4" in result.output
        assert "Step 2/4" in result.output
        assert "Step 3/4" in result.output
        assert "Step 4/4" in result.output

    def test_quickstart_shows_baseline(self, runner, tmp_dir):
        result = runner.invoke(cli, ["quickstart", "--dir", tmp_dir])
        assert "Baseline" in result.output

    def test_quickstart_shows_server_hint(self, runner, tmp_dir):
        result = runner.invoke(cli, ["quickstart", "--dir", tmp_dir])
        assert "autoagent server" in result.output

    def test_quickstart_with_agent_name(self, runner, tmp_dir):
        result = runner.invoke(cli, ["quickstart", "--dir", tmp_dir, "--agent-name", "Test Bot"])
        assert result.exit_code == 0
        assert "Test Bot" in result.output

    def test_quickstart_keeps_runtime_state_inside_target_directory(self, runner, tmp_path, monkeypatch):
        target = tmp_path / "workspace"
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(cli, ["quickstart", "--dir", str(target), "--no-open"])

        assert result.exit_code == 0
        assert (target / "optimizer_memory.db").exists()
        assert (target / "eval_history.db").exists()
        assert (target / ".autoagent" / "best_score.txt").exists()
        assert (target / ".autoagent" / "eval_cache.db").exists()
        assert (target / ".autoagent" / "traces.db").exists()
        assert not (tmp_path / "optimizer_memory.db").exists()
        assert not (tmp_path / ".autoagent" / "best_score.txt").exists()


# ---------------------------------------------------------------------------
# Demo command
# ---------------------------------------------------------------------------

class TestDemoCommand:
    def test_demo_exists(self, runner):
        result = runner.invoke(cli, ["demo", "--help"])
        assert result.exit_code == 0
        assert "demo" in result.output.lower()

    def test_demo_group_shows_branded_banner(self, runner):
        result = runner.invoke(cli, ["demo"])
        assert result.exit_code == 0
        assert "Continuous Agent Optimization Platform" in result.output
        assert "Created by Andrew Huot" in result.output

    def test_demo_quickstart_runs(self, runner, tmp_dir):
        result = runner.invoke(cli, ["demo", "quickstart", "--dir", tmp_dir])
        assert result.exit_code == 0
        assert "Demo complete" in result.output

    def test_demo_quickstart_shows_score(self, runner, tmp_dir):
        result = runner.invoke(cli, ["demo", "quickstart", "--dir", tmp_dir])
        assert "Score:" in result.output

    def test_demo_quickstart_shows_server_hint(self, runner, tmp_dir):
        result = runner.invoke(cli, ["demo", "quickstart", "--dir", tmp_dir])
        assert "autoagent server" in result.output

    def test_demo_quickstart_shows_quickstart_hint(self, runner, tmp_dir):
        result = runner.invoke(cli, ["demo", "quickstart", "--dir", tmp_dir])
        assert "autoagent quickstart" in result.output

    def test_demo_quickstart_forces_mock_mode_even_if_api_keys_exist(self, runner, tmp_dir, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        result = runner.invoke(cli, ["demo", "quickstart", "--dir", tmp_dir, "--no-open"])

        assert result.exit_code == 0
        assert "Using mock mode for the guided demo quickstart." in result.output
        assert "Demo complete" in result.output

    def test_demo_quickstart_keeps_runtime_state_inside_target_directory(self, runner, tmp_path, monkeypatch):
        target = tmp_path / "workspace"
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(cli, ["demo", "quickstart", "--dir", str(target), "--no-open"])

        assert result.exit_code == 0
        assert (target / "optimizer_memory.db").exists()
        assert (target / "eval_history.db").exists()
        assert (target / ".autoagent" / "best_score.txt").exists()
        assert (target / ".autoagent" / "eval_cache.db").exists()
        assert (target / ".autoagent" / "traces.db").exists()
        assert not (tmp_path / "optimizer_memory.db").exists()
        assert not (tmp_path / ".autoagent" / "best_score.txt").exists()

    def test_demo_vp_exists(self, runner):
        result = runner.invoke(cli, ["demo", "vp", "--help"])
        assert result.exit_code == 0
        assert "VP-ready demo" in result.output

    def test_demo_vp_runs_with_no_pause(self, runner):
        result = runner.invoke(cli, ["demo", "vp", "--no-pause"])
        assert result.exit_code == 0
        assert "Agent Health Report" in result.output
        assert "Results" in result.output
        assert "Next steps" in result.output

    def test_demo_vp_custom_agent_name(self, runner):
        result = runner.invoke(cli, ["demo", "vp", "--agent-name", "Test Bot", "--no-pause"])
        assert result.exit_code == 0
        assert "Test Bot" in result.output

    def test_demo_vp_shows_5_acts(self, runner):
        result = runner.invoke(cli, ["demo", "vp", "--no-pause"])
        assert result.exit_code == 0
        # Act 1: Health report
        assert "Overall Score" in result.output
        assert "CRITICAL" in result.output
        # Act 2: Diagnosis
        assert "Diagnosing issues" in result.output
        assert "Root Cause Analysis" in result.output
        # Act 3: Self-healing
        assert "Optimizing" in result.output
        assert "Cycle 1/3" in result.output
        assert "Cycle 2/3" in result.output
        assert "Cycle 3/3" in result.output
        # Act 4: Changes
        assert "Changes for Review" in result.output
        # Act 5: Results
        assert "Results" in result.output
        assert "Before" in result.output
        assert "After" in result.output


# ---------------------------------------------------------------------------
# CLI structure includes new commands
# ---------------------------------------------------------------------------

class TestNewCommandsInHelp:
    def test_quickstart_in_help(self, runner):
        # quickstart is hidden from default help but still registered and functional
        assert "quickstart" in cli.commands
        result = runner.invoke(cli, ["quickstart", "--help"])
        assert result.exit_code == 0

    def test_demo_in_help(self, runner):
        # demo is hidden from default help but still registered and functional
        assert "demo" in cli.commands
        result = runner.invoke(cli, ["demo", "--help"])
        assert result.exit_code == 0
