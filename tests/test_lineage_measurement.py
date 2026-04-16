"""R2.5 gate: measurement events round-trip through view_attempt.

Narrow acceptance test for the post-deploy measurement path. Exercises
the happy path (deployment → measurement → view surfaces composite_delta)
plus the common edge cases improve measure will need to handle.
"""
from __future__ import annotations

import pytest

from optimizer.improvement_lineage import (
    EVENT_MEASUREMENT,
    ImprovementLineageStore,
)


@pytest.fixture
def store(tmp_path):
    return ImprovementLineageStore(db_path=str(tmp_path / "lineage.db"))


def test_measurement_roundtrips_through_view(store):
    aid = "m0000001"
    store.record_deployment(attempt_id=aid, deployment_id="d1", version=3)
    store.record_measurement(
        attempt_id=aid,
        measurement_id="meas-1",
        composite_delta=0.02,
        eval_run_id="r2",
    )
    view = store.view_attempt(aid)
    assert view.deployment_id == "d1"
    assert view.deployed_version == 3
    assert view.measurement_id == "meas-1"
    assert view.composite_delta == 0.02


def test_multiple_measurements_surface_latest(store):
    """Re-measuring after a deploy overwrites composite_delta in the view.

    The underlying event stream keeps every write; view_attempt()
    intentionally surfaces the most recent measurement so
    `agentlab improve lineage` reflects the current state.
    """
    aid = "m0000002"
    store.record_deployment(attempt_id=aid, deployment_id="d1", version=1)
    store.record_measurement(
        attempt_id=aid, measurement_id="meas-a", composite_delta=0.01
    )
    store.record_measurement(
        attempt_id=aid, measurement_id="meas-b", composite_delta=0.04
    )
    view = store.view_attempt(aid)
    assert view.measurement_id == "meas-b"
    assert view.composite_delta == 0.04
    measurement_events = [
        e for e in view.events if e.event_type == EVENT_MEASUREMENT
    ]
    assert len(measurement_events) == 2


def test_measurement_without_deployment_still_recorded(store):
    """Lineage is append-only; we don't enforce ordering in the store.
    The `improve measure` CLI does the ordering check — the store itself
    must accept any write so backfill/replay can insert in any order."""
    aid = "m0000003"
    store.record_measurement(
        attempt_id=aid, measurement_id="orphan", composite_delta=0.0
    )
    view = store.view_attempt(aid)
    assert view.measurement_id == "orphan"
    assert view.composite_delta == 0.0
    assert view.deployment_id is None


def test_measurement_composite_delta_none_is_preserved(store):
    """Some cases record the measurement metadata before the delta is known."""
    aid = "m0000004"
    store.record_measurement(
        attempt_id=aid,
        measurement_id="pending",
        composite_delta=None,
        eval_run_id="r5",
    )
    view = store.view_attempt(aid)
    assert view.measurement_id == "pending"
    assert view.composite_delta is None
