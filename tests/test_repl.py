"""Tests for cli/repl.py — interactive REPL shell."""

from __future__ import annotations

import warnings
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cli.repl import (
    SLASH_COMMANDS,
    _build_status_bar,
    _compact_session,
    _handle_slash_command,
    run_shell,
)
from cli.sessions import Session


def test_status_bar_no_workspace() -> None:
    assert _build_status_bar(None) == "no workspace"


def test_status_bar_with_workspace(tmp_path: Path) -> None:
    workspace = MagicMock()
    workspace.workspace_label = "test-ws"
    workspace.resolve_active_config.return_value = None
    workspace.change_cards_db = tmp_path / "nope.db"
    workspace.best_score_file = tmp_path / "nope.txt"
    bar = _build_status_bar(workspace)
    assert "test-ws" in bar


def test_status_bar_with_config(tmp_path: Path) -> None:
    workspace = MagicMock()
    workspace.workspace_label = "ws"
    config = MagicMock()
    config.version = 3
    workspace.resolve_active_config.return_value = config
    workspace.change_cards_db = tmp_path / "nope.db"
    workspace.best_score_file = tmp_path / "nope.txt"
    bar = _build_status_bar(workspace)
    assert "v003" in bar


def test_slash_exit() -> None:
    session = Session(session_id="x", title="t")
    store = MagicMock()
    result = _handle_slash_command(
        "/exit",
        workspace=None,
        session=session,
        session_store=store,
    )
    assert result is True


def test_slash_help() -> None:
    session = Session(session_id="x", title="t")
    store = MagicMock()
    result = _handle_slash_command(
        "/help",
        workspace=None,
        session=session,
        session_store=store,
    )
    assert result is False


def test_slash_unknown() -> None:
    session = Session(session_id="x", title="t")
    store = MagicMock()
    result = _handle_slash_command(
        "/foobar",
        workspace=None,
        session=session,
        session_store=store,
    )
    assert result is False


def test_slash_config_no_workspace() -> None:
    session = Session(session_id="x", title="t")
    store = MagicMock()
    result = _handle_slash_command(
        "/config",
        workspace=None,
        session=session,
        session_store=store,
    )
    assert result is False


def test_slash_config_with_workspace() -> None:
    workspace = MagicMock()
    config = MagicMock()
    config.version = 5
    config.path = "/tmp/v005.yaml"
    config.config = {"model": "gpt-4o"}
    workspace.resolve_active_config.return_value = config
    workspace.summarize_config.return_value = "gpt-4o"
    session = Session(session_id="x", title="t")
    store = MagicMock()
    result = _handle_slash_command(
        "/config",
        workspace=workspace,
        session=session,
        session_store=store,
    )
    assert result is False


def test_slash_mcp_routes_to_status(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []

    def _fake_run_click_command(command_path: str) -> None:
        called.append(command_path)

    monkeypatch.setattr("cli.repl._run_click_command", _fake_run_click_command)
    session = Session(session_id="x", title="t")
    store = MagicMock()

    result = _handle_slash_command(
        "/mcp",
        workspace=None,
        session=session,
        session_store=store,
    )

    assert result is False
    assert called == ["mcp status"]


def test_compact_session_writes_file(tmp_path: Path) -> None:
    workspace = MagicMock()
    workspace.agentlab_dir = tmp_path / ".agentlab"
    workspace.agentlab_dir.mkdir(parents=True)

    session = Session(
        session_id="abc",
        title="Test Session",
        started_at=1000000.0,
        active_goal="fix bug",
        command_history=["/status", "/doctor"],
        transcript=[],
    )
    _compact_session(session, workspace)
    summary_path = workspace.agentlab_dir / "memory" / "latest_session.md"
    assert summary_path.exists()
    content = summary_path.read_text(encoding="utf-8")
    assert "Test Session" in content
    assert "/status" in content


def test_compact_session_no_workspace() -> None:
    session = Session(session_id="x", title="t")
    _compact_session(session, None)


def test_all_slash_commands_documented() -> None:
    expected = {
        "/help",
        "/status",
        "/config",
        "/memory",
        "/doctor",
        "/review",
        "/mcp",
        "/compact",
        "/resume",
        "/exit",
    }
    assert set(SLASH_COMMANDS.keys()) == expected


def test_run_shell_emits_deprecation_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """T25: classic shell is deprecated and must surface a warning.

    The workbench app is the new default entry point; ``--classic``
    stays functional for one release but must signal the migration.
    """
    workspace = MagicMock()
    workspace.root = tmp_path
    workspace.workspace_label = "ws"
    workspace.agentlab_dir = tmp_path / ".agentlab"
    workspace.resolve_active_config.return_value = None
    workspace.change_cards_db = tmp_path / "nope.db"
    workspace.best_score_file = tmp_path / "nope.txt"

    monkeypatch.setattr("cli.repl.resolve_settings", lambda **_: {})
    monkeypatch.setattr("cli.repl.resolve_cli_ui", lambda *_a, **_kw: "text")
    monkeypatch.setattr("builtins.input", lambda *_a, **_kw: (_ for _ in ()).throw(EOFError()))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        run_shell(workspace)

    deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert deprecations, "run_shell must emit a DeprecationWarning"
    message = str(deprecations[0].message)
    assert "cli.repl.run_shell" in message
    assert "workbench" in message.lower()
