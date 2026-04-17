"""Production-score distribution drift detector (R6.9 / R6.10).

Compares the distribution of per-case composite scores in the current eval
run against the baseline distribution of recent runs. When the two
distributions diverge (KL(current || baseline) >= threshold), the eval
set is likely out of date relative to the production traffic being
scored — surface a recommendation to ingest fresh traces.

# NOTE: This module detects drift in the *production score distribution*
# (are we evaluating the right cases?). For *judge agreement drift* (are
# the judges still trustworthy?) see judges/drift_monitor.py — a
# distinct feature with a different trigger path.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

__all__ = ["DriftReport", "detect_distribution_drift"]


@dataclass
class DriftReport:
    """Outcome of a single drift-detection call.

    Fields are designed to be JSON-serializable for notification payloads.
    """

    diverged: bool
    kl: float  # KL(current || baseline), bucketed + smoothed, natural log.
    threshold: float
    baseline_size: int
    current_size: int
    recommendation: str


def _bucket(scores: Sequence[float], bins: int) -> list[float]:
    """Bucket ``scores`` into ``bins`` equal-width bins over ``[0, 1]``.

    Scores outside ``[0, 1]`` are clipped. Returns raw counts (not
    normalized). The last bin is inclusive of 1.0.
    """
    counts = [0.0] * bins
    for raw in scores:
        try:
            x = float(raw)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(x):
            continue
        if x < 0.0:
            x = 0.0
        elif x > 1.0:
            x = 1.0
        idx = int(x * bins)
        if idx >= bins:
            idx = bins - 1
        counts[idx] += 1.0
    return counts


def _to_probs(counts: list[float], eps: float) -> list[float]:
    """Normalize ``counts`` into a probability distribution with smoothing.

    Empty input yields a uniform distribution so KL stays finite.
    """
    total = sum(counts)
    if total == 0.0:
        n = len(counts)
        return [1.0 / n] * n
    return [(c / total) + eps for c in counts]


def detect_distribution_drift(
    baseline_scores: list[float],
    current_scores: list[float],
    *,
    threshold: float = 0.2,
    bins: int = 10,
    eps: float = 1e-9,
) -> DriftReport:
    """Compute KL(current || baseline) between bucketed score histograms.

    Both distributions are bucketed into ``bins`` equal-width bins over
    ``[0, 1]`` (scores outside the unit interval are clipped), smoothed
    by ``eps`` to avoid ``log(0)``, and compared using the natural log
    form of Kullback–Leibler divergence::

        KL(P || Q) = sum_i P_i * ln(P_i / Q_i)

    When ``kl >= threshold`` the report is flagged as ``diverged`` and
    includes a recommendation to ingest fresh traces. Otherwise the
    recommendation confirms the distribution is stable.
    """
    baseline_size = len(baseline_scores)
    current_size = len(current_scores)

    if baseline_size == 0 and current_size == 0:
        return DriftReport(
            diverged=False,
            kl=0.0,
            threshold=float(threshold),
            baseline_size=0,
            current_size=0,
            recommendation=(
                f"Eval distribution stable (KL=0.000 < {threshold})."
            ),
        )

    baseline_counts = _bucket(baseline_scores, bins)
    current_counts = _bucket(current_scores, bins)

    q = _to_probs(baseline_counts, eps)  # baseline
    p = _to_probs(current_counts, eps)  # current

    kl = 0.0
    for pi, qi in zip(p, q):
        # pi and qi are both > 0 because of the eps smoothing floor, so
        # the natural log is always well-defined.
        kl += pi * math.log(pi / qi)

    if not math.isfinite(kl) or kl < 0.0:
        # Numerical guardrail — KL is non-negative in theory, but rounding
        # near-zero can produce tiny negatives; clamp for callers.
        kl = max(0.0, kl) if math.isfinite(kl) else 0.0

    diverged = kl >= float(threshold)

    if diverged:
        recommendation = (
            f"Eval distribution diverged (KL={kl:.3f} >= {threshold}). "
            "Your eval set covers a stale slice of current production distribution. "
            "Ingest traces from the last N days: "
            "agentlab eval ingest --from-traces <path> --since 7d"
        )
    else:
        recommendation = (
            f"Eval distribution stable (KL={kl:.3f} < {threshold})."
        )

    return DriftReport(
        diverged=diverged,
        kl=float(kl),
        threshold=float(threshold),
        baseline_size=baseline_size,
        current_size=current_size,
        recommendation=recommendation,
    )
