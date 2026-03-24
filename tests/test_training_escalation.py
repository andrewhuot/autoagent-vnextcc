"""Tests for training escalation monitor."""

from __future__ import annotations

import pytest

from optimizer.training_escalation import (
    FailureFamilyStability,
    TrainingEscalationMonitor,
    TrainingMethod,
)


# ---------------------------------------------------------------------------
# FailureFamilyStability tests
# ---------------------------------------------------------------------------


def test_failure_family_stability_is_stable_true():
    family = FailureFamilyStability(
        failure_family="tool_error",
        cycle_count=5,
        volume=20,
    )

    assert family.is_stable is True


def test_failure_family_stability_is_stable_false_low_cycles():
    family = FailureFamilyStability(
        failure_family="tool_error",
        cycle_count=3,
        volume=25,
    )

    assert family.is_stable is False


def test_failure_family_stability_is_stable_false_low_volume():
    family = FailureFamilyStability(
        failure_family="tool_error",
        cycle_count=6,
        volume=15,
    )

    assert family.is_stable is False


def test_failure_family_stability_prompt_fix_rate():
    family = FailureFamilyStability(
        failure_family="tool_error",
        prompt_fix_attempts=10,
        prompt_fix_successes=3,
    )

    assert family.prompt_fix_rate == 0.3


def test_failure_family_stability_prompt_fix_rate_zero_attempts():
    family = FailureFamilyStability(failure_family="tool_error")

    assert family.prompt_fix_rate == 0.0


# ---------------------------------------------------------------------------
# TrainingEscalationMonitor tests
# ---------------------------------------------------------------------------


def test_training_escalation_monitor_record_cycle():
    monitor = TrainingEscalationMonitor()

    monitor.record_cycle(
        failure_family="tool_error",
        volume=10,
        prompt_fix_attempted=True,
        prompt_fix_succeeded=False,
    )

    assert "tool_error" in monitor.families
    entry = monitor.families["tool_error"]
    assert entry.cycle_count == 1
    assert entry.volume == 10
    assert entry.prompt_fix_attempts == 1
    assert entry.prompt_fix_successes == 0


def test_training_escalation_monitor_record_multiple_cycles():
    monitor = TrainingEscalationMonitor()

    for i in range(6):
        monitor.record_cycle(
            failure_family="tool_error",
            volume=5,
            prompt_fix_attempted=True,
            prompt_fix_succeeded=(i % 3 == 0),  # 2 successes out of 6
        )

    entry = monitor.families["tool_error"]
    assert entry.cycle_count == 6
    assert entry.volume == 30
    assert entry.prompt_fix_attempts == 6
    assert entry.prompt_fix_successes == 2


def test_training_escalation_monitor_check_escalation_not_stable():
    monitor = TrainingEscalationMonitor()

    # Only 3 cycles, need 5 for stability
    for i in range(3):
        monitor.record_cycle(
            failure_family="tool_error",
            volume=10,
            prompt_fix_attempted=True,
            prompt_fix_succeeded=False,
        )

    rec = monitor.check_escalation("tool_error")

    assert rec is None


def test_training_escalation_monitor_check_escalation_high_fix_rate():
    monitor = TrainingEscalationMonitor()

    # High fix rate (>0.5) should not escalate
    for i in range(6):
        monitor.record_cycle(
            failure_family="tool_error",
            volume=5,
            prompt_fix_attempted=True,
            prompt_fix_succeeded=True,  # all succeed
        )

    rec = monitor.check_escalation("tool_error")

    assert rec is None


def test_training_escalation_monitor_check_escalation_recommends_sft():
    monitor = TrainingEscalationMonitor()

    # Very low fix rate (<0.1) -> SFT
    for i in range(12):
        monitor.record_cycle(
            failure_family="tool_error",
            volume=5,
            prompt_fix_attempted=True,
            prompt_fix_succeeded=(i == 0),  # 1 success out of 12
        )

    rec = monitor.check_escalation("tool_error")

    assert rec is not None
    assert rec.recommended_method == TrainingMethod.SFT
    assert rec.confidence == 0.8
    assert rec.dataset_size == 60  # 12 cycles * 5 volume


def test_training_escalation_monitor_check_escalation_recommends_dpo():
    monitor = TrainingEscalationMonitor()

    # Fix rate 0.1-0.3 -> DPO
    for i in range(10):
        monitor.record_cycle(
            failure_family="routing_failure",
            volume=5,
            prompt_fix_attempted=True,
            prompt_fix_succeeded=(i < 2),  # 2 successes out of 10 = 0.2
        )

    rec = monitor.check_escalation("routing_failure")

    assert rec is not None
    assert rec.recommended_method == TrainingMethod.DPO
    assert rec.confidence == 0.7


def test_training_escalation_monitor_check_escalation_recommends_rft():
    monitor = TrainingEscalationMonitor()

    # Fix rate 0.3-0.5 -> RFT
    for i in range(10):
        monitor.record_cycle(
            failure_family="quality_degradation",
            volume=5,
            prompt_fix_attempted=True,
            prompt_fix_succeeded=(i < 4),  # 4 successes out of 10 = 0.4
        )

    rec = monitor.check_escalation("quality_degradation")

    assert rec is not None
    assert rec.recommended_method == TrainingMethod.RFT
    assert rec.confidence == 0.6


def test_training_escalation_monitor_get_all_recommendations():
    monitor = TrainingEscalationMonitor()

    # Family 1: should escalate to SFT
    for i in range(10):
        monitor.record_cycle(
            failure_family="tool_error",
            volume=5,
            prompt_fix_attempted=True,
            prompt_fix_succeeded=False,
        )

    # Family 2: should escalate to DPO
    for i in range(10):
        monitor.record_cycle(
            failure_family="routing_failure",
            volume=5,
            prompt_fix_attempted=True,
            prompt_fix_succeeded=(i < 2),
        )

    # Family 3: high fix rate, no escalation
    for i in range(6):
        monitor.record_cycle(
            failure_family="latency_spike",
            volume=5,
            prompt_fix_attempted=True,
            prompt_fix_succeeded=True,
        )

    recs = monitor.get_all_recommendations()

    assert len(recs) == 2  # only 2 should escalate
    families = {r.failure_family for r in recs}
    assert "tool_error" in families
    assert "routing_failure" in families
    assert "latency_spike" not in families
