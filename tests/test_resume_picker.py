from __future__ import annotations

from pathlib import Path

from cli.sessions.picker import build_picker_rows
from cli.sessions.store import SessionStore, TurnRecord


def _workspace(root: Path, name: str) -> Path:
    path = root / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_build_picker_rows_returns_empty_for_unknown_workspace(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "projects")

    assert build_picker_rows(store, tmp_path / "missing") == []


def test_build_picker_rows_orders_by_last_modified(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "projects")
    workspace_root = _workspace(tmp_path, "workspace")
    first = store.create(workspace_root)
    second = store.create(workspace_root)

    store.append(first.session_id, TurnRecord(role="user", content="older"))
    store.append(second.session_id, TurnRecord(role="user", content="newer"))

    rows = build_picker_rows(store, workspace_root)

    assert [row.session_id for row in rows] == [second.session_id, first.session_id]


def test_build_picker_rows_prefers_session_summary_metadata(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "projects")
    workspace_root = _workspace(tmp_path, "workspace")
    session = store.create(workspace_root)
    store.append(
        session.session_id,
        TurnRecord(
            kind="session_meta",
            metadata={"session_summary": "Deployment debugging thread"},
        ),
    )
    store.append(session.session_id, TurnRecord(role="user", content="actual first message"))

    rows = build_picker_rows(store, workspace_root)

    assert rows[0].summary == "Deployment debugging thread"


def test_build_picker_rows_falls_back_to_first_user_message_and_truncates_preview(
    tmp_path: Path,
) -> None:
    store = SessionStore(tmp_path / "projects")
    workspace_root = _workspace(tmp_path, "workspace")
    session = store.create(workspace_root)
    long_message = "x" * 120
    store.append(session.session_id, TurnRecord(role="user", content=long_message))

    rows = build_picker_rows(store, workspace_root)

    assert rows[0].summary == long_message[:80]
    assert rows[0].last_user_preview == long_message[:80]
