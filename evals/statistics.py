"""Statistical significance utilities for optimization acceptance gating."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass


@dataclass
class SignificanceResult:
    """Result of paired significance testing."""

    observed_delta: float
    p_value: float
    is_significant: bool
    n_pairs: int
    alpha: float
    min_effect_size: float


def paired_significance(
    baseline_values: list[float],
    candidate_values: list[float],
    *,
    alpha: float = 0.05,
    min_effect_size: float = 0.005,
    iterations: int = 5000,
    seed: int = 7,
) -> SignificanceResult:
    """Run a paired sign-flip permutation test for candidate improvement.

    The null hypothesis is zero-mean paired difference. We estimate one-sided
    p-value P(diff >= observed | H0).
    """
    n_pairs = min(len(baseline_values), len(candidate_values))
    if n_pairs == 0:
        return SignificanceResult(
            observed_delta=0.0,
            p_value=1.0,
            is_significant=False,
            n_pairs=0,
            alpha=alpha,
            min_effect_size=min_effect_size,
        )

    baseline = baseline_values[:n_pairs]
    candidate = candidate_values[:n_pairs]
    diffs = [cand - base for base, cand in zip(baseline, candidate)]
    observed = sum(diffs) / n_pairs

    if observed < min_effect_size:
        return SignificanceResult(
            observed_delta=observed,
            p_value=1.0,
            is_significant=False,
            n_pairs=n_pairs,
            alpha=alpha,
            min_effect_size=min_effect_size,
        )

    rng = random.Random(seed)
    exceedances = 0
    rounds = max(100, int(iterations))

    for _ in range(rounds):
        signed = [delta if rng.random() >= 0.5 else -delta for delta in diffs]
        sample_mean = sum(signed) / n_pairs
        if sample_mean >= observed:
            exceedances += 1

    p_value = (exceedances + 1) / (rounds + 1)
    return SignificanceResult(
        observed_delta=observed,
        p_value=p_value,
        is_significant=p_value < alpha,
        n_pairs=n_pairs,
        alpha=alpha,
        min_effect_size=min_effect_size,
    )


# ---------------------------------------------------------------------------
# Extended statistical layer (Feature 8)
# ---------------------------------------------------------------------------


@dataclass
class ClusteredBootstrapResult:
    """Result of a clustered bootstrap significance test."""

    observed_delta: float
    p_value: float
    is_significant: bool
    confidence_interval: tuple[float, float]
    effect_size: float
    power_estimate: float
    n_clusters: int
    n_observations: int


def clustered_bootstrap(
    baseline_values: list[float],
    candidate_values: list[float],
    cluster_ids: list[str],
    *,
    alpha: float = 0.05,
    min_effect_size: float = 0.005,
    iterations: int = 2000,
    seed: int = 7,
) -> ClusteredBootstrapResult:
    """Clustered bootstrap test — resample whole clusters with replacement.

    Groups observations by *cluster_id*, then resamples clusters (not individual
    observations) to respect within-cluster correlation.
    """
    n = min(len(baseline_values), len(candidate_values), len(cluster_ids))
    if n == 0:
        return ClusteredBootstrapResult(
            observed_delta=0.0,
            p_value=1.0,
            is_significant=False,
            confidence_interval=(0.0, 0.0),
            effect_size=0.0,
            power_estimate=0.0,
            n_clusters=0,
            n_observations=0,
        )

    # Group by cluster
    clusters: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for i in range(n):
        clusters[cluster_ids[i]].append((baseline_values[i], candidate_values[i]))

    cluster_keys = list(clusters.keys())
    n_clusters = len(cluster_keys)

    # Observed delta
    diffs = [c - b for b, c in (pair for cid in cluster_keys for pair in clusters[cid])]
    observed_delta = sum(diffs) / len(diffs)

    # Pooled std for effect size
    pooled_std = (sum(d ** 2 for d in diffs) / len(diffs) - observed_delta ** 2) ** 0.5
    effect_size = observed_delta / pooled_std if pooled_std > 0 else 0.0

    rng = random.Random(seed)
    bootstrap_deltas: list[float] = []

    for _ in range(iterations):
        sampled_keys = [rng.choice(cluster_keys) for _ in range(n_clusters)]
        all_pairs = [pair for k in sampled_keys for pair in clusters[k]]
        if not all_pairs:
            bootstrap_deltas.append(0.0)
            continue
        delta = sum(c - b for b, c in all_pairs) / len(all_pairs)
        bootstrap_deltas.append(delta)

    bootstrap_deltas.sort()

    # Confidence interval
    lo_idx = max(0, int(iterations * (alpha / 2)) - 1)
    hi_idx = min(iterations - 1, int(iterations * (1 - alpha / 2)))
    ci = (bootstrap_deltas[lo_idx], bootstrap_deltas[hi_idx])

    # p-value: fraction of bootstrap deltas <= 0 (one-sided)
    count_le_zero = sum(1 for d in bootstrap_deltas if d <= 0)
    p_value = (count_le_zero + 1) / (iterations + 1)

    # Power estimate: fraction of bootstrap samples where delta > min_effect_size
    power_estimate = sum(1 for d in bootstrap_deltas if d > min_effect_size) / iterations

    return ClusteredBootstrapResult(
        observed_delta=observed_delta,
        p_value=p_value,
        is_significant=p_value < alpha,
        confidence_interval=ci,
        effect_size=effect_size,
        power_estimate=power_estimate,
        n_clusters=n_clusters,
        n_observations=n,
    )


@dataclass
class SequentialTestResult:
    """Result of a sequential (group-sequential) hypothesis test."""

    should_stop: bool
    reject_null: bool
    current_z: float
    boundary: float
    n_looks: int
    alpha_spent: float


def sequential_test(
    cumulative_deltas: list[float],
    *,
    alpha: float = 0.05,
    max_looks: int = 10,
) -> SequentialTestResult:
    """O'Brien-Fleming-style group-sequential test.

    Uses an alpha-spending function ``alpha_i = alpha * (i / max_looks) ** 2``
    where *i* is the current look number (``len(cumulative_deltas)``).

    The z-statistic is derived from the cumulative deltas assuming unit variance
    scaled by sqrt(n).
    """
    n_looks = len(cumulative_deltas)
    if n_looks == 0:
        return SequentialTestResult(
            should_stop=False,
            reject_null=False,
            current_z=0.0,
            boundary=float("inf"),
            n_looks=0,
            alpha_spent=0.0,
        )

    # Alpha spent at this look
    fraction = min(n_looks / max_looks, 1.0)
    alpha_spent = alpha * (fraction ** 2)

    # z-statistic: mean of cumulative deltas * sqrt(n)
    mean_delta = sum(cumulative_deltas) / n_looks
    current_z = mean_delta * math.sqrt(n_looks)

    # Boundary from alpha_spent (two-sided, use half for one-sided comparison)
    # Using inverse normal approximation: Phi^{-1}(1 - alpha_spent/2)
    boundary = _inv_normal(1.0 - alpha_spent / 2.0) if alpha_spent > 0 else float("inf")

    reject_null = abs(current_z) >= boundary
    should_stop = reject_null or n_looks >= max_looks

    return SequentialTestResult(
        should_stop=should_stop,
        reject_null=reject_null,
        current_z=current_z,
        boundary=boundary,
        n_looks=n_looks,
        alpha_spent=alpha_spent,
    )


def _inv_normal(p: float) -> float:
    """Approximate inverse of the standard normal CDF (Beasley-Springer-Moro)."""
    if p <= 0.0:
        return -float("inf")
    if p >= 1.0:
        return float("inf")
    if p == 0.5:
        return 0.0

    # Rational approximation (Abramowitz & Stegun 26.2.23)
    if p < 0.5:
        t = math.sqrt(-2.0 * math.log(p))
    else:
        t = math.sqrt(-2.0 * math.log(1.0 - p))

    c0 = 2.515517
    c1 = 0.802853
    c2 = 0.010328
    d1 = 1.432788
    d2 = 0.189269
    d3 = 0.001308

    result = t - (c0 + c1 * t + c2 * t * t) / (1.0 + d1 * t + d2 * t * t + d3 * t * t * t)
    return result if p >= 0.5 else -result


def multiple_hypothesis_correction(
    p_values: list[float],
    *,
    alpha: float = 0.05,
    method: str = "holm",
) -> list[tuple[int, float, bool]]:
    """Holm-Bonferroni multiple-hypothesis correction.

    Returns a list of ``(original_index, adjusted_p_value, is_significant)`` tuples
    sorted by original index.
    """
    if method != "holm":
        raise ValueError(f"Unsupported method: {method!r}. Only 'holm' is implemented.")

    n = len(p_values)
    if n == 0:
        return []

    # Sort by p-value, keeping original index
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])

    results: dict[int, tuple[float, bool]] = {}
    cumulative_max = 0.0
    for rank, (orig_idx, pval) in enumerate(indexed):
        # Holm correction: p * (n - rank)
        adjusted = pval * (n - rank)
        # Enforce monotonicity
        cumulative_max = max(cumulative_max, adjusted)
        adjusted = min(cumulative_max, 1.0)
        results[orig_idx] = (adjusted, adjusted < alpha)

    return [(idx, results[idx][0], results[idx][1]) for idx in range(n)]


@dataclass
class MinSampleSize:
    """Sample-size adequacy check for a single metric."""

    metric_name: str
    min_samples: int
    current_samples: int
    is_sufficient: bool


def check_sample_sizes(
    metric_values: dict[str, list[float]],
    *,
    min_per_metric: int = 30,
) -> list[MinSampleSize]:
    """Check whether each metric has enough samples.

    Returns one :class:`MinSampleSize` per metric, sorted by metric name.
    """
    results: list[MinSampleSize] = []
    for name in sorted(metric_values):
        current = len(metric_values[name])
        results.append(
            MinSampleSize(
                metric_name=name,
                min_samples=min_per_metric,
                current_samples=current,
                is_sufficient=current >= min_per_metric,
            )
        )
    return results


def judge_variance_estimate(
    scores: list[float],
    *,
    n_resample: int = 100,
    seed: int = 42,
) -> float:
    """Bootstrap estimate of judge-score standard deviation.

    Resamples *scores* with replacement ``n_resample`` times, computes the mean
    of each resample, and returns the standard deviation of those means — a
    measure of judge inconsistency.
    """
    n = len(scores)
    if n == 0:
        return 0.0

    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(n_resample):
        sample = [rng.choice(scores) for _ in range(n)]
        means.append(sum(sample) / n)

    overall_mean = sum(means) / len(means)
    variance = sum((m - overall_mean) ** 2 for m in means) / len(means)
    return variance ** 0.5
