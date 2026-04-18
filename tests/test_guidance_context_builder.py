"""Adapter tests: turning a real (or fake) workspace into a GuidanceContext.

These tests use ``SimpleNamespace`` workspaces to avoid dragging the real
``AgentLabWorkspace`` (and its init requirements) into unit-level tests.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from cli.guidance.context_builder import (
    build_context_from_workspace,
    history_path_for_workspace,
)


def _make_workspace(tmp_path: Path, *, pending: int = 0, best_score: str | None = None) -> SimpleNamespace:
    agentlab_dir = tmp_path / ".agentlab"
    agentlab_dir.mkdir()
    best_file = agentlab_dir / "best_score.txt"
    if best_score is not None:
        best_file.write_text(best_score, encoding="utf-8")
    cards_db = agentlab_dir / "change_cards.db"
    if pending:
        conn = sqlite3.connect(str(cards_db))
        conn.execute(
            "CREATE TABLE change_cards (id INTEGER PRIMARY KEY, status TEXT)"
        )
        conn.executemany(
            "INSERT INTO change_cards(status) VALUES (?)",
            [("pending",) for _ in range(pending)],
        )
        conn.commit()
        conn.close()
    return SimpleNamespace(
        root=tmp_path,
        agentlab_dir=agentlab_dir,
        best_score_file=best_file,
        change_cards_db=cards_db,
        eval_history_db=tmp_path / "eval_history.db",
        memory_db=tmp_path / "optimizer_memory.db",
        runtime_config_path=tmp_path / "agentlab.yaml",
    )


def test_build_context_handles_missing_workspace() -> None:
    ctx = build_context_from_workspace(None)
    assert ctx.workspace is None
    assert ctx.workspace_valid is False


def test_build_context_reads_pending_review_cards(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path, pending=2)
    ctx = build_context_from_workspace(workspace)
    assert ctx.pending_review_cards == 2


def test_build_context_reads_best_score(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path, best_score="0.742")
    ctx = build_context_from_workspace(workspace)
    assert ctx.best_score == "0.742"


def test_build_context_no_best_score_when_file_empty(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path, best_score="")
    ctx = build_context_from_workspace(workspace)
    assert ctx.best_score is None


def test_build_context_populates_now(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path)
    ctx = build_context_from_workspace(workspace, now=1234.0)
    assert ctx.now == 1234.0


def test_build_context_session_store_returns_latest(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path)
    fake_session = SimpleNamespace(session_id="s-abc")
    store = SimpleNamespace(
        list_sessions=lambda limit=1: [fake_session],
        count=lambda: 3,
    )
    ctx = build_context_from_workspace(workspace, session_store=store)
    assert ctx.latest_session_id == "s-abc"
    assert ctx.session_count == 3


def test_build_context_tolerates_session_store_failure(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path)

    def raises(**_kw: object) -> list:
        raise RuntimeError("store broken")

    store = SimpleNamespace(list_sessions=raises)
    ctx = build_context_from_workspace(workspace, session_store=store)
    assert ctx.latest_session_id is None
    assert ctx.session_count == 0


def test_history_path_resolves_under_agentlab_dir(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path)
    path = history_path_for_workspace(workspace)
    assert path == workspace.agentlab_dir / "guidance_history.json"


def test_history_path_none_for_unbound_workspace() -> None:
    assert history_path_for_workspace(None) is None


def test_build_context_survives_unreadable_cards_db(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path)
    # Overwrite the sqlite file with garbage so opening will error.
    workspace.change_cards_db.write_bytes(b"not a database")
    ctx = build_context_from_workspace(workspace)
    assert ctx.pending_review_cards == 0
