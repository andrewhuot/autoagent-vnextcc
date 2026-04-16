"""evals/runner.py emits an eval_run lineage event after minting run_id."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from evals.runner import EvalRunner
from evals.scorer import CompositeScore, EvalResult
from optimizer.improvement_lineage import (
    EVENT_EVAL_RUN,
    ImprovementLineageStore,
)


@pytest.fixture
def lineage_db(tmp_path, monkeypatch):
    db_path = tmp_path / "lineage.db"
    monkeypatch.setenv("AGENTLAB_IMPROVEMENT_LINEAGE_DB", str(db_path))
    return db_path


def _fake_runner(tmp_path) -> EvalRunner:
    """Construct a minimal EvalRunner that doesn't touch an agent or cache."""
    agent_fn = MagicMock(spec=[], return_value={"response": "", "specialist": "support"})
    agent_fn.__name__ = "fake_agent"
    runner = EvalRunner(
        agent_fn=agent_fn,
        history_store=None,
        cache_enabled=False,
        cache_db_path=str(tmp_path / "eval_cache.db"),
    )
    # Prevent results_store from writing anywhere relevant during _persist_history
    # (it isn't called from _persist_history but keep it isolated anyway).
    runner.results_store = MagicMock()
    return runner


def _fake_score() -> CompositeScore:
    """Hand-constructed CompositeScore with a couple of results."""
    results = [
        EvalResult(
            case_id="c1",
            category="support",
            passed=True,
            quality_score=1.0,
            safety_passed=True,
            latency_ms=120.0,
            token_count=80,
        ),
        EvalResult(
            case_id="c2",
            category="support",
            passed=False,
            quality_score=0.5,
            safety_passed=True,
            latency_ms=200.0,
            token_count=150,
        ),
    ]
    return CompositeScore(
        quality=0.75,
        safety=1.0,
        tool_use_accuracy=1.0,
        latency=0.8,
        cost=0.9,
        composite=0.82,
        total_cases=2,
        passed_cases=1,
        results=results,
    )


def test_persist_history_emits_eval_run_event(lineage_db, tmp_path):
    runner = _fake_runner(tmp_path)
    score = _fake_score()
    runner._persist_history(
        score,
        dataset_path="configs/some_dataset.yaml",
        split="all",
    )
    store = ImprovementLineageStore(db_path=str(lineage_db))
    events = [e for e in store.recent(100) if e.event_type == EVENT_EVAL_RUN]
    assert len(events) == 1
    payload = events[0].payload
    assert payload["eval_run_id"] == score.run_id
    assert payload["composite_score"] == score.composite
    assert payload["config_path"] == "configs/some_dataset.yaml"
    assert payload["case_count"] == 2


def test_persist_history_does_not_crash_when_lineage_db_unwritable(
    tmp_path, monkeypatch
):
    """Lineage write failures must not break eval."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir")
    # Path underneath a regular file cannot be created as a DB.
    monkeypatch.setenv(
        "AGENTLAB_IMPROVEMENT_LINEAGE_DB", str(blocker / "lineage.db")
    )
    runner = _fake_runner(tmp_path)
    score = _fake_score()
    # Must not raise.
    runner._persist_history(score, dataset_path=None, split="all")


def test_persist_history_skips_when_env_empty(tmp_path, monkeypatch):
    """Setting the env var to empty string disables lineage emit."""
    monkeypatch.setenv("AGENTLAB_IMPROVEMENT_LINEAGE_DB", "")
    runner = _fake_runner(tmp_path)
    score = _fake_score()
    # Should not raise and should not create any DB.
    runner._persist_history(score, dataset_path=None, split="all")


def test_persist_history_handles_missing_composite(lineage_db, tmp_path):
    """A score with composite=0.0 still round-trips without error."""
    runner = _fake_runner(tmp_path)
    score = CompositeScore(total_cases=0, passed_cases=0, results=[])
    runner._persist_history(score, dataset_path=None, split="all")
    store = ImprovementLineageStore(db_path=str(lineage_db))
    events = [e for e in store.recent(100) if e.event_type == EVENT_EVAL_RUN]
    assert len(events) == 1
    assert events[0].payload["case_count"] == 0
    assert events[0].payload["config_path"] == ""
