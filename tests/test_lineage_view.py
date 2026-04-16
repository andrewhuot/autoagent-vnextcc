"""AttemptLineageView aggregator over the event stream."""
from __future__ import annotations

import pytest

from optimizer.improvement_lineage import (
    AttemptLineageView,
    ImprovementLineageStore,
)


@pytest.fixture
def store(tmp_path):
    return ImprovementLineageStore(db_path=str(tmp_path / "lineage.db"))


def test_view_attempt_flattens_full_chain(store):
    aid = "a1b2c3d4"
    store.record_eval_run(eval_run_id="r1", attempt_id=aid, composite_score=0.80)
    store.record_attempt(
        attempt_id=aid,
        status="accepted",
        score_before=0.80,
        score_after=0.85,
        eval_run_id="r1",
    )
    store.record_deployment(attempt_id=aid, deployment_id="d1", version=3)
    store.record_measurement(
        attempt_id=aid,
        measurement_id="m1",
        composite_delta=0.04,
        eval_run_id="r2",
    )
    view = store.view_attempt(aid)
    assert isinstance(view, AttemptLineageView)
    assert view.attempt_id == aid
    assert view.eval_run_id == "r1"
    assert view.deployment_id == "d1"
    assert view.deployed_version == 3
    assert view.measurement_id == "m1"
    assert view.composite_delta == 0.04
    assert view.status == "accepted"
    assert len(view.events) == 4


def test_view_attempt_partial_chain(store):
    store.record_attempt(attempt_id="a1", status="proposed")
    view = store.view_attempt("a1")
    assert view.status == "proposed"
    assert view.eval_run_id is None
    assert view.deployment_id is None
    assert view.measurement_id is None
    assert view.composite_delta is None
    assert len(view.events) == 1


def test_view_attempt_unknown_id_is_empty_view(store):
    view = store.view_attempt("does-not-exist")
    assert view.attempt_id == "does-not-exist"
    assert view.status is None
    assert view.events == []


def test_view_attempt_recognizes_legacy_promote_event(store):
    """Existing API path emits `promote` (not our new `deployment`).
    view_attempt() must surface it as the deployment."""
    aid = "legacy01"
    store.record(aid, "promote", version=5, payload={"deployment_id": "legacy-d1"})
    view = store.view_attempt(aid)
    assert view.deployment_id == "legacy-d1"
    assert view.deployed_version == 5


def test_view_attempt_recognizes_legacy_deploy_canary(store):
    aid = "legacy02"
    store.record(aid, "deploy_canary", version=2, payload={"deployment_id": "canary-1"})
    view = store.view_attempt(aid)
    assert view.deployment_id == "canary-1"
    assert view.deployed_version == 2


def test_view_attempt_rollback_clears_version(store):
    """A rollback after promote should surface as a rolled-back attempt.
    We keep deployed_version populated (last-deployed) but set `rolled_back=True`."""
    aid = "rb000001"
    store.record(aid, "promote", version=3, payload={"deployment_id": "d1"})
    store.record(aid, "rollback", version=3, payload={"deployment_id": "d1"})
    view = store.view_attempt(aid)
    assert view.rolled_back is True
    assert view.deployed_version == 3


def test_view_attempt_latest_attempt_status_wins(store):
    aid = "upd00001"
    store.record_attempt(attempt_id=aid, status="proposed")
    store.record_attempt(attempt_id=aid, status="accepted", score_after=0.9)
    view = store.view_attempt(aid)
    assert view.status == "accepted"
    assert view.score_after == 0.9


def test_view_attempt_rejection_surfaced(store):
    aid = "rej00001"
    store.record_attempt(attempt_id=aid, status="rejected_regression",
                         score_before=0.8, score_after=0.75)
    store.record_rejection(attempt_id=aid, reason="regression_detected",
                           detail="drop 0.05")
    view = store.view_attempt(aid)
    assert view.status == "rejected_regression"
    assert view.rejection_reason == "regression_detected"
    assert view.rejection_detail == "drop 0.05"


def test_view_attempt_parent_attempt_id(store):
    aid = "child001"
    store.record_attempt(
        attempt_id=aid, status="proposed",
        parent_attempt_id="parent01",
    )
    view = store.view_attempt(aid)
    assert view.parent_attempt_id == "parent01"
