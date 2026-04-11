"""API tests for reviewable change-card decisions."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.changes import router
from deployer.versioning import ConfigVersionManager
from optimizer.change_card import ChangeCardStore, ProposedChangeCard
from optimizer.experiments import ExperimentCard, ExperimentStore


def _make_change_card(
    card_id: str,
    experiment_id: str,
    *,
    candidate_version: int = 12,
) -> ProposedChangeCard:
    """Build a pending change card linked to one experiment."""
    return ProposedChangeCard(
        card_id=card_id,
        title="Strengthen root prompt",
        why="Fix routing failures from the latest eval run",
        experiment_card_id=experiment_id,
        candidate_config_version=candidate_version,
        candidate_config_path=f"/workspace/.agentlab/configs/v{candidate_version:03d}.yaml",
        source_eval_path="/workspace/.agentlab/evals/run-123.json",
        status="pending",
        created_at=time.time(),
    )


def _make_experiment(experiment_id: str) -> ExperimentCard:
    """Build a pending experiment card that should mirror review decisions."""
    return ExperimentCard(
        experiment_id=experiment_id,
        created_at=time.time(),
        hypothesis="Strengthen root prompt",
        touched_surfaces=["prompts.root"],
        touched_agents=["root"],
        diff_summary="Prompt rewrite",
        eval_set_versions={},
        replay_set_hash="",
        baseline_sha="base",
        candidate_sha="candidate",
        risk_class="low",
        deployment_policy="pr_only",
        rollback_handle="rollback",
        total_experiment_cost=0.0,
        status="pending",
        result_summary="",
        operator_name="prompt_rewrite",
    )


def _client_with_stores(tmp_path: Path) -> tuple[TestClient, ChangeCardStore, ExperimentStore]:
    """Return a minimal app whose change decisions share card and experiment stores."""
    change_store = ChangeCardStore(db_path=str(tmp_path / "changes.db"))
    experiment_store = ExperimentStore(db_path=str(tmp_path / "experiments.db"))
    experiment_store.save(_make_experiment("exp-001"))
    change_store.save(_make_change_card("card-001", "exp-001"))

    app = FastAPI()
    app.include_router(router)
    app.state.change_card_store = change_store
    app.state.experiment_store = experiment_store
    return TestClient(app), change_store, experiment_store


def test_apply_change_card_accepts_linked_experiment(tmp_path: Path) -> None:
    client, change_store, experiment_store = _client_with_stores(tmp_path)

    response = client.post("/api/changes/card-001/apply")

    assert response.status_code == 200
    assert change_store.get("card-001").status == "applied"  # type: ignore[union-attr]
    experiment = experiment_store.get("exp-001")
    assert experiment is not None
    assert experiment.status == "accepted"
    assert "card-001" in experiment.result_summary


def test_apply_change_card_promotes_candidate_when_version_state_is_available(tmp_path: Path) -> None:
    change_store = ChangeCardStore(db_path=str(tmp_path / "changes.db"))
    experiment_store = ExperimentStore(db_path=str(tmp_path / "experiments.db"))
    version_manager = ConfigVersionManager(configs_dir=str(tmp_path / "configs"))
    version_manager.save_version({"prompt": "old"}, scores={"composite": 0.72}, status="active")
    candidate = version_manager.save_version({"prompt": "new"}, scores={"composite": 0.84}, status="canary")
    experiment_store.save(_make_experiment("exp-001"))
    change_store.save(_make_change_card("card-001", "exp-001", candidate_version=candidate.version))

    app = FastAPI()
    app.include_router(router)
    app.state.change_card_store = change_store
    app.state.experiment_store = experiment_store
    app.state.version_manager = version_manager
    client = TestClient(app)

    response = client.post("/api/changes/card-001/apply")

    assert response.status_code == 200
    assert response.json()["candidate_promoted"] is True
    assert version_manager.manifest["active_version"] == candidate.version


def test_reject_change_card_rejects_linked_experiment(tmp_path: Path) -> None:
    client, change_store, experiment_store = _client_with_stores(tmp_path)

    response = client.post("/api/changes/card-001/reject", json={"reason": "insufficient evidence"})

    assert response.status_code == 200
    assert change_store.get("card-001").status == "rejected"  # type: ignore[union-attr]
    experiment = experiment_store.get("exp-001")
    assert experiment is not None
    assert experiment.status == "rejected"
    assert "insufficient evidence" in experiment.result_summary
