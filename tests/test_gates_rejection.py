"""Tests for structured rejection types in optimizer.gates (R1.6)."""

from __future__ import annotations

import pytest

from optimizer.gates import (
    RejectionReason,
    RejectionRecord,
    rejection_from_status,
)


def test_rejection_reason_values_are_stable() -> None:
    """Enum string values must remain stable for SQLite/JSON serialization."""
    assert RejectionReason.SAFETY_VIOLATION.value == "safety_violation"
    assert RejectionReason.REGRESSION_DETECTED.value == "regression_detected"
    assert RejectionReason.NO_SIGNIFICANT_IMPROVEMENT.value == "no_significant_improvement"
    assert RejectionReason.GATE_FAILED.value == "gate_failed"
    assert RejectionReason.COVERAGE_INSUFFICIENT.value == "coverage_insufficient"


def test_rejection_record_to_dict_round_trip() -> None:
    record = RejectionRecord(
        attempt_id="att-1",
        reason=RejectionReason.REGRESSION_DETECTED,
        detail="quality dropped",
        baseline_score=0.8,
        candidate_score=0.6,
        metadata={"metric": "quality"},
    )
    d = record.to_dict()
    assert d["attempt_id"] == "att-1"
    assert d["reason"] == "regression_detected"
    assert d["detail"] == "quality dropped"
    assert d["baseline_score"] == 0.8
    assert d["candidate_score"] == 0.6
    assert d["metadata"] == {"metric": "quality"}


def test_rejection_record_defaults() -> None:
    record = RejectionRecord(
        attempt_id="att-2",
        reason=RejectionReason.GATE_FAILED,
        detail="something went wrong",
    )
    assert record.baseline_score is None
    assert record.candidate_score is None
    assert record.metadata == {}


def test_rejection_from_status_constraints() -> None:
    assert rejection_from_status("rejected_constraints") == RejectionReason.SAFETY_VIOLATION


def test_rejection_from_status_regression() -> None:
    assert rejection_from_status("rejected_regression") == RejectionReason.REGRESSION_DETECTED


def test_rejection_from_status_no_improvement() -> None:
    assert (
        rejection_from_status("rejected_no_improvement")
        == RejectionReason.NO_SIGNIFICANT_IMPROVEMENT
    )


def test_rejection_from_status_unknown_rejected() -> None:
    assert rejection_from_status("rejected_something_new") == RejectionReason.GATE_FAILED


def test_rejection_from_status_accepted_raises() -> None:
    with pytest.raises(ValueError):
        rejection_from_status("accepted")


def test_rejection_from_status_empty_raises() -> None:
    with pytest.raises(ValueError):
        rejection_from_status("")
