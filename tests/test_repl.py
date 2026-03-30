"""Tests for cli/repl.py — interactive REPL shell."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from cli.repl import (
    SLASH_COMMANDS,
    _build_status_bar,
    _compact_session,
    _handle_slash_command,
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


def test_compact_session_writes_file(tmp_path: Path) -> None:
    workspace = MagicMock()
    workspace.autoagent_dir = tmp_path / ".autoagent"
    workspace.autoagent_dir.mkdir(parents=True)

    session = Session(
        session_id="abc",
        title="Test Session",
        started_at=1000000.0,
        active_goal="fix bug",
        command_history=["/status", "/doctor"],
        transcript=[],
    )
    _compact_session(session, workspace)
    summary_path = workspace.autoagent_dir / "memory" / "latest_session.md"
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
