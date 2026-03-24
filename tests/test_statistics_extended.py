"""Tests for extended statistical utilities."""

from __future__ import annotations

import pytest

from evals.statistics import (
    PowerAnalysis,
    PromotionDecision,
    SafetySeverityTier,
    check_promotion_criteria,
    compute_required_sample_size,
    safety_upper_bound,
)


# ---------------------------------------------------------------------------
# compute_required_sample_size tests
# ---------------------------------------------------------------------------


def test_compute_required_sample_size_small_effect():
    n = compute_required_sample_size(
        effect_size=0.01,
        alpha=0.05,
        power=0.8,
        baseline_variance=0.1,
    )

    # Small effect size requires larger sample
    assert n > 100


def test_compute_required_sample_size_large_effect():
    n = compute_required_sample_size(
        effect_size=0.1,
        alpha=0.05,
        power=0.8,
        baseline_variance=0.1,
    )

    # Large effect size requires smaller sample
    assert 10 < n < 100


def test_compute_required_sample_size_zero_effect():
    n = compute_required_sample_size(
        effect_size=0.0,
        alpha=0.05,
        power=0.8,
        baseline_variance=0.1,
    )

    # Zero effect size returns minimum (2)
    assert n == 2


# ---------------------------------------------------------------------------
# PowerAnalysis tests
# ---------------------------------------------------------------------------


def test_power_analysis_is_adequate_true():
    analysis = PowerAnalysis(
        required_n=30,
        current_n=50,
        power=0.8,
        effect_size=0.05,
        alpha=0.05,
    )

    assert analysis.is_adequate is True


def test_power_analysis_is_adequate_false():
    analysis = PowerAnalysis(
        required_n=100,
        current_n=50,
        power=0.8,
        effect_size=0.05,
        alpha=0.05,
    )

    assert analysis.is_adequate is False


# ---------------------------------------------------------------------------
# safety_upper_bound tests
# ---------------------------------------------------------------------------


def test_safety_upper_bound_zero_violations():
    upper = safety_upper_bound(
        violations=0,
        total=100,
        tier=SafetySeverityTier.P0,
        alpha=0.05,
    )

    # With 0 violations, upper bound should be small but > 0
    assert 0.0 < upper < 0.05


def test_safety_upper_bound_some_violations():
    upper = safety_upper_bound(
        violations=5,
        total=100,
        tier=SafetySeverityTier.P1,
        alpha=0.05,
    )

    # With 5% violation rate, upper bound should be > 0.05
    assert upper > 0.05
    assert upper < 0.15


def test_safety_upper_bound_many_violations():
    upper = safety_upper_bound(
        violations=20,
        total=100,
        tier=SafetySeverityTier.P2,
        alpha=0.05,
    )

    # 20% violation rate -> higher upper bound
    assert upper > 0.2


def test_safety_upper_bound_zero_total():
    upper = safety_upper_bound(
        violations=0,
        total=0,
        tier=SafetySeverityTier.P0,
    )

    # Zero total returns 1.0 (maximally conservative)
    assert upper == 1.0


# ---------------------------------------------------------------------------
# check_promotion_criteria tests
# ---------------------------------------------------------------------------


def test_check_promotion_criteria_all_pass():
    decision = check_promotion_criteria(
        p0_count=0,
        p1_rate_upper=0.01,
        p1_threshold=0.05,
        slice_regressions=[],
        holdout_winner=True,
        canary_survived=True,
    )

    assert decision.approved is True
    assert len(decision.stages_failed) == 0
    assert "p0_safety" in decision.stages_passed
    assert "p1_safety" in decision.stages_passed
    assert "slice_check" in decision.stages_passed
    assert "holdout_eval" in decision.stages_passed
    assert "canary" in decision.stages_passed


def test_check_promotion_criteria_fails_p0():
    decision = check_promotion_criteria(
        p0_count=1,  # one P0 violation
        p1_rate_upper=0.01,
        p1_threshold=0.05,
        slice_regressions=[],
        holdout_winner=True,
        canary_survived=True,
    )

    assert decision.approved is False
    assert "p0_safety" in decision.stages_failed
    assert decision.details["p0_count"] == 1


def test_check_promotion_criteria_fails_p1():
    decision = check_promotion_criteria(
        p0_count=0,
        p1_rate_upper=0.10,  # exceeds threshold
        p1_threshold=0.05,
        slice_regressions=[],
        holdout_winner=True,
        canary_survived=True,
    )

    assert decision.approved is False
    assert "p1_safety" in decision.stages_failed
    assert decision.details["p1_rate_upper"] == 0.10


def test_check_promotion_criteria_fails_slice_regression():
    decision = check_promotion_criteria(
        p0_count=0,
        p1_rate_upper=0.01,
        p1_threshold=0.05,
        slice_regressions=["category_billing", "category_support"],
        holdout_winner=True,
        canary_survived=True,
    )

    assert decision.approved is False
    assert "slice_check" in decision.stages_failed
    assert "category_billing" in decision.details["slice_regressions"]


def test_check_promotion_criteria_fails_holdout():
    decision = check_promotion_criteria(
        p0_count=0,
        p1_rate_upper=0.01,
        p1_threshold=0.05,
        slice_regressions=[],
        holdout_winner=False,
        canary_survived=True,
    )

    assert decision.approved is False
    assert "holdout_eval" in decision.stages_failed


def test_check_promotion_criteria_fails_canary():
    decision = check_promotion_criteria(
        p0_count=0,
        p1_rate_upper=0.01,
        p1_threshold=0.05,
        slice_regressions=[],
        holdout_winner=True,
        canary_survived=False,
    )

    assert decision.approved is False
    assert "canary" in decision.stages_failed


def test_check_promotion_criteria_multiple_failures():
    decision = check_promotion_criteria(
        p0_count=2,
        p1_rate_upper=0.10,
        p1_threshold=0.05,
        slice_regressions=["slice1"],
        holdout_winner=False,
        canary_survived=False,
    )

    assert decision.approved is False
    assert len(decision.stages_failed) == 5  # all stages failed
    assert len(decision.stages_passed) == 0
