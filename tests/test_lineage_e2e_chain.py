"""End-to-end lineage chain: eval_run -> attempt -> deployment -> measurement.

Exercises each R2 emission site with realistic inputs and verifies that
view_attempt() returns a fully populated AttemptLineageView. This is
the R2 acceptance test for lineage coverage.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from optimizer.improvement_lineage import (
    EVENT_ATTEMPT,
    EVENT_DEPLOYMENT,
    EVENT_EVAL_RUN,
    EVENT_MEASUREMENT,
    ImprovementLineageStore,
)


ATTEMPT_ID = "e2echain"  # 8 chars, matches the R1 invariant


@pytest.fixture
def lineage_db(tmp_path, monkeypatch):
    db_path = tmp_path / "lineage.db"
    monkeypatch.setenv("AGENTLAB_IMPROVEMENT_LINEAGE_DB", str(db_path))
    return db_path


# --- Stage 1: eval emission ------------------------------------------------

def _emit_real_eval_run(eval_run_id: str, composite: float) -> None:
    """Call EvalRunner's real helper the same way _persist_history does."""
    from evals.runner import EvalRunner
    from evals.scorer import CompositeScore

    score = CompositeScore(
        composite=composite,
        quality=composite,
        safety=1.0,
        latency=0.9,
        cost=0.9,
        results=[],
    )
    score.run_id = eval_run_id
    EvalRunner._emit_eval_run_lineage(
        run_id=eval_run_id,
        score=score,
        dataset_path="configs/foo.yaml",
    )


# --- Stage 2: optimizer emission -------------------------------------------

def _emit_real_optimizer_events(
    lineage_store: ImprovementLineageStore,
    attempt_id: str,
    eval_run_id: str,
) -> None:
    """Call Optimizer._emit_attempt_lineage the same way run() does."""
    from optimizer.loop import Optimizer

    opt = Optimizer(eval_runner=MagicMock(), lineage_store=lineage_store)
    opt._emit_attempt_lineage(
        attempt_id=attempt_id,
        status="accepted",
        score_before=0.80,
        score_after=0.85,
        eval_run_id=eval_run_id,
    )


# --- Stage 3: deployer emission --------------------------------------------

def _emit_real_deploy_event(attempt_id: str, version: int) -> None:
    """Call the real _emit_deploy_lineage helper from runner.py."""
    from runner import _emit_deploy_lineage

    _emit_deploy_lineage(
        attempt_id=attempt_id,
        deployment_id=f"promote-v{version:03d}",
        version=version,
        strategy="immediate",
    )


# --- Stage 4: measurement (written directly -- improve measure comes in B.3) -

def _emit_measurement(
    lineage_store: ImprovementLineageStore,
    attempt_id: str,
    composite_delta: float,
) -> None:
    lineage_store.record_measurement(
        attempt_id=attempt_id,
        measurement_id="meas-1",
        composite_delta=composite_delta,
        eval_run_id="post-deploy-run",
    )


# --- The E2E test ----------------------------------------------------------

def test_full_lineage_chain_for_single_attempt(lineage_db):
    """eval_run -> attempt -> deployment -> measurement, all keyed on one attempt_id."""
    store = ImprovementLineageStore(db_path=str(lineage_db))

    # 1. Eval emits its own run event (no attempt_id yet -- eval runs before optimizer).
    _emit_real_eval_run(eval_run_id="run-e2e-1", composite=0.80)

    # 2. Optimizer processes that eval, produces an attempt, links by eval_run_id.
    _emit_real_optimizer_events(store, attempt_id=ATTEMPT_ID, eval_run_id="run-e2e-1")

    # 3. User accepts -> deploy emits a deployment event with the attempt_id.
    _emit_real_deploy_event(attempt_id=ATTEMPT_ID, version=7)

    # 4. After deploy, improve measure writes the composite_delta.
    _emit_measurement(store, attempt_id=ATTEMPT_ID, composite_delta=0.05)

    # The whole chain is queryable in one call:
    view = store.view_attempt(ATTEMPT_ID)
    assert view.attempt_id == ATTEMPT_ID
    assert view.eval_run_id == "run-e2e-1"
    assert view.status == "accepted"
    assert view.score_before == 0.80
    assert view.score_after == 0.85
    assert view.deployment_id == "promote-v007"
    assert view.deployed_version == 7
    assert view.measurement_id == "meas-1"
    assert view.composite_delta == 0.05

    # The events list contains attempt, deployment, measurement in chronological order.
    # eval_run is written with attempt_id="" (no attempt yet), so it does NOT
    # show up in view_attempt(ATTEMPT_ID) which filters on attempt_id.
    types_in_order = [e.event_type for e in view.events]
    assert EVENT_ATTEMPT in types_in_order
    assert EVENT_DEPLOYMENT in types_in_order
    assert EVENT_MEASUREMENT in types_in_order
    # attempt comes before deployment, deployment before measurement.
    assert types_in_order.index(EVENT_ATTEMPT) < types_in_order.index(EVENT_DEPLOYMENT)
    assert types_in_order.index(EVENT_DEPLOYMENT) < types_in_order.index(EVENT_MEASUREMENT)


def test_eval_run_event_is_queryable_independently(lineage_db):
    """The eval_run event is keyed by attempt_id='' (no attempt exists yet);
    callers can still find it via recent()."""
    store = ImprovementLineageStore(db_path=str(lineage_db))
    _emit_real_eval_run(eval_run_id="run-indep-1", composite=0.75)
    eval_events = [e for e in store.recent(100) if e.event_type == EVENT_EVAL_RUN]
    assert len(eval_events) == 1
    assert eval_events[0].payload["eval_run_id"] == "run-indep-1"
    assert eval_events[0].attempt_id == ""


def test_rejected_attempt_lineage_surfaces_reason(lineage_db):
    """A rejected attempt's rejection event is visible via view_attempt."""
    from optimizer.gates import RejectionReason
    from optimizer.loop import Optimizer

    store = ImprovementLineageStore(db_path=str(lineage_db))
    opt = Optimizer(eval_runner=MagicMock(), lineage_store=store)
    opt._emit_attempt_lineage(
        attempt_id="rejected1",
        status="rejected_regression",
        score_before=0.80,
        score_after=0.75,
    )
    opt._emit_rejection_lineage(
        attempt_id="rejected1",
        reason=RejectionReason.REGRESSION_DETECTED,
        detail="composite dropped 0.05",
    )
    view = store.view_attempt("rejected1")
    assert view.status == "rejected_regression"
    assert view.rejection_reason == RejectionReason.REGRESSION_DETECTED.value
    assert view.rejection_detail == "composite dropped 0.05"
    assert view.deployment_id is None  # rejected, never deployed
