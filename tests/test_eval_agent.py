"""Tests for live eval-agent fallback behavior."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

import agent
from agent.eval_agent import ConfiguredEvalAgent, _load_default_config
from evals.fixtures.mock_data import mock_agent_response
from runner import cli


class FailingRouter:
    """Router stub that simulates a live-provider failure."""

    mock_mode = False
    mock_reason = ""

    def generate(self, request):  # noqa: ANN001
        del request
        raise RuntimeError("provider unavailable")


def _read_json(path: Path) -> dict:
    """Load a JSON file used by CLI assertions."""
    return json.loads(path.read_text(encoding="utf-8"))


def test_configured_eval_agent_falls_back_to_mock_on_provider_error() -> None:
    """Provider failures should degrade to deterministic mock responses instead of crashing evals."""
    default_config = _load_default_config()
    eval_agent = ConfiguredEvalAgent(
        llm_router=FailingRouter(),
        default_config=default_config,
    )

    result = eval_agent.run("How do I reset my password?")

    assert result == mock_agent_response("How do I reset my password?", default_config)
    assert eval_agent.mock_mode is True
    assert any("falling back to deterministic mock responses" in message.lower() for message in eval_agent.mock_mode_messages)


def test_eval_run_real_agent_survives_provider_errors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """`autoagent eval run --real-agent` should finish even when the live router fails."""
    runner = CliRunner()
    workspace = tmp_path / "fallback-agent"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace), "--no-synthetic-data"])
    assert init_result.exit_code == 0, init_result.output

    monkeypatch.chdir(workspace)
    failing_agent = ConfiguredEvalAgent(
        llm_router=FailingRouter(),
        default_config=_load_default_config(),
    )
    monkeypatch.setattr(
        agent,
        "create_eval_agent",
        lambda runtime, force_real_agent=False, default_config=None: failing_agent,
    )

    result = runner.invoke(cli, ["eval", "run", "--real-agent"])

    assert result.exit_code == 0, result.output
    assert "mixed mode" in result.output.lower()
    assert "Warning:" in result.output
    assert "falling back to deterministic mock responses" in result.output.lower()
    latest = _read_json(workspace / ".autoagent" / "eval_results_latest.json")
    assert latest["mode"] == "mixed"
    assert latest["total"] == 3
    assert latest["passed"] == 2
    assert any(
        "falling back to deterministic mock responses" in warning.lower()
        for warning in latest["scores"]["warnings"]
    )
    assert failing_agent.mock_mode is True


def test_eval_run_require_live_fails_when_provider_falls_back(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """`autoagent eval run --require-live` should fail instead of silently persisting mock results."""
    runner = CliRunner()
    workspace = tmp_path / "require-live-agent"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace), "--no-synthetic-data"])
    assert init_result.exit_code == 0, init_result.output

    monkeypatch.chdir(workspace)
    failing_agent = ConfiguredEvalAgent(
        llm_router=FailingRouter(),
        default_config=_load_default_config(),
    )
    monkeypatch.setattr(
        agent,
        "create_eval_agent",
        lambda runtime, force_real_agent=False, default_config=None: failing_agent,
    )

    result = runner.invoke(cli, ["eval", "run", "--require-live"])

    assert result.exit_code != 0
    assert "require live" in result.output.lower() or "live eval required" in result.output.lower()
    assert not (workspace / ".autoagent" / "eval_results_latest.json").exists()
