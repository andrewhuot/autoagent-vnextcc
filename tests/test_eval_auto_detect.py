"""Tests for eval auto-detection of LLM credentials and --mock flag."""

from __future__ import annotations

import os

import pytest
from click.testing import CliRunner

from runner import _has_llm_credentials, cli


# ---------------------------------------------------------------------------
# _has_llm_credentials unit tests
# ---------------------------------------------------------------------------

_CREDENTIAL_VARS = [
    "GOOGLE_API_KEY",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
]


def _strip_all_credentials(monkeypatch) -> None:
    """Remove every recognized credential env var."""
    for var in _CREDENTIAL_VARS:
        monkeypatch.delenv(var, raising=False)


class TestHasLlmCredentials:
    """Unit tests for _has_llm_credentials()."""

    def test_returns_false_when_no_env_vars(self, monkeypatch):
        _strip_all_credentials(monkeypatch)
        assert _has_llm_credentials() is False

    @pytest.mark.parametrize("var", _CREDENTIAL_VARS)
    def test_returns_true_when_single_var_set(self, monkeypatch, var):
        _strip_all_credentials(monkeypatch)
        monkeypatch.setenv(var, "test-key-value")
        assert _has_llm_credentials() is True

    def test_returns_true_when_multiple_vars_set(self, monkeypatch):
        _strip_all_credentials(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        assert _has_llm_credentials() is True

    def test_returns_false_when_var_is_empty_string(self, monkeypatch):
        _strip_all_credentials(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        assert _has_llm_credentials() is False


# ---------------------------------------------------------------------------
# CLI flag integration tests (eval run --mock / --real-agent)
# ---------------------------------------------------------------------------

def _env_without_api_keys() -> dict[str, str]:
    """Return a process environment with provider credentials stripped."""
    env = dict(os.environ)
    for var in _CREDENTIAL_VARS:
        env[var] = ""
    return env


def _env_with_api_key() -> dict[str, str]:
    """Return a process environment with one credential set."""
    env = dict(os.environ)
    for var in _CREDENTIAL_VARS:
        env[var] = ""
    env["OPENAI_API_KEY"] = "sk-test-auto-detect"
    return env


class TestEvalRunMockFlag:
    """Verify --mock flag appears in CLI help and controls agent mode banner."""

    def test_mock_flag_in_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["eval", "run", "--help"])
        assert result.exit_code == 0
        assert "--mock" in result.output
        assert "Force mock agent" in result.output

    def test_real_agent_flag_still_in_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["eval", "run", "--help"])
        assert result.exit_code == 0
        assert "--real-agent" in result.output


class TestEvalRunModeBanner:
    """Verify mode banner output for different flag/env combinations."""

    def test_mock_flag_shows_mock_banner(self, monkeypatch):
        _strip_all_credentials(monkeypatch)
        runner = CliRunner()
        result = runner.invoke(cli, ["eval", "run", "--mock"], env=_env_without_api_keys())
        assert "Running evals with mock agent (--mock flag)" in result.output

    def test_mock_flag_overrides_credentials(self, monkeypatch):
        """--mock should force mock even when credentials exist."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        runner = CliRunner()
        result = runner.invoke(cli, ["eval", "run", "--mock"], env=_env_with_api_key())
        assert "Running evals with mock agent (--mock flag)" in result.output

    def test_no_credentials_auto_detects_mock(self, monkeypatch):
        _strip_all_credentials(monkeypatch)
        runner = CliRunner()
        result = runner.invoke(cli, ["eval", "run"], env=_env_without_api_keys())
        assert "Running evals with mock agent (no LLM credentials found" in result.output

    def test_credentials_auto_detects_real(self, monkeypatch):
        """When credentials are present and no flag given, auto-detect real mode."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-auto-detect")
        runner = CliRunner()
        result = runner.invoke(cli, ["eval", "run"], env=_env_with_api_key())
        assert "Running evals with real agent (credentials auto-detected)" in result.output

    def test_real_agent_flag_shows_real_banner(self, monkeypatch):
        _strip_all_credentials(monkeypatch)
        runner = CliRunner()
        result = runner.invoke(cli, ["eval", "run", "--real-agent"], env=_env_without_api_keys())
        assert "Running evals with real agent (--real-agent flag)" in result.output
