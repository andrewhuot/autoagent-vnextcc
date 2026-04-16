"""ImprovementLineageStore.backfill_orphans — idempotent backfill of
pre-R2 eval artifacts into the lineage store.

Policy: scan EvalResultsStore (.agentlab/eval_results.db by default)
for run_ids that don't yet have an eval_run lineage event, insert them,
and drop a sentinel file so subsequent invocations no-op quickly.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from optimizer.improvement_lineage import (
    EVENT_EVAL_RUN,
    ImprovementLineageStore,
)


def _seed_eval_results_db(db_path: Path, run_ids: list[str]) -> None:
    """Write a minimal EvalResultsStore schema + rows the backfill will find."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS result_runs (
                run_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                mode TEXT NOT NULL,
                config_snapshot TEXT NOT NULL,
                summary TEXT NOT NULL
            )
            """
        )
        for i, run_id in enumerate(run_ids):
            summary = json.dumps({"composite": 0.8 + i * 0.01})
            conn.execute(
                "INSERT INTO result_runs(run_id, created_at, mode, config_snapshot, summary) "
                "VALUES (?, ?, ?, ?, ?)",
                (run_id, "2026-04-17T00:00:00Z", "mock", "{}", summary),
            )
        conn.commit()


@pytest.fixture
def agentlab_root(tmp_path, monkeypatch):
    """A fake .agentlab/ directory rooted at tmp_path."""
    root = tmp_path / ".agentlab"
    root.mkdir()
    return root


def test_backfill_inserts_orphan_eval_runs(agentlab_root):
    eval_db = agentlab_root / "eval_results.db"
    _seed_eval_results_db(eval_db, ["orphan-001", "orphan-002", "orphan-003"])

    lineage_db = agentlab_root / "improvement_lineage.db"
    store = ImprovementLineageStore(db_path=str(lineage_db))

    n = store.backfill_orphans(root=str(agentlab_root))
    assert n == 3

    events = [e for e in store.recent(100) if e.event_type == EVENT_EVAL_RUN]
    assert len(events) == 3
    payload_run_ids = {e.payload.get("eval_run_id") for e in events}
    assert payload_run_ids == {"orphan-001", "orphan-002", "orphan-003"}


def test_backfill_is_idempotent(agentlab_root):
    eval_db = agentlab_root / "eval_results.db"
    _seed_eval_results_db(eval_db, ["only-001"])

    store = ImprovementLineageStore(db_path=str(agentlab_root / "lineage.db"))
    n1 = store.backfill_orphans(root=str(agentlab_root))
    assert n1 == 1
    n2 = store.backfill_orphans(root=str(agentlab_root))
    assert n2 == 0
    # Sentinel file exists:
    assert (agentlab_root / ".lineage_backfill_done").exists()


def test_backfill_skips_already_linked_run_ids(agentlab_root):
    eval_db = agentlab_root / "eval_results.db"
    _seed_eval_results_db(eval_db, ["pre-linked", "fresh"])

    lineage_db = agentlab_root / "improvement_lineage.db"
    store = ImprovementLineageStore(db_path=str(lineage_db))
    # Simulate an already-present event: record_eval_run was called for pre-linked.
    store.record_eval_run(eval_run_id="pre-linked", attempt_id="", composite_score=0.9)

    n = store.backfill_orphans(root=str(agentlab_root))
    assert n == 1  # only 'fresh' is orphan

    events = [
        e for e in store.recent(100)
        if e.event_type == EVENT_EVAL_RUN
    ]
    run_ids = [e.payload.get("eval_run_id") for e in events]
    assert run_ids.count("pre-linked") == 1  # not double-inserted
    assert "fresh" in run_ids


def test_backfill_noop_when_no_eval_db(agentlab_root):
    """If .agentlab/eval_results.db doesn't exist, backfill is a no-op (returns 0)."""
    store = ImprovementLineageStore(db_path=str(agentlab_root / "l.db"))
    n = store.backfill_orphans(root=str(agentlab_root))
    assert n == 0


def test_backfill_recovers_composite_score_from_summary(agentlab_root):
    eval_db = agentlab_root / "eval_results.db"
    _seed_eval_results_db(eval_db, ["with-score"])
    store = ImprovementLineageStore(db_path=str(agentlab_root / "l.db"))
    store.backfill_orphans(root=str(agentlab_root))
    events = [e for e in store.recent(100) if e.event_type == EVENT_EVAL_RUN]
    assert len(events) == 1
    # Score should have been parsed from the summary JSON:
    assert events[0].payload.get("composite_score") == pytest.approx(0.80, abs=1e-6)


def test_backfill_swallows_summary_parse_errors(agentlab_root):
    """A run_row with malformed summary JSON is still backfilled; composite_score=None."""
    eval_db = agentlab_root / "eval_results.db"
    eval_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(eval_db)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS result_runs (
                run_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                mode TEXT NOT NULL,
                config_snapshot TEXT NOT NULL,
                summary TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO result_runs(run_id, created_at, mode, config_snapshot, summary) "
            "VALUES (?, ?, ?, ?, ?)",
            ("malformed", "2026-04-17T00:00:00Z", "mock", "{}", "not-json"),
        )
        conn.commit()

    store = ImprovementLineageStore(db_path=str(agentlab_root / "l.db"))
    n = store.backfill_orphans(root=str(agentlab_root))
    assert n == 1
    events = [e for e in store.recent(100) if e.event_type == EVENT_EVAL_RUN]
    assert events[0].payload.get("composite_score") is None
