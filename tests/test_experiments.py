"""Unit tests for experiment cards and the ExperimentStore."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from optimizer.experiments import ExperimentCard, ExperimentStore


def _make_card(
    experiment_id: str = "exp-001",
    status: str = "pending",
    created_at: float | None = None,
    hypothesis: str = "Improve quality via prompt rewrite",
) -> ExperimentCard:
    """Build a minimal ExperimentCard for tests."""
    return ExperimentCard(
        experiment_id=experiment_id,
        created_at=created_at or time.time(),
        hypothesis=hypothesis,
        touched_surfaces=["instruction"],
        touched_agents=["root"],
        diff_summary="Rewrote root prompt",
        eval_set_versions={"golden": "abc123"},
        replay_set_hash="hash123",
        baseline_sha="sha_base",
        candidate_sha="sha_cand",
        risk_class="low",
        deployment_policy="pr_only",
        rollback_handle="rollback_001",
        total_experiment_cost=0.05,
        status=status,
        result_summary="",
        operator_name="instruction_rewrite",
        baseline_scores={"quality": 0.7, "safety": 1.0},
        candidate_scores={"quality": 0.8, "safety": 1.0},
        significance_p_value=0.03,
        significance_delta=0.1,
    )


def test_experiment_store_save_and_get(tmp_path: Path) -> None:
    """Save an experiment card and retrieve it by ID."""
    store = ExperimentStore(db_path=str(tmp_path / "experiments.db"))
    card = _make_card(experiment_id="exp-save-get")
    store.save(card)

    retrieved = store.get("exp-save-get")
    assert retrieved is not None
    assert retrieved.experiment_id == "exp-save-get"
    assert retrieved.hypothesis == card.hypothesis
    assert retrieved.touched_surfaces == ["instruction"]
    assert retrieved.baseline_scores == {"quality": 0.7, "safety": 1.0}
    assert retrieved.significance_p_value == pytest.approx(0.03)


def test_experiment_store_list_recent(tmp_path: Path) -> None:
    """Save 3 cards and verify list_recent returns them newest-first."""
    store = ExperimentStore(db_path=str(tmp_path / "experiments.db"))
    now = time.time()
    for i in range(3):
        card = _make_card(experiment_id=f"exp-{i}", created_at=now + i)
        store.save(card)

    recent = store.list_recent(limit=10)
    assert len(recent) == 3
    # Most recent first
    assert recent[0].experiment_id == "exp-2"
    assert recent[1].experiment_id == "exp-1"
    assert recent[2].experiment_id == "exp-0"


def test_experiment_store_list_by_status(tmp_path: Path) -> None:
    """Filter cards by status — only accepted cards returned."""
    store = ExperimentStore(db_path=str(tmp_path / "experiments.db"))
    now = time.time()
    store.save(_make_card(experiment_id="e1", status="pending", created_at=now))
    store.save(_make_card(experiment_id="e2", status="accepted", created_at=now + 1))
    store.save(_make_card(experiment_id="e3", status="rejected", created_at=now + 2))
    store.save(_make_card(experiment_id="e4", status="accepted", created_at=now + 3))

    accepted = store.list_by_status("accepted")
    assert len(accepted) == 2
    assert all(c.status == "accepted" for c in accepted)
    # Newest first
    assert accepted[0].experiment_id == "e4"


def test_experiment_store_update_status(tmp_path: Path) -> None:
    """Update a card from pending to accepted."""
    store = ExperimentStore(db_path=str(tmp_path / "experiments.db"))
    store.save(_make_card(experiment_id="exp-update", status="pending"))

    store.update_status("exp-update", "accepted", result_summary="Quality improved by 10%")

    card = store.get("exp-update")
    assert card is not None
    assert card.status == "accepted"
    assert card.result_summary == "Quality improved by 10%"


def test_experiment_store_get_nonexistent(tmp_path: Path) -> None:
    """Getting a non-existent experiment should return None."""
    store = ExperimentStore(db_path=str(tmp_path / "experiments.db"))
    assert store.get("does-not-exist") is None
