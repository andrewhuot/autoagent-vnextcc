"""Tests for workspace ``.env`` hydration from the CLI entry point.

Previously, launching the interactive workbench via ``agentlab`` did not
load ``.agentlab/.env`` into ``os.environ``. The coordinator runtime
then could not resolve provider credentials for
``harness.models.worker``, silently fell back to the deterministic stub,
and every worker turn produced the same canned output.

These tests lock the fix in place: when ``cli()`` enters a workspace,
the workspace env file must be hydrated before any runtime is built.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from runner import _enter_discovered_workspace


def test_enter_discovered_workspace_hydrates_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    agentlab_dir = tmp_path / ".agentlab"
    agentlab_dir.mkdir()
    (agentlab_dir / ".env").write_text("GOOGLE_API_KEY=ai-from-env-file\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    _enter_discovered_workspace("doctor")

    assert os.environ.get("GOOGLE_API_KEY") == "ai-from-env-file"


def test_enter_discovered_workspace_does_not_override_existing_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "already-in-shell")
    agentlab_dir = tmp_path / ".agentlab"
    agentlab_dir.mkdir()
    (agentlab_dir / ".env").write_text("GOOGLE_API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    _enter_discovered_workspace("doctor")

    assert os.environ.get("GOOGLE_API_KEY") == "already-in-shell"


def test_enter_discovered_workspace_skips_for_init_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``init`` / ``new`` run pre-workspace, so they must not touch env."""
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    agentlab_dir = tmp_path / ".agentlab"
    agentlab_dir.mkdir()
    (agentlab_dir / ".env").write_text("GOOGLE_API_KEY=should-not-load\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert _enter_discovered_workspace("init") is None
    assert "GOOGLE_API_KEY" not in os.environ
