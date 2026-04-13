"""Tests for workspace-local environment loading."""

from __future__ import annotations

from cli.workspace_env import load_workspace_env


def test_load_workspace_env_does_not_override_explicit_blank_values(tmp_path) -> None:
    """An explicit blank env var should disable the saved workspace key for that process."""
    env_dir = tmp_path / ".agentlab"
    env_dir.mkdir()
    (env_dir / ".env").write_text("GOOGLE_API_KEY=g-test-saved-key\n", encoding="utf-8")
    environ = {"GOOGLE_API_KEY": ""}

    load_workspace_env(tmp_path, environ=environ)

    assert environ["GOOGLE_API_KEY"] == ""


def test_load_workspace_env_populates_missing_values(tmp_path) -> None:
    """Missing env vars should still hydrate from the workspace-local env file."""
    env_dir = tmp_path / ".agentlab"
    env_dir.mkdir()
    (env_dir / ".env").write_text("GOOGLE_API_KEY=g-test-saved-key\n", encoding="utf-8")
    environ: dict[str, str] = {}

    load_workspace_env(tmp_path, environ=environ)

    assert environ["GOOGLE_API_KEY"] == "g-test-saved-key"
