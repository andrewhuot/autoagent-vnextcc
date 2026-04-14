"""Tests for cli/harness_doctor.py — Coordinator section of /doctor."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from cli.harness_doctor import render_coordinator_section


@dataclass
class _FakeWorkspace:
    root: Path

    @property
    def runtime_config_path(self) -> Path:
        return self.root / "agentlab.yaml"


def _write_config(root: Path, payload: dict) -> None:
    (root / "agentlab.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")


def _clear_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_render_coordinator_section_happy_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_keys(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    _write_config(
        tmp_path,
        {
            "harness": {
                "models": {
                    "coordinator": {
                        "provider": "anthropic",
                        "model": "claude-opus-4-6",
                        "api_key_env": "ANTHROPIC_API_KEY",
                    },
                    "worker": {
                        "provider": "anthropic",
                        "model": "claude-sonnet-4-6",
                        "api_key_env": "ANTHROPIC_API_KEY",
                    },
                }
            }
        },
    )
    workspace = _FakeWorkspace(root=tmp_path)

    output = render_coordinator_section(workspace)

    assert "Coordinator" in output
    assert "Worker mode:" in output
    assert "deterministic" in output  # default when AGENTLAB_WORKER_MODE unset
    assert "Coordinator model:" in output
    assert "claude-opus-4-6" in output
    assert "Worker model:" in output
    assert "claude-sonnet-4-6" in output
    assert "harness.models.coordinator" in output
    assert "harness.models.worker" in output
    assert "Credentials:" in output
    assert "ANTHROPIC_API_KEY" in output
    assert "present" in output


def test_render_coordinator_section_reports_llm_worker_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_keys(monkeypatch)
    monkeypatch.setenv("AGENTLAB_WORKER_MODE", "llm")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    _write_config(
        tmp_path,
        {
            "harness": {
                "models": {
                    "coordinator": {"provider": "openai", "model": "gpt-5"},
                    "worker": {"provider": "openai", "model": "gpt-4.1-mini"},
                }
            }
        },
    )
    output = render_coordinator_section(_FakeWorkspace(root=tmp_path))
    assert "Worker mode:        llm" in output


# ---------------------------------------------------------------------------
# Sad paths
# ---------------------------------------------------------------------------


def test_render_coordinator_section_missing_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_keys(monkeypatch)
    # No agentlab.yaml in tmp_path at all.
    workspace = _FakeWorkspace(root=tmp_path)
    output = render_coordinator_section(workspace)
    assert "Coordinator model:" in output
    assert "not configured" in output
    assert "deterministic stubs" in output


def test_render_coordinator_section_invalid_partial_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_keys(monkeypatch)
    _write_config(
        tmp_path,
        {
            "harness": {
                "models": {
                    "coordinator": {"provider": "anthropic"},
                    "worker": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
                }
            }
        },
    )
    output = render_coordinator_section(_FakeWorkspace(root=tmp_path))
    assert "invalid" in output
    assert "harness.models.coordinator.invalid" in output


def test_render_coordinator_section_missing_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_keys(monkeypatch)
    _write_config(
        tmp_path,
        {
            "harness": {
                "models": {
                    "coordinator": {
                        "provider": "anthropic",
                        "model": "claude-opus-4-6",
                    },
                    "worker": {
                        "provider": "anthropic",
                        "model": "claude-sonnet-4-6",
                    },
                }
            }
        },
    )
    output = render_coordinator_section(_FakeWorkspace(root=tmp_path))
    assert "missing ANTHROPIC_API_KEY" in output
    assert "live mode will fail" in output


def test_render_coordinator_section_no_workspace() -> None:
    output = render_coordinator_section(None)
    assert "Coordinator" in output
    assert "Worker mode:" in output
    assert "no workspace" in output
