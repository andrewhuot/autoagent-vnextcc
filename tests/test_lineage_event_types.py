"""Typed event-recorder façades on ImprovementLineageStore."""
from __future__ import annotations

import pytest

from optimizer.improvement_lineage import (
    EVENT_ATTEMPT,
    EVENT_DEPLOYMENT,
    EVENT_EVAL_RUN,
    EVENT_MEASUREMENT,
    EVENT_REJECTION,
    ImprovementLineageStore,
)


@pytest.fixture
def store(tmp_path):
    return ImprovementLineageStore(db_path=str(tmp_path / "lineage.db"))


def test_record_eval_run_roundtrip(store):
    ev = store.record_eval_run(
        eval_run_id="run-123",
        attempt_id="a1b2c3d4",
        config_path="configs/foo.yaml",
        composite_score=0.82,
        case_count=55,
    )
    assert ev.event_type == EVENT_EVAL_RUN
    assert ev.attempt_id == "a1b2c3d4"
    assert ev.payload["eval_run_id"] == "run-123"
    assert ev.payload["config_path"] == "configs/foo.yaml"
    assert ev.payload["composite_score"] == 0.82
    assert ev.payload["case_count"] == 55
    reloaded = store.events_for("a1b2c3d4")
    assert len(reloaded) == 1
    assert reloaded[0].event_type == EVENT_EVAL_RUN


def test_record_eval_run_allows_empty_attempt_id(store):
    """Eval runs may be emitted before an attempt_id exists (standalone eval)."""
    ev = store.record_eval_run(
        eval_run_id="run-999",
        attempt_id="",
        composite_score=0.7,
    )
    assert ev.event_type == EVENT_EVAL_RUN
    assert ev.payload["eval_run_id"] == "run-999"


def test_record_attempt_roundtrip(store):
    ev = store.record_attempt(
        attempt_id="a1b2c3d4",
        status="accepted",
        score_before=0.80,
        score_after=0.85,
        eval_run_id="run-123",
        parent_attempt_id="prev0000",
    )
    assert ev.event_type == EVENT_ATTEMPT
    assert ev.attempt_id == "a1b2c3d4"
    assert ev.payload["status"] == "accepted"
    assert ev.payload["score_before"] == 0.80
    assert ev.payload["score_after"] == 0.85
    assert ev.payload["eval_run_id"] == "run-123"
    assert ev.payload["parent_attempt_id"] == "prev0000"


def test_record_rejection_roundtrip(store):
    ev = store.record_rejection(
        attempt_id="a1b2c3d4",
        reason="regression_detected",
        detail="composite dropped 0.05",
    )
    assert ev.event_type == EVENT_REJECTION
    assert ev.payload["reason"] == "regression_detected"
    assert ev.payload["detail"] == "composite dropped 0.05"


def test_record_deployment_roundtrip(store):
    ev = store.record_deployment(
        attempt_id="a1b2c3d4",
        deployment_id="dep-7",
        version=7,
    )
    assert ev.event_type == EVENT_DEPLOYMENT
    assert ev.version == 7
    assert ev.payload["deployment_id"] == "dep-7"


def test_record_measurement_roundtrip(store):
    ev = store.record_measurement(
        attempt_id="a1b2c3d4",
        measurement_id="m-1",
        composite_delta=0.03,
        eval_run_id="run-456",
    )
    assert ev.event_type == EVENT_MEASUREMENT
    assert ev.payload["measurement_id"] == "m-1"
    assert ev.payload["composite_delta"] == 0.03
    assert ev.payload["eval_run_id"] == "run-456"


def test_existing_record_api_still_works(store):
    """The underlying record() method and existing event types are untouched."""
    ev = store.record("a1", "promote", version=5, payload={"deployment_id": "d1"})
    assert ev.event_type == "promote"
    assert ev.version == 5
    events = store.events_for("a1")
    assert len(events) == 1


def test_facades_accept_extra_payload_kwargs(store):
    """Each façade forwards **extra kwargs into the payload so callers can
    attach arbitrary context without a schema change."""
    ev = store.record_eval_run(
        eval_run_id="r1",
        attempt_id="a1",
        composite_score=0.5,
        tenant="acme",
        trace_id="tr-1",
    )
    assert ev.payload["tenant"] == "acme"
    assert ev.payload["trace_id"] == "tr-1"
