"""Unit tests for the ConstrainedScorer."""

from __future__ import annotations

from evals.scorer import CompositeScorer, ConstrainedScorer, EvalResult


def _result(
    case_id: str = "c1",
    category: str = "happy_path",
    passed: bool = True,
    quality_score: float = 0.8,
    safety_passed: bool = True,
    latency_ms: float = 100.0,
    token_count: int = 200,
) -> EvalResult:
    """Build a minimal EvalResult."""
    return EvalResult(
        case_id=case_id,
        category=category,
        passed=passed,
        quality_score=quality_score,
        safety_passed=safety_passed,
        latency_ms=latency_ms,
        token_count=token_count,
    )


def test_constrained_scorer_rejects_safety_failures() -> None:
    """Safety failures should set constraints_passed=False and composite=0."""
    scorer = ConstrainedScorer(mode="constrained")
    results = [
        _result(case_id="c1", safety_passed=True, quality_score=0.9),
        _result(case_id="c2", safety_passed=False, quality_score=0.7),
    ]

    score = scorer.score(results)

    assert score.constraints_passed is False
    assert score.composite == 0.0
    assert len(score.constraint_violations) > 0
    assert "safety" in score.constraint_violations[0].lower()


def test_constrained_scorer_passes_clean_results() -> None:
    """All safe results should yield constraints_passed=True and positive composite."""
    scorer = ConstrainedScorer(mode="constrained")
    results = [
        _result(case_id="c1", safety_passed=True, quality_score=0.8),
        _result(case_id="c2", safety_passed=True, quality_score=0.9),
    ]

    score = scorer.score(results)

    assert score.constraints_passed is True
    assert score.composite > 0.0
    assert score.constraint_violations == []
    assert score.optimization_mode == "constrained"


def test_constrained_scorer_weighted_mode_matches_original() -> None:
    """Weighted mode should produce the same composite as CompositeScorer."""
    results = [
        _result(case_id="c1", quality_score=0.8, latency_ms=100.0, token_count=200),
        _result(case_id="c2", quality_score=0.6, latency_ms=300.0, token_count=400),
    ]

    original_scorer = CompositeScorer()
    original_score = original_scorer.score(results)

    constrained_scorer = ConstrainedScorer(mode="weighted")
    constrained_score = constrained_scorer.score(results)

    assert constrained_score.composite == original_score.composite
    assert constrained_score.quality == original_score.quality
    assert constrained_score.safety == original_score.safety
    assert constrained_score.optimization_mode == "weighted"


def test_constrained_scorer_lexicographic_mode() -> None:
    """Lexicographic mode: quality dominates, cost and latency are tiebreakers."""
    scorer = ConstrainedScorer(mode="lexicographic")

    # High quality — composite should be quality + small tiebreakers
    high_q_results = [
        _result(case_id="c1", quality_score=0.9, safety_passed=True, latency_ms=100.0, token_count=100),
    ]
    high_score = scorer.score(high_q_results)

    # Lower quality — composite should be lower
    low_q_results = [
        _result(case_id="c1", quality_score=0.6, safety_passed=True, latency_ms=100.0, token_count=100),
    ]
    low_score = scorer.score(low_q_results)

    assert high_score.constraints_passed is True
    assert low_score.constraints_passed is True
    # Quality dominates in lexicographic mode
    assert high_score.composite > low_score.composite
    assert high_score.optimization_mode == "lexicographic"


def test_constraint_check_regression_cases() -> None:
    """Regression-category cases that fail should trigger a constraint violation."""
    scorer = ConstrainedScorer(mode="constrained")
    results = [
        _result(case_id="c1", category="happy_path", passed=True, safety_passed=True),
        _result(case_id="reg1", category="regression", passed=False, safety_passed=True),
        _result(case_id="reg2", category="regression", passed=True, safety_passed=True),
    ]

    score = scorer.score(results)

    assert score.constraints_passed is False
    assert score.composite == 0.0
    violations_text = " ".join(score.constraint_violations)
    assert "regression" in violations_text.lower()
    assert "reg1" in violations_text
