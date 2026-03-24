"""Unit tests for extended statistics — clustered bootstrap, sequential test, corrections."""

from __future__ import annotations

from evals.statistics import (
    check_sample_sizes,
    clustered_bootstrap,
    judge_variance_estimate,
    multiple_hypothesis_correction,
    sequential_test,
)


def test_clustered_bootstrap_detects_improvement() -> None:
    """Clear improvement across clusters should yield is_significant=True."""
    # Candidate consistently better by ~0.2
    baseline = [0.5, 0.5, 0.5, 0.6, 0.6, 0.6, 0.4, 0.4, 0.4, 0.5, 0.5, 0.5]
    candidate = [0.7, 0.7, 0.7, 0.8, 0.8, 0.8, 0.6, 0.6, 0.6, 0.7, 0.7, 0.7]
    clusters = ["a", "a", "a", "b", "b", "b", "c", "c", "c", "d", "d", "d"]

    result = clustered_bootstrap(
        baseline, candidate, clusters, alpha=0.05, iterations=2000, seed=42,
    )

    assert result.is_significant is True
    assert result.observed_delta > 0.1
    assert result.p_value < 0.05
    assert result.n_clusters == 4
    assert result.n_observations == 12
    assert result.confidence_interval[0] > 0  # CI should exclude zero


def test_clustered_bootstrap_rejects_noise() -> None:
    """No real difference (just noise) should yield is_significant=False."""
    baseline =  [0.50, 0.51, 0.49, 0.50, 0.52, 0.48, 0.50, 0.51, 0.49, 0.50]
    candidate = [0.51, 0.50, 0.50, 0.49, 0.51, 0.49, 0.51, 0.50, 0.50, 0.49]
    clusters =  ["a", "a", "b", "b", "c", "c", "d", "d", "e", "e"]

    result = clustered_bootstrap(
        baseline, candidate, clusters, alpha=0.05, iterations=2000, seed=42,
    )

    assert result.is_significant is False
    assert result.p_value >= 0.05


def test_sequential_test_early_stop() -> None:
    """Strong signal should trigger should_stop=True before max_looks."""
    # Very large positive deltas — need z = mean * sqrt(n) to exceed boundary.
    # At 8 looks out of 10, alpha_spent = 0.05 * (0.8)^2 = 0.032,
    # boundary ~ 2.14, z = mean * sqrt(8). Use mean~1.0 => z ~2.83 > 2.14.
    deltas = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]

    result = sequential_test(deltas, alpha=0.05, max_looks=10)

    assert result.should_stop is True
    assert result.reject_null is True
    assert result.n_looks == 8
    assert result.current_z > 0


def test_sequential_test_continues_weak_signal() -> None:
    """Weak signal should not trigger early stop."""
    # Tiny deltas — not enough evidence
    deltas = [0.001, 0.002]

    result = sequential_test(deltas, alpha=0.05, max_looks=10)

    assert result.should_stop is False
    assert result.reject_null is False
    assert result.n_looks == 2


def test_multiple_hypothesis_correction_holm() -> None:
    """Holm-Bonferroni should adjust p-values upward and reject fewer hypotheses."""
    p_values = [0.01, 0.03, 0.04, 0.80]

    corrected = multiple_hypothesis_correction(p_values, alpha=0.05)

    assert len(corrected) == 4
    # Each tuple is (original_index, adjusted_p, is_significant)
    # Verify original order preserved
    indices = [c[0] for c in corrected]
    assert indices == [0, 1, 2, 3]

    # Adjusted p-values should be >= original
    for orig_idx, adj_p, _ in corrected:
        assert adj_p >= p_values[orig_idx]

    # The large p-value (0.80) should definitely not be significant
    assert corrected[3][2] is False

    # The smallest (0.01) adjusted = 0.01 * 4 = 0.04, should be significant
    assert corrected[0][2] is True


def test_check_sample_sizes() -> None:
    """Metrics with fewer samples than min_per_metric should be flagged insufficient."""
    metric_values = {
        "quality": [0.8] * 50,       # sufficient
        "latency": [100.0] * 10,     # insufficient
        "cost": [0.5] * 30,          # exactly at threshold
    }

    results = check_sample_sizes(metric_values, min_per_metric=30)

    assert len(results) == 3
    # Sorted by metric name
    assert results[0].metric_name == "cost"
    assert results[0].is_sufficient is True

    assert results[1].metric_name == "latency"
    assert results[1].is_sufficient is False
    assert results[1].current_samples == 10

    assert results[2].metric_name == "quality"
    assert results[2].is_sufficient is True


def test_judge_variance_estimate() -> None:
    """Bootstrap variance estimate should be positive for varied scores."""
    scores = [0.3, 0.5, 0.7, 0.9, 0.4, 0.6, 0.8, 0.2, 0.5, 0.7]

    variance = judge_variance_estimate(scores, n_resample=200, seed=42)

    assert variance > 0.0
    # For these varied scores, std of bootstrap means should be moderate
    assert variance < 0.5  # sanity upper bound

    # Empty scores should return 0
    assert judge_variance_estimate([]) == 0.0
