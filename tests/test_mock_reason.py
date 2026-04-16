"""Unit tests for cli.mock_reason (R1.12)."""
from __future__ import annotations

from pathlib import Path

import pytest

from cli.mock_reason import MockReasonResult, compute_mock_reason


@pytest.fixture
def clean_env(monkeypatch):
    for var in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_GENAI_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    yield


def _write_yaml(tmp_path: Path, use_mock: bool | None) -> Path:
    path = tmp_path / "agentlab.yaml"
    if use_mock is None:
        path.write_text("name: test\n")
    else:
        path.write_text(f"optimizer:\n  use_mock: {'true' if use_mock else 'false'}\n")
    return path


def test_disabled_when_runtime_use_mock_false(tmp_path, clean_env):
    result = compute_mock_reason(runtime_use_mock=False, config_path=str(_write_yaml(tmp_path, False)))
    assert result.reason == "disabled"
    assert not result.is_blocking
    assert not result.is_warning


def test_configured_when_yaml_explicitly_sets_use_mock_true(tmp_path, clean_env):
    path = _write_yaml(tmp_path, True)
    result = compute_mock_reason(runtime_use_mock=True, config_path=str(path))
    assert result.reason == "configured"
    assert result.is_warning
    assert not result.is_blocking


def test_missing_provider_key_when_yaml_doesnt_set_it(tmp_path, clean_env):
    path = _write_yaml(tmp_path, None)
    result = compute_mock_reason(runtime_use_mock=True, config_path=str(path))
    assert result.reason == "missing_provider_key"
    assert result.is_blocking


def test_missing_key_beats_cli_override_when_yaml_false(tmp_path, clean_env):
    """YAML says false, runtime says true (via mode override), no key -> missing_provider_key."""
    path = _write_yaml(tmp_path, False)
    result = compute_mock_reason(runtime_use_mock=True, config_path=str(path))
    assert result.reason == "missing_provider_key"


def test_configured_when_runtime_true_yaml_false_but_key_present(tmp_path, clean_env, monkeypatch):
    """CLI override forced mock even though key exists - treat as configured."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-" + "a" * 40)
    path = _write_yaml(tmp_path, False)
    result = compute_mock_reason(runtime_use_mock=True, config_path=str(path))
    assert result.reason == "configured"


def test_missing_config_path(tmp_path, clean_env):
    result = compute_mock_reason(runtime_use_mock=True, config_path=None)
    # No config to check, no key present -> missing key
    assert result.reason == "missing_provider_key"


def test_nonexistent_config_path(tmp_path, clean_env):
    result = compute_mock_reason(runtime_use_mock=True, config_path=str(tmp_path / "nope.yaml"))
    assert result.reason == "missing_provider_key"


def test_malformed_yaml_not_use_mock_true(tmp_path, clean_env):
    """Broken yaml shouldn't crash or claim configured; fall through to key check."""
    path = tmp_path / "agentlab.yaml"
    path.write_text("this is not: [valid yaml\n")
    result = compute_mock_reason(runtime_use_mock=True, config_path=str(path))
    assert result.reason == "missing_provider_key"


def test_gemini_key_satisfies_has_key(monkeypatch, tmp_path):
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSy" + "x" * 35)
    path = _write_yaml(tmp_path, False)
    # YAML says false but runtime says mock - with key present, treated as configured (override)
    result = compute_mock_reason(runtime_use_mock=True, config_path=str(path))
    assert result.reason == "configured"
