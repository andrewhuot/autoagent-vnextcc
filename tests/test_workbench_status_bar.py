"""Tests for the T06 reactive status bar (`cli/workbench_app/status_bar.py`)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import click
import pytest

from cli.sessions import Session
from cli.workbench_app.status_bar import (
    StatusBar,
    StatusSnapshot,
    render_snapshot,
    snapshot_from_workspace,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class _FakeActiveConfig:
    def __init__(self, version: int = 7, model: str = "gpt-4o") -> None:
        self.version = version
        self.config = {"model": model} if model else {}
        self.path = Path("/tmp/fake.yaml")


class _FakeWorkspace:
    def __init__(
        self,
        *,
        label: str = "demo-ws",
        active: object | None = None,
        cards_db: Path | None = None,
        best_score_file: Path | None = None,
    ) -> None:
        self.workspace_label = label
        self._active = active
        # These attrs need to be real Paths because the status bar does
        # ``.exists()`` / ``.read_text()`` on them.
        self.change_cards_db = cards_db or Path("/nonexistent-cards.db")
        self.best_score_file = best_score_file or Path("/nonexistent-score.txt")

    def resolve_active_config(self):
        return self._active


def _seed_cards_db(tmp_path: Path, pending: int) -> Path:
    db = tmp_path / "change_cards.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE change_cards (id INTEGER PRIMARY KEY, status TEXT)"
    )
    for _ in range(pending):
        conn.execute("INSERT INTO change_cards (status) VALUES ('pending')")
    # Mix in a resolved card so the COUNT() query is doing real work.
    conn.execute("INSERT INTO change_cards (status) VALUES ('resolved')")
    conn.commit()
    conn.close()
    return db


# ---------------------------------------------------------------------------
# snapshot_from_workspace
# ---------------------------------------------------------------------------


def test_snapshot_from_workspace_without_workspace_is_empty() -> None:
    snap = snapshot_from_workspace(None)
    assert snap.workspace_label is None
    assert snap.config_version is None
    assert snap.model is None
    assert snap.pending_reviews == 0
    assert snap.best_score is None
    assert snap.agentlab_version  # always populated


def test_snapshot_from_workspace_pulls_label_version_model() -> None:
    ws = _FakeWorkspace(active=_FakeActiveConfig(version=12, model="claude-sonnet-4"))
    snap = snapshot_from_workspace(ws)
    assert snap.workspace_label == "demo-ws"
    assert snap.config_version == 12
    assert snap.model == "claude-sonnet-4"


def test_snapshot_from_workspace_honors_model_override() -> None:
    ws = _FakeWorkspace(active=_FakeActiveConfig(model="gpt-4o"))
    snap = snapshot_from_workspace(ws, model_override="claude-opus-4-6")
    assert snap.model == "claude-opus-4-6"


def test_snapshot_from_workspace_tolerates_resolve_exception() -> None:
    class _RaisingWorkspace(_FakeWorkspace):
        def resolve_active_config(self):
            raise RuntimeError("db locked")

    snap = snapshot_from_workspace(_RaisingWorkspace())
    # No version/model, but the rest still renders.
    assert snap.config_version is None
    assert snap.model is None
    assert snap.workspace_label == "demo-ws"


def test_snapshot_from_workspace_counts_pending_reviews(tmp_path: Path) -> None:
    db = _seed_cards_db(tmp_path, pending=3)
    ws = _FakeWorkspace(cards_db=db)
    snap = snapshot_from_workspace(ws)
    assert snap.pending_reviews == 3


def test_snapshot_from_workspace_handles_missing_cards_db() -> None:
    ws = _FakeWorkspace(cards_db=Path("/definitely/not/here.db"))
    snap = snapshot_from_workspace(ws)
    assert snap.pending_reviews == 0


def test_snapshot_from_workspace_handles_corrupt_cards_db(tmp_path: Path) -> None:
    db = tmp_path / "bad.db"
    db.write_bytes(b"not a sqlite database at all")
    ws = _FakeWorkspace(cards_db=db)
    snap = snapshot_from_workspace(ws)
    assert snap.pending_reviews == 0  # tolerated


def test_snapshot_from_workspace_reads_best_score(tmp_path: Path) -> None:
    score = tmp_path / "best_score.txt"
    score.write_text("0.873\n", encoding="utf-8")
    ws = _FakeWorkspace(best_score_file=score)
    snap = snapshot_from_workspace(ws)
    assert snap.best_score == "0.873"


def test_snapshot_from_workspace_empty_score_file_is_none(tmp_path: Path) -> None:
    score = tmp_path / "best_score.txt"
    score.write_text("", encoding="utf-8")
    ws = _FakeWorkspace(best_score_file=score)
    snap = snapshot_from_workspace(ws)
    assert snap.best_score is None


def test_snapshot_from_workspace_includes_session_title() -> None:
    session = Session(session_id="s1", title="Improve classifier")
    snap = snapshot_from_workspace(None, session=session)
    assert snap.session_title == "Improve classifier"


# ---------------------------------------------------------------------------
# render_snapshot
# ---------------------------------------------------------------------------


def test_render_snapshot_no_workspace_sentinel() -> None:
    snap = StatusSnapshot(agentlab_version="1.2.3")
    line = render_snapshot(snap, color=False)
    assert "no workspace" in line
    assert "agentlab 1.2.3" in line


def test_render_snapshot_full_content_plain() -> None:
    snap = StatusSnapshot(
        workspace_label="demo",
        config_version=3,
        model="gpt-4o",
        pending_reviews=2,
        best_score="0.91",
        agentlab_version="0.0.1",
    )
    line = render_snapshot(snap, color=False)
    assert "demo" in line
    assert "v003" in line
    assert "gpt-4o" in line
    assert "2 reviews" in line
    assert "score:0.91" in line
    # The " | " separator keeps the order stable for downstream parsing.
    assert line.index("demo") < line.index("v003") < line.index("gpt-4o")
    assert line.index("gpt-4o") < line.index("2 reviews") < line.index("score:0.91")


def test_render_snapshot_singular_review_label() -> None:
    snap = StatusSnapshot(workspace_label="w", pending_reviews=1)
    line = render_snapshot(snap, color=False)
    assert "1 review" in line
    assert "1 reviews" not in line


def test_render_snapshot_hides_zero_reviews() -> None:
    snap = StatusSnapshot(workspace_label="w", pending_reviews=0)
    line = render_snapshot(snap, color=False)
    assert "review" not in line


def test_render_snapshot_color_emits_ansi_codes() -> None:
    snap = StatusSnapshot(workspace_label="demo", pending_reviews=5)
    colored = render_snapshot(snap, color=True)
    plain = render_snapshot(snap, color=False)
    # Colored output carries ANSI escapes; plain does not.
    assert "\x1b[" in colored
    assert "\x1b[" not in plain
    # The unstyled text still matches after stripping escapes.
    assert click.unstyle(colored) == plain


def test_render_snapshot_includes_extras() -> None:
    snap = StatusSnapshot(
        workspace_label="w",
        extras=(("cycle", "3/10"), ("phase", "optimize")),
    )
    line = render_snapshot(snap, color=False)
    assert "cycle:3/10" in line
    assert "phase:optimize" in line


# ---------------------------------------------------------------------------
# StatusBar
# ---------------------------------------------------------------------------


def test_status_bar_refresh_from_workspace_pulls_snapshot(tmp_path: Path) -> None:
    score = tmp_path / "best_score.txt"
    score.write_text("0.5", encoding="utf-8")
    ws = _FakeWorkspace(
        active=_FakeActiveConfig(version=9, model="haiku"),
        best_score_file=score,
    )
    bar = StatusBar()
    snap = bar.refresh_from_workspace(ws)
    assert snap is bar.snapshot
    assert snap.workspace_label == "demo-ws"
    assert snap.config_version == 9
    assert snap.model == "haiku"
    assert snap.best_score == "0.5"


def test_status_bar_update_patches_fields() -> None:
    bar = StatusBar(StatusSnapshot(workspace_label="w", pending_reviews=0))
    bar.update(pending_reviews=4, best_score="0.77")
    assert bar.snapshot.pending_reviews == 4
    assert bar.snapshot.best_score == "0.77"
    # Untouched fields survive the patch.
    assert bar.snapshot.workspace_label == "w"


def test_status_bar_update_rejects_unknown_field() -> None:
    bar = StatusBar()
    with pytest.raises(TypeError, match="unknown fields"):
        bar.update(not_a_real_field="oops")


def test_status_bar_render_round_trips_via_custom_render_fn() -> None:
    captured: list[StatusSnapshot] = []

    def _render(snap: StatusSnapshot) -> str:
        captured.append(snap)
        return f"<<{snap.workspace_label}>>"

    bar = StatusBar(StatusSnapshot(workspace_label="foo"), render_fn=_render)
    assert bar.render() == "<<foo>>"
    assert captured == [bar.snapshot]


def test_status_bar_render_color_false_ignores_custom_render_fn() -> None:
    # color=False goes through the plain renderer, not the injected one —
    # this is the contract tests rely on to assert without ANSI noise.
    def _shouldnt_be_called(_: StatusSnapshot) -> str:
        raise AssertionError("custom render_fn should not run for color=False")

    bar = StatusBar(
        StatusSnapshot(workspace_label="demo"),
        render_fn=_shouldnt_be_called,
    )
    plain = bar.render(color=False)
    assert "demo" in plain
    assert "\x1b[" not in plain
