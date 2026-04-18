"""Tests for the ``/suggest`` slash handler."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from cli.workbench_app.commands import CommandRegistry
from cli.workbench_app.slash import SlashContext, dispatch
from cli.workbench_app.suggest_slash import (
    build_suggest_command,
    select_active_suggestions,
)


@pytest.fixture
def registry() -> CommandRegistry:
    reg = CommandRegistry()
    reg.register(build_suggest_command())
    return reg


def _fake_workspace(tmp_path: Path) -> SimpleNamespace:
    agentlab_dir = tmp_path / ".agentlab"
    agentlab_dir.mkdir()
    return SimpleNamespace(
        root=tmp_path,
        agentlab_dir=agentlab_dir,
        best_score_file=agentlab_dir / "best_score.txt",
        change_cards_db=agentlab_dir / "cards.db",
        eval_history_db=tmp_path / "eval_history.db",
        memory_db=tmp_path / "optimizer_memory.db",
        runtime_config_path=tmp_path / "agentlab.yaml",
    )


def test_suggest_lists_active_suggestions(
    tmp_path: Path, registry: CommandRegistry
) -> None:
    """With a broken workspace we expect at least one suggestion rendered."""
    output: list[str] = []
    ctx = SlashContext(
        workspace=None,  # invalid → broken-workspace rule fires
        echo=output.append,
        registry=registry,
    )
    result = dispatch(ctx, "/suggest", registry=registry)
    assert result.handled
    assert result.error is None
    rendered = "\n".join(output)
    assert "Active Suggestions" in rendered
    assert "Workspace" in rendered  # broken-workspace rule body mentions workspace


def test_suggest_dismiss_requires_id(
    tmp_path: Path, registry: CommandRegistry
) -> None:
    output: list[str] = []
    ctx = SlashContext(
        workspace=_fake_workspace(tmp_path),
        echo=output.append,
        registry=registry,
    )
    result = dispatch(ctx, "/suggest dismiss", registry=registry)
    assert result.handled
    rendered = "\n".join(output)
    assert "Usage" in rendered


def test_suggest_dismiss_persists_history(
    tmp_path: Path, registry: CommandRegistry
) -> None:
    workspace = _fake_workspace(tmp_path)
    output: list[str] = []
    ctx = SlashContext(workspace=workspace, echo=output.append, registry=registry)
    result = dispatch(
        ctx, "/suggest dismiss provider-mock-mode", registry=registry
    )
    assert result.handled
    history_path = workspace.agentlab_dir / "guidance_history.json"
    assert history_path.exists()


def test_suggest_reset_clears_history(
    tmp_path: Path, registry: CommandRegistry
) -> None:
    workspace = _fake_workspace(tmp_path)
    output: list[str] = []
    ctx = SlashContext(workspace=workspace, echo=output.append, registry=registry)
    # Seed a dismissal then reset.
    dispatch(ctx, "/suggest dismiss provider-mock-mode", registry=registry)
    output.clear()
    result = dispatch(ctx, "/suggest reset", registry=registry)
    assert result.handled
    rendered = "\n".join(output)
    assert "cleared" in rendered.lower()


def test_select_active_suggestions_respects_limit(tmp_path: Path) -> None:
    """The helper is reused by the status command — must honor ``limit``."""
    # Workspace=None triggers the broken-workspace rule, so we'll always have
    # at least one suggestion even without configuring state.
    items = select_active_suggestions(None, limit=1)
    assert len(items) <= 1
