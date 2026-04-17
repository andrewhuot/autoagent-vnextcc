from __future__ import annotations

import threading
from pathlib import Path

import pytest

from cli.sessions import Session as LegacySession
from cli.sessions import SessionStore as LegacySessionStore
from cli.sessions.store import SessionStore, TurnRecord


def _workspace(root: Path, name: str) -> Path:
    path = root / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _turn(*, role: str, content: str) -> TurnRecord:
    return TurnRecord(role=role, content=content)


def test_legacy_cli_sessions_imports_still_work() -> None:
    session = LegacySession(session_id="legacy")
    store = LegacySessionStore(Path("/tmp"))

    assert session.session_id == "legacy"
    assert isinstance(store, LegacySessionStore)


def test_load_drops_only_partial_final_line(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    store = SessionStore(tmp_path / "projects")
    workspace_root = _workspace(tmp_path, "workspace")
    session = store.create(workspace_root)

    store.append(session.session_id, _turn(role="user", content="hello"))

    session_file = next((tmp_path / "projects").glob("**/*.jsonl"))
    with session_file.open("a", encoding="utf-8") as handle:
        handle.write("{\"kind\":\"turn\",\"role\":\"assistant\"")

    records = store.load(session.session_id)

    assert [record.role for record in records if record.kind == "turn"] == ["user"]
    assert "dropping partial final line" in caplog.text


def test_load_raises_for_non_terminal_corruption(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "projects")
    workspace_root = _workspace(tmp_path, "workspace")
    session = store.create(workspace_root)
    session_file = next((tmp_path / "projects").glob("**/*.jsonl"))

    session_file.write_text(
        "{\"kind\":\"turn\",\"role\":\"user\",\"content\":\"ok\"}\n"
        "{\"kind\":\"turn\"\n"
        "{\"kind\":\"turn\",\"role\":\"assistant\",\"content\":\"later\"}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        store.load(session.session_id)


def test_slug_collision_adds_hash_suffix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import cli.sessions.store as store_module

    store = SessionStore(tmp_path / "projects")
    first_workspace = _workspace(tmp_path, "first")
    second_workspace = _workspace(tmp_path, "second")

    monkeypatch.setattr(store_module, "_slug_base", lambda _path: "shared-slug")

    first = store.create(first_workspace)
    second = store.create(second_workspace)

    assert first.workspace_slug == "shared-slug"
    assert second.workspace_slug.startswith("shared-slug-")
    assert len(second.workspace_slug.split("-")[-1]) == 4


def test_concurrent_appends_preserve_all_turns(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "projects")
    workspace_root = _workspace(tmp_path, "workspace")
    session = store.create(workspace_root)

    def append_turn(index: int) -> None:
        store.append(
            session.session_id,
            _turn(role="user", content=f"line-{index}"),
        )

    threads = [threading.Thread(target=append_turn, args=(index,)) for index in range(25)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    records = store.load(session.session_id)
    user_contents = sorted(
        (
            record.content
            for record in records
            if record.kind == "turn" and record.content
        ),
        key=lambda value: int(value.split("-")[-1]),
    )

    assert user_contents == [f"line-{index}" for index in range(25)]


def test_list_for_workspace_returns_preview_and_turn_count(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "projects")
    workspace_root = _workspace(tmp_path, "workspace")
    session = store.create(workspace_root)
    store.append(session.session_id, _turn(role="assistant", content="hi"))
    store.append(session.session_id, _turn(role="user", content="show me the latest deploy summary"))

    summaries = store.list_for_workspace(workspace_root)

    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.session_id == session.session_id
    assert summary.turn_count == 2
    assert summary.last_user_preview == "show me the latest deploy summary"
