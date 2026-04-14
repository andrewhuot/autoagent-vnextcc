"""Tests for workspace-scoped model surfaces."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from runner import cli


@pytest.fixture
def runner() -> CliRunner:
    """Return a CLI runner."""
    return CliRunner()


def test_model_list_and_show_surface_workspace_effective_models(runner: CliRunner) -> None:
    """The model commands should expose available and effective runtime models."""
    with runner.isolated_filesystem():
        init_result = runner.invoke(cli, ["init", "--dir", "."])
        assert init_result.exit_code == 0, init_result.output

        list_result = runner.invoke(cli, ["model", "list", "--json"])
        assert list_result.exit_code == 0, list_result.output
        list_payload = json.loads(list_result.output)
        assert list_payload["status"] == "ok"
        assert any(item["provider"] == "openai" for item in list_payload["data"])

        show_result = runner.invoke(cli, ["model", "show", "--json"])
        assert show_result.exit_code == 0, show_result.output
        show_payload = json.loads(show_result.output)
        assert show_payload["data"]["proposer"]
        assert show_payload["data"]["evaluator"]


def test_mode_without_subcommand_behaves_like_show(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`agentlab mode` should behave like `agentlab mode show`."""
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli, ["mode"])

    assert result.exit_code == 0, result.output
    assert "Current mode:" in result.output


def test_model_without_subcommand_behaves_like_show(runner: CliRunner) -> None:
    """`agentlab model` should surface the effective model summary directly."""
    with runner.isolated_filesystem():
        init_result = runner.invoke(cli, ["init", "--dir", "."])
        assert init_result.exit_code == 0, init_result.output

        result = runner.invoke(cli, ["model"])

        assert result.exit_code == 0, result.output
        assert "Effective models" in result.output


def test_provider_without_subcommand_behaves_like_status(runner: CliRunner) -> None:
    """`agentlab provider` should show provider status instead of erroring."""
    with runner.isolated_filesystem():
        init_result = runner.invoke(cli, ["init", "--dir", "."])
        assert init_result.exit_code == 0, init_result.output

        result = runner.invoke(cli, ["provider"])

        assert result.exit_code == 0, result.output
        assert "Configured providers" in result.output
        assert "runtime config" in result.output


def test_model_set_writes_workspace_settings_overrides(runner: CliRunner) -> None:
    """Per-workspace proposer/evaluator overrides should live in `.agentlab/settings.json`."""
    with runner.isolated_filesystem():
        init_result = runner.invoke(cli, ["init", "--dir", "."])
        assert init_result.exit_code == 0, init_result.output

        proposer_result = runner.invoke(cli, ["model", "set", "proposer", "anthropic:claude-sonnet-4-5"])
        evaluator_result = runner.invoke(cli, ["model", "set", "evaluator", "google:gemini-2.5-pro"])

        assert proposer_result.exit_code == 0, proposer_result.output
        assert evaluator_result.exit_code == 0, evaluator_result.output

        settings = json.loads((Path(".agentlab") / "settings.json").read_text(encoding="utf-8"))
        assert settings["models"]["proposer"] == "anthropic:claude-sonnet-4-5"
        assert settings["models"]["evaluator"] == "google:gemini-2.5-pro"

        show_result = runner.invoke(cli, ["model", "show", "--json"])
        show_payload = json.loads(show_result.output)
        assert show_payload["data"]["proposer"]["key"] == "anthropic:claude-sonnet-4-5"
        assert show_payload["data"]["evaluator"]["key"] == "google:gemini-2.5-pro"


def test_provider_configure_normalizes_fully_qualified_model_input(runner: CliRunner) -> None:
    """Provider setup should accept `provider:model` input without duplicating the provider prefix."""
    with runner.isolated_filesystem():
        init_result = runner.invoke(cli, ["init", "--dir", "."])
        assert init_result.exit_code == 0, init_result.output

        configure_result = runner.invoke(
            cli,
            ["provider", "configure"],
            input="openai\nopenai:gpt-4o\nOPENAI_API_KEY\n",
        )
        assert configure_result.exit_code == 0, configure_result.output
        assert "Applied: provider openai:gpt-4o" in configure_result.output

        list_result = runner.invoke(cli, ["model", "list", "--json"])
        assert list_result.exit_code == 0, list_result.output
        list_payload = json.loads(list_result.output)
        assert list_payload["status"] == "ok"
        assert [item["key"] for item in list_payload["data"]] == ["openai:gpt-4o"]

        show_result = runner.invoke(cli, ["model", "show", "--json"])
        assert show_result.exit_code == 0, show_result.output
        show_payload = json.loads(show_result.output)
        assert show_payload["data"]["proposer"]["key"] == "openai:gpt-4o"
        assert show_payload["data"]["evaluator"]["key"] == "openai:gpt-4o"


def test_provider_configure_accepts_and_saves_api_key(runner: CliRunner) -> None:
    """Provider setup should be able to take a pasted API key and enable live mode."""
    with runner.isolated_filesystem():
        init_result = runner.invoke(cli, ["init", "--dir", ".", "--mode", "mock"])
        assert init_result.exit_code == 0, init_result.output

        configure_result = runner.invoke(
            cli,
            [
                "provider",
                "configure",
                "--provider",
                "openai",
                "--model",
                "gpt-4o",
                "--api-key",
                "sk-live-test",
            ],
        )

        assert configure_result.exit_code == 0, configure_result.output
        assert "Saved OPENAI_API_KEY to .agentlab/.env" in configure_result.output
        env_file = Path(".agentlab") / ".env"
        assert "OPENAI_API_KEY=sk-live-test" in env_file.read_text(encoding="utf-8")
        runtime = yaml.safe_load(Path("agentlab.yaml").read_text(encoding="utf-8"))
        assert runtime["optimizer"]["use_mock"] is False
