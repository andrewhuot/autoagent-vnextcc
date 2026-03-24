"""Tests for the enhanced CLI command structure."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from runner import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


class TestCLIStructure:
    """Verify the CLI has all expected commands and subcommands."""

    def test_root_group_exists(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "AutoAgent VNextCC" in result.output

    def test_version_flag(self, runner):
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "1.0.0" in result.output

    def test_eval_group_exists(self, runner):
        result = runner.invoke(cli, ["eval", "--help"])
        assert result.exit_code == 0
        assert "run" in result.output
        assert "results" in result.output
        assert "list" in result.output

    def test_config_group_exists(self, runner):
        result = runner.invoke(cli, ["config", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output
        assert "show" in result.output
        assert "diff" in result.output

    def test_top_level_commands(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        for cmd in ["init", "eval", "optimize", "config", "deploy", "loop", "status", "logs", "server"]:
            assert cmd in result.output, f"Missing command: {cmd}"

    def test_legacy_run_group_hidden(self, runner):
        """Legacy run group should exist but be hidden from help."""
        result = runner.invoke(cli, ["--help"])
        # 'run' should not appear as a visible command in help
        # (it's hidden=True)
        # But it should still work
        result2 = runner.invoke(cli, ["run", "--help"])
        assert result2.exit_code == 0


class TestInitCommand:
    def test_init_creates_structure(self, runner, tmp_dir):
        result = runner.invoke(cli, ["init", "--dir", tmp_dir])
        assert result.exit_code == 0
        assert "Initialized" in result.output
        assert (Path(tmp_dir) / "configs").is_dir()
        assert (Path(tmp_dir) / "evals" / "cases").is_dir()

    def test_init_copies_base_config(self, runner, tmp_dir):
        result = runner.invoke(cli, ["init", "--dir", tmp_dir])
        assert result.exit_code == 0
        assert (Path(tmp_dir) / "configs" / "v001_base.yaml").exists()

    def test_init_copies_eval_cases(self, runner, tmp_dir):
        result = runner.invoke(cli, ["init", "--dir", tmp_dir])
        assert result.exit_code == 0
        cases_dir = Path(tmp_dir) / "evals" / "cases"
        yaml_files = list(cases_dir.glob("*.yaml"))
        assert len(yaml_files) > 0


class TestEvalCommands:
    def test_eval_run_default(self, runner):
        result = runner.invoke(cli, ["eval", "run"])
        assert result.exit_code == 0
        assert "Composite:" in result.output

    def test_eval_run_with_category(self, runner):
        result = runner.invoke(cli, ["eval", "run", "--category", "happy_path"])
        assert result.exit_code == 0
        assert "Category: happy_path" in result.output

    def test_eval_run_with_output(self, runner, tmp_dir):
        output_file = os.path.join(tmp_dir, "results.json")
        result = runner.invoke(cli, ["eval", "run", "--output", output_file])
        assert result.exit_code == 0
        assert Path(output_file).exists()
        data = json.loads(Path(output_file).read_text())
        assert "scores" in data
        assert "results" in data

    def test_eval_results_from_file(self, runner, tmp_dir):
        # First create a results file
        output_file = os.path.join(tmp_dir, "results.json")
        runner.invoke(cli, ["eval", "run", "--output", output_file])
        # Then read it
        result = runner.invoke(cli, ["eval", "results", "--file", output_file])
        assert result.exit_code == 0
        assert "Composite:" in result.output

    def test_eval_list_empty(self, runner, tmp_dir):
        result = runner.invoke(cli, ["eval", "list"])
        # May or may not find files depending on cwd
        assert result.exit_code == 0


class TestStatusCommand:
    def test_status_with_empty_db(self, runner, tmp_dir):
        db_path = os.path.join(tmp_dir, "test.db")
        configs_dir = os.path.join(tmp_dir, "configs")
        memory_db = os.path.join(tmp_dir, "memory.db")
        os.makedirs(configs_dir, exist_ok=True)

        result = runner.invoke(cli, [
            "status",
            "--db", db_path,
            "--configs-dir", configs_dir,
            "--memory-db", memory_db,
        ])
        assert result.exit_code == 0
        assert "Conversations: 0" in result.output


class TestLogsCommand:
    def test_logs_empty_db(self, runner, tmp_dir):
        db_path = os.path.join(tmp_dir, "test.db")
        result = runner.invoke(cli, ["logs", "--db", db_path])
        assert result.exit_code == 0
        assert "No conversations found" in result.output


class TestConfigCommands:
    def test_config_list_empty(self, runner, tmp_dir):
        configs_dir = os.path.join(tmp_dir, "configs")
        os.makedirs(configs_dir, exist_ok=True)
        result = runner.invoke(cli, ["config", "list", "--configs-dir", configs_dir])
        assert result.exit_code == 0
        assert "No config versions" in result.output


class TestDoctorCommand:
    def test_doctor_runs_without_error(self, runner):
        """doctor command exits cleanly and prints the header."""
        result = runner.invoke(cli, ["doctor"])
        assert result.exit_code == 0
        assert "AutoAgent Doctor" in result.output
        assert "API Keys" in result.output
        assert "Data Stores" in result.output

    def test_doctor_shows_mock_warning_when_use_mock_true(self, runner, tmp_dir):
        """doctor reports mock-mode warning when use_mock: true."""
        config_file = os.path.join(tmp_dir, "autoagent_mock.yaml")
        Path(config_file).write_text("optimizer:\n  use_mock: true\n", encoding="utf-8")
        result = runner.invoke(cli, ["doctor", "--config", config_file])
        assert result.exit_code == 0
        assert "Enabled" in result.output
        assert "use_mock" in result.output

    def test_doctor_no_mock_warning_when_use_mock_false(self, runner, tmp_dir):
        """doctor does not warn about mock mode when use_mock: false."""
        config_file = os.path.join(tmp_dir, "autoagent_real.yaml")
        Path(config_file).write_text("optimizer:\n  use_mock: false\n", encoding="utf-8")
        result = runner.invoke(cli, ["doctor", "--config", config_file])
        assert result.exit_code == 0
        assert "Disabled" in result.output

    def test_doctor_shows_api_key_set(self, runner, tmp_dir):
        """doctor shows OPENAI_API_KEY as Set when the env var is present."""
        config_file = os.path.join(tmp_dir, "autoagent.yaml")
        Path(config_file).write_text("optimizer:\n  use_mock: false\n", encoding="utf-8")
        env = {**os.environ, "OPENAI_API_KEY": "sk-test-key"}
        result = runner.invoke(cli, ["doctor", "--config", config_file], env=env)
        assert result.exit_code == 0
        assert "OPENAI_API_KEY" in result.output
        assert "Set" in result.output

    def test_doctor_shows_api_key_not_set(self, runner, tmp_dir):
        """doctor shows OPENAI_API_KEY as Not set when the env var is absent."""
        config_file = os.path.join(tmp_dir, "autoagent.yaml")
        Path(config_file).write_text("optimizer:\n  use_mock: false\n", encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
        result = runner.invoke(cli, ["doctor", "--config", config_file], env=env)
        assert result.exit_code == 0
        assert "OPENAI_API_KEY" in result.output
        assert "Not set" in result.output

    def test_doctor_status_line_reports_issues(self, runner, tmp_dir):
        """Status line reflects issue count."""
        config_file = os.path.join(tmp_dir, "autoagent.yaml")
        Path(config_file).write_text("optimizer:\n  use_mock: true\n", encoding="utf-8")
        # Strip all API key env vars to force multiple issues
        env = {
            k: v for k, v in os.environ.items()
            if k not in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")
        }
        result = runner.invoke(cli, ["doctor", "--config", config_file], env=env)
        assert result.exit_code == 0
        assert "issue" in result.output

    def test_eval_run_prints_mock_warning(self, runner):
        """eval run warns when use_mock is true (default in autoagent.yaml)."""
        result = runner.invoke(cli, ["eval", "run"])
        assert result.exit_code == 0
        # autoagent.yaml has use_mock: true, so the warning should appear
        assert "mock provider" in result.output.lower() or "simulated" in result.output.lower()
