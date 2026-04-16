"""Tests for CompositeWeights yaml loading and validation (R3.9)."""

import pytest

from evals.composite_weights import (
    CompositeWeights,
    load_from_workspace,
    validate_weights,
)
from evals.scorer import CompositeScorer, EvalResult


def _result(quality: float, safety_passed: bool = True,
            latency_ms: float = 0.0, token_count: int = 0) -> EvalResult:
    return EvalResult(
        case_id="c", category="happy_path", passed=True,
        quality_score=quality, safety_passed=safety_passed,
        latency_ms=latency_ms, token_count=token_count,
    )


# ----- CompositeWeights dataclass -----

def test_composite_weights_defaults_match_pre_r3_constants() -> None:
    w = CompositeWeights()
    assert w.quality == 0.40
    assert w.safety == 0.25
    assert w.latency == 0.20
    assert w.cost == 0.15


def test_composite_weights_frozen() -> None:
    w = CompositeWeights()
    with pytest.raises(Exception):  # FrozenInstanceError (dataclasses)
        w.quality = 0.99  # type: ignore[misc]


# ----- validate_weights -----

def test_validate_weights_accepts_summing_to_one() -> None:
    w = CompositeWeights(quality=0.4, safety=0.25, latency=0.2, cost=0.15)
    validate_weights(w)  # no raise


def test_validate_weights_rejects_bad_sum() -> None:
    w = CompositeWeights(quality=0.5, safety=0.25, latency=0.2, cost=0.15)
    with pytest.raises(ValueError, match="1.0"):
        validate_weights(w)


def test_validate_weights_tolerates_float_noise() -> None:
    # Floating-point rounding: 0.40 + 0.25 + 0.20 + 0.15 = 1.0 but via other
    # paths (e.g., 0.1 + 0.9) the sum can land at 1.0000000000000002.
    w = CompositeWeights(quality=0.1, safety=0.9, latency=0.0, cost=0.0)
    validate_weights(w, tolerance=1e-6)  # must not raise


def test_validate_weights_rejects_negative() -> None:
    w = CompositeWeights(quality=1.1, safety=-0.1, latency=0.0, cost=0.0)
    with pytest.raises(ValueError, match="non-negative|negative"):
        validate_weights(w)


# ----- load_from_workspace -----

def test_load_from_yaml_reads_eval_composite_weights(tmp_path) -> None:
    yml = tmp_path / "agentlab.yaml"
    yml.write_text(
        "eval:\n"
        "  composite:\n"
        "    weights:\n"
        "      quality: 0.45\n"
        "      safety: 0.25\n"
        "      latency: 0.15\n"
        "      cost: 0.15\n"
    )
    w = load_from_workspace(str(yml))
    assert w.quality == 0.45
    assert w.safety == 0.25
    assert w.latency == 0.15
    assert w.cost == 0.15


def test_load_from_yaml_missing_file_returns_defaults(tmp_path) -> None:
    w = load_from_workspace(str(tmp_path / "nonexistent.yaml"))
    assert (w.quality, w.safety, w.latency, w.cost) == (0.40, 0.25, 0.20, 0.15)


def test_load_from_yaml_missing_section_returns_defaults(tmp_path) -> None:
    yml = tmp_path / "agentlab.yaml"
    yml.write_text("harness: {}\n")
    w = load_from_workspace(str(yml))
    assert (w.quality, w.safety, w.latency, w.cost) == (0.40, 0.25, 0.20, 0.15)


def test_load_from_yaml_partial_block_fills_defaults(tmp_path) -> None:
    """Only quality overridden; the other three fall back to defaults."""
    yml = tmp_path / "agentlab.yaml"
    yml.write_text(
        "eval:\n  composite:\n    weights:\n      quality: 0.60\n"
    )
    w = load_from_workspace(str(yml))
    assert w.quality == 0.60
    assert w.safety == 0.25
    assert w.latency == 0.20
    assert w.cost == 0.15


# ----- CompositeScorer injection -----

def test_composite_scorer_default_preserves_pre_r3_behavior() -> None:
    """CompositeScorer() with no args must behave exactly like pre-R3."""
    scorer = CompositeScorer()
    results = [
        _result(quality=1.0, safety_passed=True, latency_ms=0, token_count=0),
    ]
    score = scorer.score(results)
    # With perfect results, composite should be 1.0 (within rounding).
    assert score.composite == 1.0
    assert score.quality == 1.0
    assert score.safety == 1.0


def test_composite_scorer_uses_injected_weights() -> None:
    """Quality-heavy weights mean a high-quality-but-low-safety run scores higher
    than it would under the default weights."""
    results = [
        _result(quality=1.0, safety_passed=False, latency_ms=0, token_count=0),
    ]
    # Default weights: 0.4 * 1.0 + 0.25 * 0.0 + 0.2 * 1.0 + 0.15 * 1.0 = 0.75
    default_score = CompositeScorer().score(results).composite
    # Quality-heavy weights: 0.8 * 1.0 + 0.1 * 0.0 + 0.05 * 1.0 + 0.05 * 1.0 = 0.90
    quality_heavy = CompositeWeights(quality=0.8, safety=0.1, latency=0.05, cost=0.05)
    heavy_score = CompositeScorer(weights=quality_heavy).score(results).composite
    assert heavy_score > default_score
    assert heavy_score == pytest.approx(0.90, abs=0.001)
    assert default_score == pytest.approx(0.75, abs=0.001)


def test_composite_scorer_rejects_invalid_weights() -> None:
    bad = CompositeWeights(quality=0.5, safety=0.5, latency=0.5, cost=0.5)
    with pytest.raises(ValueError, match="1.0"):
        CompositeScorer(weights=bad)
