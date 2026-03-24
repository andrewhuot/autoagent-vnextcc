"""Statistical significance utilities for optimization acceptance gating."""

from __future__ import annotations

import random
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
