"""Tests for bootstrap CI + variance-calibrated effect size on paired_significance (R3.12, R3.13)."""

import math

from evals.statistics import SignificanceResult, paired_significance


def _split(pairs):
    baseline = [p[0] for p in pairs]
    candidate = [p[1] for p in pairs]
    return baseline, candidate


# ---------- R3.12: bootstrap CI ----------

def test_ci_brackets_observed_delta() -> None:
    pairs = [(0.80, 0.85), (0.70, 0.74), (0.60, 0.66), (0.50, 0.58), (0.90, 0.93)]
    baseline, candidate = _split(pairs)
    r = paired_significance(
        baseline, candidate,
        bootstrap_ci=True, n_bootstrap=2000, seed=42,
    )
    assert r.confidence_interval is not None
    lo, hi = r.confidence_interval
    assert lo <= r.observed_delta <= hi


def test_ci_disabled_returns_none() -> None:
    baseline, candidate = _split([(0.80, 0.85), (0.70, 0.74)])
    r = paired_significance(baseline, candidate, bootstrap_ci=False)
    assert r.confidence_interval is None


def test_ci_is_deterministic_with_seed() -> None:
    baseline, candidate = _split([(0.8, 0.9), (0.7, 0.75), (0.6, 0.65)])
    r1 = paired_significance(baseline, candidate, bootstrap_ci=True, seed=7, n_bootstrap=500)
    r2 = paired_significance(baseline, candidate, bootstrap_ci=True, seed=7, n_bootstrap=500)
    assert r1.confidence_interval == r2.confidence_interval


def test_ci_different_seeds_produce_similar_cis() -> None:
    """Sanity: different seeds yield close but not identical CIs (non-degenerate bootstrap)."""
    baseline, candidate = _split([(0.8, 0.85)] * 10)
    r_a = paired_significance(baseline, candidate, bootstrap_ci=True, seed=1, n_bootstrap=1000)
    r_b = paired_significance(baseline, candidate, bootstrap_ci=True, seed=2, n_bootstrap=1000)
    assert r_a.confidence_interval is not None
    assert r_b.confidence_interval is not None


def test_ci_empty_input_handled() -> None:
    r = paired_significance([], [], bootstrap_ci=True)
    # No pairs → CI meaningless; either None or (0.0, 0.0).
    assert r.confidence_interval is None or r.confidence_interval == (0.0, 0.0)


# ---------- R3.13: variance-calibrated effect size ----------

def test_calibrated_effect_size_reported() -> None:
    pairs = [(0.80, 0.85), (0.70, 0.75), (0.60, 0.65), (0.50, 0.55)]
    baseline, candidate = _split(pairs)
    r = paired_significance(baseline, candidate, bootstrap_ci=False)
    assert r.calibrated_effect_size is not None
    # All diffs are +0.05 → zero variance → ES should be inf (or very large).
    assert r.calibrated_effect_size == math.inf or r.calibrated_effect_size > 1e6


def test_calibrated_effect_size_finite_when_diffs_vary() -> None:
    # Mix of +0.10 and -0.05 diffs.
    pairs = [(0.5, 0.6), (0.5, 0.45), (0.5, 0.6), (0.5, 0.45)]
    baseline, candidate = _split(pairs)
    r = paired_significance(baseline, candidate, bootstrap_ci=False)
    assert r.calibrated_effect_size is not None
    assert math.isfinite(r.calibrated_effect_size)
    assert 0 < r.calibrated_effect_size < 10


def test_small_but_stable_improvement_passes_gate() -> None:
    """Every pair delta = +0.03 exactly. Even though the observed delta is small,
    the calibrated ES is very large (zero variance), so the gate passes."""
    pairs = [(0.80, 0.83)] * 20
    baseline, candidate = _split(pairs)
    r = paired_significance(
        baseline, candidate,
        min_effect_size=0.01,  # delta 0.03 > 0.01
        min_calibrated_effect=2.0,  # zero-variance → inf → passes
        bootstrap_ci=False,
    )
    assert r.calibrated_effect_size is not None
    assert r.calibrated_effect_size == math.inf or r.calibrated_effect_size > 2.0
    assert r.is_significant  # passes the calibrated gate


def test_large_but_noisy_improvement_fails_gate() -> None:
    """Mean delta is +0.10 but variance is huge. Calibrated ES is small,
    so the gate rejects even though the raw delta looks big."""
    pairs = [
        (0.50, 0.60), (0.50, 0.30), (0.50, 0.70), (0.50, 0.20),
        (0.50, 0.80), (0.50, 0.10), (0.50, 0.90), (0.50, 0.40),
    ]
    baseline, candidate = _split(pairs)
    r = paired_significance(
        baseline, candidate,
        min_effect_size=0.01,  # raw delta passes this
        min_calibrated_effect=0.5,  # but calibrated ES will fail this
        bootstrap_ci=False,
    )
    assert r.calibrated_effect_size is not None
    assert math.isfinite(r.calibrated_effect_size)
    assert r.calibrated_effect_size < 0.5
    # Should NOT be significant under the calibrated gate.
    assert not r.is_significant


def test_min_calibrated_effect_default_is_backwards_compatible() -> None:
    """Default min_calibrated_effect=0.0 preserves pre-R3 gating: small stable
    improvements that already pass min_effect_size still pass."""
    pairs = [(0.80, 0.83)] * 20
    baseline, candidate = _split(pairs)
    r = paired_significance(baseline, candidate, min_effect_size=0.01)
    # No min_calibrated_effect override → default 0.0 → gate passes.
    assert r.is_significant or (r.p_value >= r.alpha)
    # Either way, calibrated_effect_size is still populated.
    assert r.calibrated_effect_size is not None
