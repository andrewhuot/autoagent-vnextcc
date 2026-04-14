"""Tests for cli/onboarding.py — guided onboarding."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from cli.onboarding import OnboardingResult, run_onboarding


def _clear_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "GOOGLE_GENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_onboarding_exit_returns_none_workspace() -> None:
    with patch("click.prompt", return_value="3"):
        result = run_onboarding()
    assert isinstance(result, OnboardingResult)
    assert result.workspace is None


def test_onboarding_detects_existing_key_and_defaults_to_live(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_keys(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    with patch("click.prompt", side_effect=["1"]):
        result = run_onboarding()
    assert result.workspace == "demo"
    assert result.mode == "live"
    assert result.saved_key_env is None


def test_onboarding_without_key_prompts_and_saves(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear_keys(monkeypatch)
    monkeypatch.chdir(tmp_path)
    with patch("click.prompt", side_effect=["2", "3", "fake-google-key"]):
        result = run_onboarding()
    assert result.workspace == "empty"
    assert result.mode == "live"
    assert result.saved_key_env == "GOOGLE_API_KEY"
    env_file = tmp_path / ".agentlab" / ".env"
    assert env_file.exists()
    assert "GOOGLE_API_KEY=fake-google-key" in env_file.read_text(encoding="utf-8")


def test_onboarding_provider_prompt_defaults_to_api_key_collection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """First-run onboarding should make live/API-key setup the default path."""
    _clear_keys(monkeypatch)
    monkeypatch.chdir(tmp_path)
    defaults: list[str | None] = []

    def fake_prompt(*args, **kwargs):  # noqa: ANN002, ANN003
        defaults.append(kwargs.get("default"))
        if len(defaults) == 1:
            return "1"
        return "4"

    with patch("click.prompt", side_effect=fake_prompt):
        result = run_onboarding()

    assert result.mode == "mock"
    assert defaults[:2] == ["1", "1"]


def test_onboarding_user_picks_mock_for_now(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear_keys(monkeypatch)
    monkeypatch.chdir(tmp_path)
    with patch("click.prompt", side_effect=["1", "4"]):
        result = run_onboarding()
    assert result.workspace == "demo"
    assert result.mode == "mock"
    assert result.saved_key_env is None
    assert not (tmp_path / ".agentlab" / ".env").exists()


def test_onboarding_empty_key_input_falls_back_to_mock(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear_keys(monkeypatch)
    monkeypatch.chdir(tmp_path)
    with patch("click.prompt", side_effect=["1", "1", "   "]):
        result = run_onboarding()
    assert result.mode == "mock"
    assert result.saved_key_env is None


def test_onboarding_gemini_alias_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    """GEMINI_API_KEY in env should satisfy live-mode detection via alias hydration."""
    _clear_keys(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "sk-gemini")
    with patch("click.prompt", return_value="2"):
        result = run_onboarding()
    assert result.mode == "live"
