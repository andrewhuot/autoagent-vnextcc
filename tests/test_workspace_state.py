"""Regression tests for explicit API workspace-state detection."""

from __future__ import annotations

from pathlib import Path

import yaml

from api.workspace_state import resolve_workspace_state
from cli.workspace import AgentLabWorkspace


def _create_valid_workspace(root: Path) -> AgentLabWorkspace:
    """Create a minimal workspace with an active config for resolver tests."""
    workspace = AgentLabWorkspace.create(
        root,
        name=root.name,
        template="customer-support",
        agent_name="Support Bot",
        platform="Google ADK",
    )
    workspace.ensure_structure()
    config_path = workspace.configs_dir / "v001.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "model": "mock-model",
                "prompts": {"root": "Help customers with order questions."},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    workspace.set_active_config(1, filename="v001.yaml")
    return workspace


def test_workspace_state_is_invalid_without_workspace(tmp_path: Path, monkeypatch) -> None:
    """A non-workspace startup path should be explicit and recoverable."""
    monkeypatch.delenv("AGENTLAB_WORKSPACE", raising=False)

    state = resolve_workspace_state(start=tmp_path)

    assert state.valid is False
    assert state.source == "cwd"
    assert state.current_path == str(tmp_path.resolve())
    assert state.workspace_root is None
    assert "No AgentLab workspace found" in state.message
    assert any("agentlab server --workspace" in command for command in state.recovery_commands)
    assert any("agentlab init" in command for command in state.recovery_commands)


def test_workspace_state_is_invalid_when_workspace_has_no_active_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A workspace directory without a resolvable active config is not runtime-valid."""
    monkeypatch.delenv("AGENTLAB_WORKSPACE", raising=False)
    workspace = AgentLabWorkspace.create(
        tmp_path,
        name="empty-workspace",
        template="customer-support",
        agent_name="Support Bot",
        platform="Google ADK",
    )
    workspace.save_metadata()

    state = resolve_workspace_state(start=tmp_path)

    assert state.valid is False
    assert state.workspace_root == str(tmp_path.resolve())
    assert state.workspace_label == "empty-workspace"
    assert state.active_config_path is None
    assert "No active config" in state.message
    assert any("agentlab init" in command for command in state.recovery_commands)


def test_workspace_state_is_valid_for_initialized_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A workspace with metadata and an active config should be marked valid."""
    monkeypatch.delenv("AGENTLAB_WORKSPACE", raising=False)
    workspace = _create_valid_workspace(tmp_path)

    state = resolve_workspace_state(start=tmp_path / "configs")

    assert state.valid is True
    assert state.source == "cwd"
    assert state.workspace_root == str(workspace.root)
    assert state.workspace_label == workspace.workspace_label
    assert state.active_config_path == str(workspace.configs_dir / "v001.yaml")
    assert state.active_config_version == 1
    assert state.message == "AgentLab workspace is ready."


def test_explicit_workspace_path_is_preferred_over_cwd(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """AGENTLAB_WORKSPACE should decouple server startup from process CWD."""
    workspace_root = tmp_path / "valid-workspace"
    bad_cwd = tmp_path / "not-a-workspace"
    bad_cwd.mkdir()
    workspace = _create_valid_workspace(workspace_root)
    monkeypatch.setenv("AGENTLAB_WORKSPACE", str(workspace_root))

    state = resolve_workspace_state(start=bad_cwd)

    assert state.valid is True
    assert state.source == "env"
    assert state.current_path == str(bad_cwd.resolve())
    assert state.workspace_root == str(workspace.root)
