"""Tests for rejection tracking in the optimization loop."""
from __future__ import annotations

from collections import deque
from unittest.mock import MagicMock

import pytest

from optimizer.gates import RejectionReason, RejectionRecord
from optimizer.loop import Optimizer


def _make_optimizer() -> Optimizer:
    """Build a minimally-stubbed Optimizer for buffer tests."""
    opt = Optimizer.__new__(Optimizer)  # bypass __init__ for unit isolation
    opt._recent_rejections = deque(maxlen=200)
    opt._current_cycle_skills = []
    opt.memory = MagicMock()
    opt.event_log = None
    return opt


def test_recent_rejections_returns_empty_initially():
    opt = _make_optimizer()
    assert opt.recent_rejections() == []


def test_log_rejected_attempt_appends_to_ring_buffer():
    opt = _make_optimizer()
    health_report = MagicMock()
    health_report.metrics.to_dict.return_value = {}
    opt._log_rejected_attempt(
        health_report=health_report,
        change_description="test change",
        config_section="prompt",
        rejection_status="rejected_constraints",
        rejection_reason="Safety violated",
    )
    rejections = opt.recent_rejections()
    assert len(rejections) == 1
    assert rejections[0].reason == RejectionReason.SAFETY_VIOLATION
    assert rejections[0].detail == "Safety violated"
    assert rejections[0].attempt_id  # non-empty


def test_log_rejected_attempt_attempt_id_matches_logged_attempt():
    """The RejectionRecord.attempt_id MUST match the OptimizationAttempt persisted to memory."""
    opt = _make_optimizer()
    health_report = MagicMock()
    health_report.metrics.to_dict.return_value = {}
    opt._log_rejected_attempt(
        health_report=health_report,
        change_description="x",
        config_section="prompt",
        rejection_status="rejected_noop",
        rejection_reason="No-op proposal",
    )
    assert opt.memory.log.call_count == 1
    persisted_attempt = opt.memory.log.call_args[0][0]
    record = opt.recent_rejections()[0]
    assert record.attempt_id == persisted_attempt.attempt_id


def test_recent_rejections_returns_newest_first():
    opt = _make_optimizer()
    health_report = MagicMock()
    health_report.metrics.to_dict.return_value = {}
    for status in ["rejected_noop", "rejected_constraints", "rejected_regression"]:
        opt._log_rejected_attempt(
            health_report=health_report,
            change_description=status,
            config_section="prompt",
            rejection_status=status,
            rejection_reason=f"reason {status}",
        )
    rejections = opt.recent_rejections()
    assert len(rejections) == 3
    assert rejections[0].reason == RejectionReason.REGRESSION_DETECTED  # newest
    assert rejections[2].reason == RejectionReason.GATE_FAILED  # oldest (rejected_noop -> GATE_FAILED)


def test_recent_rejections_limit_respected():
    opt = _make_optimizer()
    health_report = MagicMock()
    health_report.metrics.to_dict.return_value = {}
    for i in range(5):
        opt._log_rejected_attempt(
            health_report=health_report,
            change_description=f"r{i}",
            config_section="prompt",
            rejection_status="rejected_noop",
            rejection_reason=f"reason {i}",
        )
    assert len(opt.recent_rejections(limit=2)) == 2
    assert len(opt.recent_rejections(limit=10)) == 5
    assert len(opt.recent_rejections()) == 5


def test_ring_buffer_caps_at_200():
    opt = _make_optimizer()
    health_report = MagicMock()
    health_report.metrics.to_dict.return_value = {}
    for i in range(250):
        opt._log_rejected_attempt(
            health_report=health_report,
            change_description=f"r{i}",
            config_section="prompt",
            rejection_status="rejected_noop",
            rejection_reason=f"reason {i}",
        )
    assert len(opt.recent_rejections()) == 200


def test_unknown_rejected_status_maps_to_gate_failed():
    opt = _make_optimizer()
    health_report = MagicMock()
    health_report.metrics.to_dict.return_value = {}
    opt._log_rejected_attempt(
        health_report=health_report,
        change_description="x",
        config_section="prompt",
        rejection_status="rejected_brand_new_reason",
        rejection_reason="Some new gate",
    )
    assert opt.recent_rejections()[0].reason == RejectionReason.GATE_FAILED
