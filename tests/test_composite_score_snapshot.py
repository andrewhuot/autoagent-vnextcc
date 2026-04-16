"""Tests for CompositeScore.weights_snapshot + historical rerender (R3.11)."""

import pytest

from evals.composite_weights import CompositeWeights
from evals.scorer import CompositeScore, CompositeScorer, EvalResult


def _result(quality: float, safety_passed: bool = True,
            latency_ms: float = 0.0, token_count: int = 0) -> EvalResult:
    return EvalResult(
        case_id="c", category="happy_path", passed=True,
        quality_score=quality, safety_passed=safety_passed,
        latency_ms=latency_ms, token_count=token_count,
    )


def test_score_carries_weights_snapshot_with_defaults() -> None:
    scorer = CompositeScorer()
    score = scorer.score([_result(quality=1.0)])
    assert score.weights_snapshot is not None
    assert score.weights_snapshot.quality == 0.40
    assert score.weights_snapshot.safety == 0.25
    assert score.weights_snapshot.latency == 0.20
    assert score.weights_snapshot.cost == 0.15


def test_score_carries_weights_snapshot_with_injected() -> None:
    w = CompositeWeights(quality=0.5, safety=0.2, latency=0.15, cost=0.15)
    scorer = CompositeScorer(weights=w)
    score = scorer.score([_result(quality=1.0)])
    assert score.weights_snapshot == w


def test_rerender_returns_score_unchanged_when_snapshot_is_none() -> None:
    """Historical data (pre-R3) has no snapshot; rerender must not crash."""
    score = CompositeScore(
        quality=0.5, safety=0.5, latency=0.5, cost=0.5,
        composite=0.5, results=[_result(quality=0.5)],
        weights_snapshot=None,
    )
    rerendered = CompositeScore.rerender(score)
    assert rerendered.composite == 0.5
    assert rerendered.weights_snapshot is None


def test_rerender_uses_snapshot_not_current_weights() -> None:
    """A score captured with quality-heavy weights re-renders at the same composite
    even after the *default* scorer has been used on similar results.

    This is the core invariant: snapshot wins over "current" settings.
    """
    results = [_result(quality=1.0, safety_passed=False, latency_ms=0, token_count=0)]
    # Score with quality-heavy weights (quality=0.80).
    quality_heavy = CompositeWeights(quality=0.8, safety=0.1, latency=0.05, cost=0.05)
    score = CompositeScorer(weights=quality_heavy).score(results)
    frozen_composite = score.composite
    assert frozen_composite == pytest.approx(0.90, abs=0.001)

    # Re-render uses the snapshot, NOT the default weights.
    rerendered = CompositeScore.rerender(score)
    assert rerendered.composite == frozen_composite
    assert rerendered.composite == pytest.approx(0.90, abs=0.001)


def test_rerender_is_idempotent() -> None:
    results = [_result(quality=1.0, safety_passed=True, latency_ms=0, token_count=0)]
    score = CompositeScorer().score(results)
    a = CompositeScore.rerender(score)
    b = CompositeScore.rerender(a)
    assert a.composite == b.composite
    assert a.weights_snapshot == b.weights_snapshot


def test_rerender_preserves_results_and_snapshot() -> None:
    """The rerendered score keeps the same results list and the same snapshot —
    that's what makes it reproducible."""
    w = CompositeWeights(quality=0.5, safety=0.2, latency=0.15, cost=0.15)
    results = [_result(quality=0.8), _result(quality=0.4)]
    score = CompositeScorer(weights=w).score(results)
    rerendered = CompositeScore.rerender(score)
    assert rerendered.weights_snapshot == w
    assert len(rerendered.results) == len(score.results)


def test_yaml_mutation_does_not_affect_historical_render(tmp_path, monkeypatch) -> None:
    """Operator scenario: score a run, mutate workspace yaml, re-render.
    The historical composite must be stable."""
    monkeypatch.chdir(tmp_path)
    # Write initial yaml (matches defaults anyway).
    (tmp_path / "agentlab.yaml").write_text(
        "eval:\n  composite:\n    weights:\n"
        "      quality: 0.4\n      safety: 0.25\n"
        "      latency: 0.2\n      cost: 0.15\n"
    )
    from evals.composite_weights import load_from_workspace
    weights_at_score_time = load_from_workspace("agentlab.yaml")
    results = [_result(quality=1.0, safety_passed=False)]
    score = CompositeScorer(weights=weights_at_score_time).score(results)
    frozen_composite = score.composite

    # Operator mutates workspace yaml to radically different weights.
    (tmp_path / "agentlab.yaml").write_text(
        "eval:\n  composite:\n    weights:\n"
        "      quality: 0.9\n      safety: 0.05\n"
        "      latency: 0.03\n      cost: 0.02\n"
    )
    # The historical score's snapshot still reflects the original weights.
    assert score.weights_snapshot.quality == 0.40
    # And re-rendering uses the snapshot, not the mutated yaml.
    rerendered = CompositeScore.rerender(score)
    assert rerendered.composite == frozen_composite


def test_rerender_supports_override_for_forensic_replay() -> None:
    """Allow an explicit `weights=` override on rerender for forensic/what-if
    analyses — e.g., 'what would this score be under today's weights?'.
    Explicit override does NOT mutate the snapshot on the returned score."""
    results = [_result(quality=1.0, safety_passed=False)]
    w_old = CompositeWeights(quality=0.5, safety=0.2, latency=0.15, cost=0.15)
    score = CompositeScorer(weights=w_old).score(results)
    original_composite = score.composite

    w_new = CompositeWeights(quality=0.9, safety=0.05, latency=0.03, cost=0.02)
    replayed = CompositeScore.rerender(score, weights=w_new)
    # Replay computes a DIFFERENT composite under the override.
    assert replayed.composite != original_composite
    # The replay's snapshot reflects what the replay used (w_new), not w_old.
    assert replayed.weights_snapshot == w_new
    # The original score is untouched.
    assert score.weights_snapshot == w_old
    assert score.composite == original_composite
