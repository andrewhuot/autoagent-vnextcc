"""Tests for Stream B usage and budget reporting."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from optimizer.cost_tracker import CostTracker
from runner import cli


@pytest.fixture
def runner() -> CliRunner:
    """Return a CLI runner."""
    return CliRunner()


def _write_eval_result(path: Path, *, total_tokens: int, estimated_cost_usd: float) -> None:
    """Persist a small eval result payload compatible with usage parsing."""
    path.write_text(
        json.dumps(
            {
                "api_version": "1",
                "status": "ok",
                "data": {
                    "quality": 0.8,
                    "safety": 1.0,
                    "latency": 0.9,
                    "cost": 0.7,
                    "composite": 0.85,
                    "total_tokens": total_tokens,
                    "estimated_cost_usd": estimated_cost_usd,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def test_usage_reports_eval_and_budget_surfaces(runner: CliRunner) -> None:
    """`autoagent usage` should summarize eval cost, optimize spend, and budget remaining."""
    with runner.isolated_filesystem():
        init_result = runner.invoke(cli, ["init", "--dir", "."])
        assert init_result.exit_code == 0, init_result.output

        runtime = yaml.safe_load(Path("autoagent.yaml").read_text(encoding="utf-8"))
        runtime["budget"]["daily_dollars"] = 5.0
        Path("autoagent.yaml").write_text(yaml.safe_dump(runtime, sort_keys=False), encoding="utf-8")

        _write_eval_result(Path(".autoagent") / "eval_results_latest.json", total_tokens=321, estimated_cost_usd=0.12)
        tracker = CostTracker(db_path=".autoagent/cost_tracker.db", daily_budget_dollars=5.0)
        tracker.record_cycle("cycle-001", spent_dollars=0.5, improvement_delta=0.1)

        result = runner.invoke(cli, ["usage", "--json"])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["status"] == "ok"
        data = payload["data"]
        assert data["last_eval"]["total_tokens"] == 321
        assert data["last_eval"]["estimated_cost_usd"] == 0.12
        assert data["last_optimize"]["spent_dollars"] == 0.5
        assert data["workspace_spend_usd"] == 0.5
        assert data["configured_budget_usd"] == 5.0
        assert data["budget_remaining_usd"] == pytest.approx(4.5)


def test_optimize_honors_max_budget_flag_before_running(runner: CliRunner) -> None:
    """A zero-dollar max budget should stop optimize before expensive work begins."""
    with runner.isolated_filesystem():
        init_result = runner.invoke(cli, ["init", "--dir", "."])
        assert init_result.exit_code == 0, init_result.output

        result = runner.invoke(cli, ["optimize", "--cycles", "1", "--max-budget-usd", "0"])

        assert result.exit_code == 0, result.output
        assert "budget" in result.output.lower()
        assert "0.00" in result.output


def test_loop_honors_max_budget_flag_before_running(runner: CliRunner) -> None:
    """The loop entrypoint should expose the same budget stop guard."""
    with runner.isolated_filesystem():
        init_result = runner.invoke(cli, ["init", "--dir", "."])
        assert init_result.exit_code == 0, init_result.output

        result = runner.invoke(cli, ["loop", "--max-cycles", "1", "--max-budget-usd", "0"])

        assert result.exit_code == 0, result.output
        assert "budget" in result.output.lower()
        assert "0.00" in result.output
