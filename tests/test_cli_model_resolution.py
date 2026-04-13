"""Credential-aware effective model resolution tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.model import (
    _credentialled_models,
    _model_is_credentialled,
    effective_model_surface,
)
from runner import cli


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Scaffold an empty workspace in a tmp dir and chdir to it."""
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["init", "--dir", "."])
    assert result.exit_code == 0, result.output
    return tmp_path


def _clear_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_only_google_key_routes_both_roles_to_gemini(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With only GOOGLE_API_KEY set, proposer and evaluator both resolve to the Gemini model."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-google-key")

    surface = effective_model_surface(workspace)

    assert surface["proposer"]["key"] == "google:gemini-2.5-pro"
    assert surface["evaluator"]["key"] == "google:gemini-2.5-pro"
    assert surface["proposer"]["credentialed"] is True
    assert surface["evaluator"]["credentialed"] is True


def test_only_anthropic_key_routes_both_roles_to_claude(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With only ANTHROPIC_API_KEY set, proposer and evaluator both resolve to Claude."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-anthropic-key")

    surface = effective_model_surface(workspace)

    assert surface["proposer"]["key"] == "anthropic:claude-sonnet-4-5"
    assert surface["evaluator"]["key"] == "anthropic:claude-sonnet-4-5"


def test_multiple_keys_split_proposer_and_evaluator(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With several keys set, roles use distinct models via the fallback_index ordering."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-anthropic")

    surface = effective_model_surface(workspace)

    assert surface["proposer"]["key"] == "openai:gpt-4o"
    assert surface["evaluator"]["key"] == "anthropic:claude-sonnet-4-5"


def test_no_keys_falls_back_to_full_list_and_flags_uncredentialed(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no keys set, surface still populates but flags both roles as non-credentialled."""
    _clear_provider_env(monkeypatch)

    surface = effective_model_surface(workspace)

    assert surface["proposer"] is not None
    assert surface["evaluator"] is not None
    assert surface["proposer"]["credentialed"] is False
    assert surface["evaluator"]["credentialed"] is False


def test_explicit_override_honored_even_if_uncredentialed(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """User overrides to a model without credentials are preserved but flagged."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-google-key")

    runner = CliRunner()
    set_result = runner.invoke(cli, ["model", "set", "proposer", "openai:gpt-4o"])
    assert set_result.exit_code == 0, set_result.output

    surface = effective_model_surface(workspace)
    assert surface["proposer"]["key"] == "openai:gpt-4o"
    assert surface["proposer"]["credentialed"] is False
    assert surface["evaluator"]["credentialed"] is True


def test_show_models_text_output_marks_credential_status(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`agentlab model show` text output should indicate whether each role has a key."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-google-key")

    result = CliRunner().invoke(cli, ["model", "show"])
    assert result.exit_code == 0, result.output
    assert "google:gemini-2.5-pro" in result.output
    assert "key set" in result.output


def test_show_models_warns_when_override_missing_key(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the user's override has no key, the text surface should warn about the missing env var."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-google-key")

    runner = CliRunner()
    set_result = runner.invoke(cli, ["model", "set", "proposer", "openai:gpt-4o"])
    assert set_result.exit_code == 0, set_result.output

    show_result = runner.invoke(cli, ["model", "show"])
    assert show_result.exit_code == 0, show_result.output
    assert "missing OPENAI_API_KEY" in show_result.output


def test_credentialled_models_helper_filters_by_env(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_credentialled_models returns only models with api_key_env populated."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")

    from agent.config.runtime import load_runtime_config
    runtime = load_runtime_config(str(workspace / "agentlab.yaml"))
    subset = _credentialled_models(runtime)

    assert [m.provider for m in subset] == ["anthropic"]
    anthropic = next(m for m in runtime.optimizer.models if m.provider == "anthropic")
    openai = next(m for m in runtime.optimizer.models if m.provider == "openai")
    assert _model_is_credentialled(anthropic) is True
    assert _model_is_credentialled(openai) is False


def test_show_json_includes_credential_flag(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """JSON output exposes the `credentialed` flag for UIs to render warnings."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_API_KEY", "fake")

    result = CliRunner().invoke(cli, ["model", "show", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["data"]["proposer"]["credentialed"] is True
    assert payload["data"]["proposer"]["api_key_env"] == "GOOGLE_API_KEY"
