"""Tests for cli/sessions.py — session persistence."""

from __future__ import annotations

from pathlib import Path

from cli.sessions import Session, SessionEntry, SessionStore


def test_session_entry_roundtrip() -> None:
    entry = SessionEntry(role="user", content="hello", timestamp=100.0)
    rebuilt = SessionEntry.from_dict(entry.to_dict())
    assert rebuilt.role == "user"
    assert rebuilt.content == "hello"
    assert rebuilt.timestamp == 100.0


def test_session_roundtrip() -> None:
    session = Session(
        session_id="abc123",
        title="Test",
        started_at=1.0,
        updated_at=2.0,
        transcript=[SessionEntry(role="user", content="hi", timestamp=1.5)],
        command_history=["/status"],
        active_goal="fix bug",
        pending_next_actions=["deploy"],
        settings_overrides={"mode": "plan"},
    )
    rebuilt = Session.from_dict(session.to_dict())
    assert rebuilt.session_id == "abc123"
    assert rebuilt.title == "Test"
    assert len(rebuilt.transcript) == 1
    assert rebuilt.transcript[0].content == "hi"
    assert rebuilt.command_history == ["/status"]
    assert rebuilt.active_goal == "fix bug"
    assert rebuilt.pending_next_actions == ["deploy"]
    assert rebuilt.settings_overrides == {"mode": "plan"}


def test_create_session(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    session = store.create(title="My Session")
    assert session.session_id
    assert session.title == "My Session"
    assert session.started_at > 0


def test_get_session(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    created = store.create(title="Lookup Test")
    fetched = store.get(created.session_id)
    assert fetched is not None
    assert fetched.title == "Lookup Test"


def test_get_missing_session(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    assert store.get("nonexistent") is None


def test_list_sessions(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    store.create(title="First")
    store.create(title="Second")
    sessions = store.list_sessions()
    assert len(sessions) == 2
    assert sessions[0].title == "Second"


def test_list_sessions_limit(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    for i in range(5):
        store.create(title=f"S{i}")
    assert len(store.list_sessions(limit=3)) == 3


def test_delete_session(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    session = store.create(title="To Delete")
    assert store.delete(session.session_id) is True
    assert store.get(session.session_id) is None


def test_delete_missing_session(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    assert store.delete("nope") is False


def test_latest_session(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    old = store.create(title="Old")
    old.updated_at = 1000.0
    store.save(old)
    new = store.create(title="New")
    new.updated_at = 2000.0
    store.save(new)
    latest = store.latest()
    assert latest is not None
    assert latest.title == "New"


def test_latest_when_empty(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    assert store.latest() is None


def test_append_entry(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    session = store.create()
    store.append_entry(session, "user", "hello world")
    reloaded = store.get(session.session_id)
    assert reloaded is not None
    assert len(reloaded.transcript) == 1
    assert reloaded.transcript[0].content == "hello world"


def test_append_command(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    session = store.create()
    store.append_command(session, "/status")
    reloaded = store.get(session.session_id)
    assert reloaded is not None
    assert reloaded.command_history == ["/status"]
