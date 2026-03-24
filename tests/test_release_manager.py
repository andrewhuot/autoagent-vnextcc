"""Tests for release manager promotion pipeline."""

from __future__ import annotations

import pytest

from deployer.canary import CanaryManager
from deployer.release_manager import PromotionStage, ReleaseManager
from deployer.versioning import ConfigVersionManager


# ---------------------------------------------------------------------------
# ReleaseManager tests
# ---------------------------------------------------------------------------


@pytest.fixture
def version_manager():
    return ConfigVersionManager()


@pytest.fixture
def release_manager(version_manager):
    return ReleaseManager(version_manager=version_manager)


def test_release_manager_start_promotion(release_manager):
    record = release_manager.start_promotion("v123")

    assert record.candidate_version == "v123"
    assert record.current_stage == PromotionStage.gate_check
    assert record.status == "in_progress"
    assert len(record.stages_completed) == 0


def test_release_manager_check_gates_pass(release_manager):
    record = release_manager.start_promotion("v123")
    gates = {
        "safety_compliance": True,
        "p0_regressions": True,
        "state_integrity": True,
    }

    passed = release_manager.check_gates(record, gates)

    assert passed is True
    assert PromotionStage.gate_check in record.stages_completed
    assert record.current_stage == PromotionStage.holdout_eval
    assert record.status == "in_progress"


def test_release_manager_check_gates_fail(release_manager):
    record = release_manager.start_promotion("v123")
    gates = {
        "safety_compliance": True,
        "p0_regressions": False,  # failed
    }

    passed = release_manager.check_gates(record, gates)

    assert passed is False
    assert record.status == "failed"
    assert "p0_regressions" in record.failure_reason
    assert record.completed_at is not None


def test_release_manager_check_holdout_pass(release_manager):
    record = release_manager.start_promotion("v123")
    record.current_stage = PromotionStage.holdout_eval

    passed = release_manager.check_holdout(record, holdout_score=0.05)

    assert passed is True
    assert PromotionStage.holdout_eval in record.stages_completed
    assert record.current_stage == PromotionStage.slice_check


def test_release_manager_check_holdout_fail(release_manager):
    record = release_manager.start_promotion("v123")
    record.current_stage = PromotionStage.holdout_eval

    passed = release_manager.check_holdout(
        record, holdout_score=-0.05, threshold=0.0
    )

    assert passed is False
    assert record.status == "failed"
    assert "Holdout regression" in record.failure_reason


def test_release_manager_check_slices_pass(release_manager):
    record = release_manager.start_promotion("v123")
    record.current_stage = PromotionStage.slice_check
    slice_results = {
        "category_billing": 0.02,
        "category_support": 0.01,
        "category_sales": -0.03,  # slight regression, within threshold
    }

    passed = release_manager.check_slices(
        record, slice_results, regression_threshold=-0.05
    )

    assert passed is True
    assert PromotionStage.slice_check in record.stages_completed


def test_release_manager_check_slices_fail(release_manager):
    record = release_manager.start_promotion("v123")
    record.current_stage = PromotionStage.slice_check
    slice_results = {
        "category_billing": 0.02,
        "category_support": -0.10,  # severe regression
    }

    passed = release_manager.check_slices(
        record, slice_results, regression_threshold=-0.05
    )

    assert passed is False
    assert record.status == "failed"
    assert "category_support" in record.failure_reason


def test_release_manager_run_full_pipeline_success(release_manager):
    record = release_manager.run_full_pipeline(
        candidate_version="v123",
        gate_results={"safety": True, "p0": True},
        holdout_score=0.05,
        slice_results={"slice1": 0.02, "slice2": 0.01},
        canary_verdict="promote",
    )

    assert record.status == "released"
    assert PromotionStage.released in record.stages_completed
    assert record.completed_at is not None


def test_release_manager_run_full_pipeline_failure_at_gates(release_manager):
    record = release_manager.run_full_pipeline(
        candidate_version="v123",
        gate_results={"safety": False},
        holdout_score=0.05,
        slice_results={"slice1": 0.02},
    )

    assert record.status == "failed"
    assert len(record.stages_completed) == 0
    assert "Gates failed" in record.failure_reason


def test_release_manager_run_full_pipeline_failure_at_holdout(release_manager):
    record = release_manager.run_full_pipeline(
        candidate_version="v123",
        gate_results={"safety": True, "p0": True},
        holdout_score=-0.1,  # regression
        slice_results={"slice1": 0.02},
    )

    assert record.status == "failed"
    assert PromotionStage.gate_check in record.stages_completed
    assert PromotionStage.holdout_eval not in record.stages_completed
    assert "Holdout regression" in record.failure_reason


def test_release_manager_run_full_pipeline_failure_at_slices(release_manager):
    record = release_manager.run_full_pipeline(
        candidate_version="v123",
        gate_results={"safety": True},
        holdout_score=0.05,
        slice_results={"slice1": -0.10},  # severe regression
    )

    assert record.status == "failed"
    assert PromotionStage.slice_check not in record.stages_completed
    assert "Slice regressions" in record.failure_reason
