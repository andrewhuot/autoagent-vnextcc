"""Optimizer emits attempt + rejection lineage events."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from optimizer.gates import RejectionReason
from optimizer.improvement_lineage import (
    EVENT_ATTEMPT,
    EVENT_REJECTION,
    ImprovementLineageStore,
)
from optimizer.loop import Optimizer


@pytest.fixture
def lineage_store(tmp_path):
    return ImprovementLineageStore(db_path=str(tmp_path / "lineage.db"))


def _make_optimizer(lineage_store=None):
    """Construct an Optimizer with mocks. Only the lineage_store wiring is
    exercised; the eval_runner is a MagicMock and never called.
    """
    return Optimizer(
        eval_runner=MagicMock(),
        lineage_store=lineage_store,
    )


def _health_report() -> MagicMock:
    health_report = MagicMock()
    health_report.metrics.to_dict.return_value = {}
    return health_report


def test_log_rejected_attempt_emits_attempt_and_rejection(lineage_store):
    opt = _make_optimizer(lineage_store=lineage_store)
    opt._log_rejected_attempt(
        change_description="tightened prompt",
        config_diff="- old\n+ new",
        rejection_status="rejected_regression",
        rejection_reason="composite dropped 0.05",
        config_section="prompt",
        health_report=_health_report(),
    )
    events = lineage_store.recent(100)
    attempt_events = [e for e in events if e.event_type == EVENT_ATTEMPT]
    rejection_events = [e for e in events if e.event_type == EVENT_REJECTION]
    assert len(attempt_events) == 1
    assert len(rejection_events) == 1
    # R1 invariant: same attempt_id on both events.
    assert attempt_events[0].attempt_id == rejection_events[0].attempt_id
    # And that attempt_id should equal the one on the persisted OptimizationAttempt.
    recent_attempts = opt.memory.recent(limit=1)
    assert len(recent_attempts) == 1
    assert recent_attempts[0].attempt_id == attempt_events[0].attempt_id


def test_log_rejected_attempt_noop_when_lineage_store_none():
    opt = _make_optimizer(lineage_store=None)
    # Must not raise:
    opt._log_rejected_attempt(
        change_description="x",
        config_diff="y",
        rejection_status="rejected_regression",
        rejection_reason="z",
        config_section="prompt",
        health_report=_health_report(),
    )
    # The OptimizationAttempt is still persisted even when lineage is off.
    assert len(opt.memory.recent(limit=1)) == 1


def test_log_rejected_attempt_lineage_failure_does_not_crash():
    """If the lineage store itself raises, optimizer keeps running."""
    broken = MagicMock()
    broken.record_attempt.side_effect = RuntimeError("db gone")
    broken.record_rejection.side_effect = RuntimeError("db gone")
    opt = _make_optimizer(lineage_store=broken)
    # Must not raise:
    opt._log_rejected_attempt(
        change_description="x",
        config_diff="y",
        rejection_status="rejected_regression",
        rejection_reason="z",
        config_section="prompt",
        health_report=_health_report(),
    )
    # OptimizationAttempt was still persisted to memory:
    assert len(opt.memory.recent(limit=1)) == 1


def test_record_attempt_uses_status_from_attempt(lineage_store):
    """The attempt event's payload.status reflects the OptimizationAttempt.status,
    and the rejection event carries the mapped RejectionReason.value.
    """
    opt = _make_optimizer(lineage_store=lineage_store)
    opt._log_rejected_attempt(
        change_description="x",
        config_diff="y",
        rejection_status="rejected_constraints",
        rejection_reason="unsafe",
        config_section="prompt",
        health_report=_health_report(),
    )
    events = lineage_store.recent(100)
    attempt_ev = next(e for e in events if e.event_type == EVENT_ATTEMPT)
    rejection_ev = next(e for e in events if e.event_type == EVENT_REJECTION)
    assert attempt_ev.payload["status"] == "rejected_constraints"
    # rejected_constraints -> SAFETY_VIOLATION per rejection_from_status().
    assert rejection_ev.payload["reason"] == RejectionReason.SAFETY_VIOLATION.value
    assert rejection_ev.payload["detail"] == "unsafe"
