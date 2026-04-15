"""Tests for :func:`builder.worker_mode.resolve_effective_worker_mode`.

The effective-mode resolver is what actually picks between the
:class:`DeterministicWorkerAdapter` stub and a live LLM worker when the
operator has not pinned ``AGENTLAB_WORKER_MODE`` by hand. These tests
exist because the previous default silently ran deterministic stubs in
every CLI session — producing identical canned responses, zero thinking
time, and the illusion that the coordinator was doing nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from builder.worker_mode import (
    EffectiveWorkerMode,
    WorkerMode,
    resolve_effective_worker_mode,
)


def _clear_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "AGENTLAB_WORKER_MODE",
    ):
        monkeypatch.delenv(name, raising=False)


def _write_config(root: Path, payload: dict) -> Path:
    path = root / "agentlab.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def test_auto_selects_llm_when_config_and_credentials_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_keys(monkeypatch)
    monkeypatch.setenv("GOOGLE_API_KEY", "ai-key")
    config_path = _write_config(
        tmp_path,
        {
            "harness": {
                "models": {
                    "worker": {
                        "provider": "google",
                        "model": "gemini-2.5-pro",
                        "api_key_env": "GOOGLE_API_KEY",
                    }
                }
            }
        },
    )
    result = resolve_effective_worker_mode(config_path=config_path)
    assert isinstance(result, EffectiveWorkerMode)
    assert result.mode is WorkerMode.LLM
    assert result.source == "autoselect.llm"
    assert "gemini-2.5-pro" in result.reason


def test_falls_back_to_deterministic_when_no_worker_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_keys(monkeypatch)
    config_path = _write_config(tmp_path, {"harness": {"models": {}}})
    result = resolve_effective_worker_mode(config_path=config_path)
    assert result.mode is WorkerMode.DETERMINISTIC
    assert result.source == "autoselect.deterministic"
    assert "no worker model configured" in result.reason


def test_falls_back_to_deterministic_when_credentials_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_keys(monkeypatch)
    config_path = _write_config(
        tmp_path,
        {
            "harness": {
                "models": {
                    "worker": {
                        "provider": "anthropic",
                        "model": "claude-sonnet-4-6",
                    }
                }
            }
        },
    )
    result = resolve_effective_worker_mode(config_path=config_path)
    assert result.mode is WorkerMode.DETERMINISTIC
    assert result.source == "autoselect.deterministic"
    assert "ANTHROPIC_API_KEY" in result.reason


def test_explicit_env_var_wins_over_autoselect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_keys(monkeypatch)
    # Even with a fully valid config, explicit env pin must stick.
    monkeypatch.setenv("GOOGLE_API_KEY", "ai-key")
    monkeypatch.setenv("AGENTLAB_WORKER_MODE", "deterministic")
    config_path = _write_config(
        tmp_path,
        {
            "harness": {
                "models": {
                    "worker": {
                        "provider": "google",
                        "model": "gemini-2.5-pro",
                        "api_key_env": "GOOGLE_API_KEY",
                    }
                }
            }
        },
    )
    result = resolve_effective_worker_mode(config_path=config_path)
    assert result.mode is WorkerMode.DETERMINISTIC
    assert result.source == "env"


def test_explicit_env_llm_wins_even_without_config(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_keys(monkeypatch)
    monkeypatch.setenv("AGENTLAB_WORKER_MODE", "llm")
    # No config path supplied; caller opted in to LLM explicitly.
    result = resolve_effective_worker_mode()
    assert result.mode is WorkerMode.LLM
    assert result.source == "env"


def test_invalid_env_value_stays_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_keys(monkeypatch)
    monkeypatch.setenv("AGENTLAB_WORKER_MODE", "rainbow")
    result = resolve_effective_worker_mode()
    assert result.mode is WorkerMode.DETERMINISTIC
    assert result.source == "env.invalid"


def test_invalid_partial_harness_stays_deterministic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_keys(monkeypatch)
    monkeypatch.setenv("GOOGLE_API_KEY", "ai-key")
    config_path = _write_config(
        tmp_path,
        {
            "harness": {"models": {"worker": {"provider": "google"}}}  # missing model key
        },
    )
    result = resolve_effective_worker_mode(config_path=config_path)
    assert result.mode is WorkerMode.DETERMINISTIC
    assert result.source == "autoselect.deterministic"
