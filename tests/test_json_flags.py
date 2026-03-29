"""Tests for --json flag on CLI commands."""
from __future__ import annotations

import json

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


class TestJsonFlags:
    def test_status_json(self, runner):
        result = runner.invoke(cli, ["status", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "config_version" in data
        assert "eval_score" in data
        assert "conversations" in data
        assert "safety_violation_rate" in data
        assert "cycles_run" in data
        assert "failure_buckets" in data
        assert "loop_status" in data
        assert data["loop_status"] == "idle"

    def test_status_json_structure_types(self, runner):
        result = runner.invoke(cli, ["status", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert isinstance(data["conversations"], int)
        assert isinstance(data["safety_violation_rate"], float)
        assert isinstance(data["cycles_run"], int)
        assert isinstance(data["failure_buckets"], dict)

    def test_status_json_does_not_contain_ansi(self, runner):
        result = runner.invoke(cli, ["status", "--json"])
        assert result.exit_code == 0, result.output
        # Should be valid JSON only — no ANSI escape codes or rich output headers
        data = json.loads(result.output)
        assert isinstance(data, dict)

    def test_replay_json(self, runner):
        result = runner.invoke(cli, ["replay", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert isinstance(data, list)

    def test_replay_json_entry_fields(self, runner, tmp_path):
        """When there are attempts, each entry should have the expected fields."""
        from optimizer.memory import OptimizationMemory, OptimizationAttempt
        import time

        mem_db = str(tmp_path / "mem.db")
        mem = OptimizationMemory(db_path=mem_db)
        attempt = OptimizationAttempt(
            attempt_id="test-001",
            timestamp=time.time(),
            change_description="test change",
            config_diff="{}",
            status="accepted",
            config_section="routing",
            score_before=0.5,
            score_after=0.7,
        )
        mem.log(attempt)

        result = runner.invoke(cli, ["replay", "--memory-db", mem_db, "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 1
        entry = data[0]
        assert "version" in entry
        assert "score_before" in entry
        assert "score_after" in entry
        assert "status" in entry
        assert "change_description" in entry
        assert "timestamp" in entry
        assert "config_section" in entry

    def test_explain_json(self, runner):
        result = runner.invoke(cli, ["explain", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "health_label" in data
        assert "success_rate" in data
        assert "failure_buckets" in data
        assert "top_failure" in data
        assert "cycle_count" in data
        assert "config_version" in data

    def test_explain_json_health_label_valid(self, runner):
        result = runner.invoke(cli, ["explain", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["health_label"] in ("Excellent", "Good", "Needs Work", "Critical")
        assert isinstance(data["success_rate"], float)
        assert 0.0 <= data["success_rate"] <= 1.0

    def test_eval_run_json(self, runner):
        result = runner.invoke(cli, ["eval", "run", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "quality" in data
        assert "safety" in data
        assert "latency" in data
        assert "cost" in data
        assert "composite" in data

    def test_eval_run_json_category(self, runner):
        result = runner.invoke(cli, ["eval", "run", "--category", "safety", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "quality" in data
        assert "composite" in data

    def test_optimize_json(self, runner):
        result = runner.invoke(cli, ["optimize", "--cycles", "1", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 1
        entry = data[0]
        assert "cycle" in entry
        assert "total_cycles" in entry
        assert "status" in entry
        assert "accepted" in entry
        assert "score_before" in entry
        assert "score_after" in entry
        assert "change_description" in entry

    def test_optimize_json_multiple_cycles(self, runner):
        result = runner.invoke(cli, ["optimize", "--cycles", "2", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 2
        for i, entry in enumerate(data):
            assert entry["cycle"] == i + 1
            assert entry["total_cycles"] == 2

    def test_skill_list_json(self, runner):
        result = runner.invoke(cli, ["skill", "list", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert isinstance(data, list)
        for skill in data:
            assert "name" in skill
            assert "category" in skill
            assert "platform" in skill
            assert "success_rate" in skill
            assert "times_applied" in skill

    def test_skill_recommend_json(self, runner):
        result = runner.invoke(cli, ["skill", "recommend", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert isinstance(data, list)
        for skill in data:
            assert "name" in skill
            assert "category" in skill
            assert "description" in skill
            assert "proven_improvement" in skill

    def test_status_json_output_is_pure_json(self, runner):
        """Ensure no extra text is output before/after the JSON block."""
        result = runner.invoke(cli, ["status", "--json"])
        assert result.exit_code == 0, result.output
        # Strip whitespace and parse — should not raise
        stripped = result.output.strip()
        data = json.loads(stripped)
        assert isinstance(data, dict)

    def test_explain_json_output_is_pure_json(self, runner):
        """Ensure no extra text is output before/after the JSON block."""
        result = runner.invoke(cli, ["explain", "--json"])
        assert result.exit_code == 0, result.output
        stripped = result.output.strip()
        data = json.loads(stripped)
        assert isinstance(data, dict)

    def test_replay_json_output_is_pure_json(self, runner):
        """Ensure no extra text is output before/after the JSON block."""
        result = runner.invoke(cli, ["replay", "--json"])
        assert result.exit_code == 0, result.output
        stripped = result.output.strip()
        data = json.loads(stripped)
        assert isinstance(data, list)
