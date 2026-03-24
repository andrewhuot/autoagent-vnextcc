"""Tests for LayeredDimensionScores and LayeredScorer."""

from __future__ import annotations

import pytest

from core.types import MetricLayer
from evals.scorer import DimensionScores, EvalResult, LayeredDimensionScores, LayeredScorer


# ---------------------------------------------------------------------------
# LayeredDimensionScores tests
# ---------------------------------------------------------------------------


def test_layered_dimensions_get_layer_hard_gate():
    dims = LayeredDimensionScores(
        safety_compliance=1.0,
        authorization_privacy=1.0,
        state_integrity=0.95,
        p0_regressions=0.0,
    )

    assert dims.get_layer("safety_compliance") == MetricLayer.HARD_GATE
    assert dims.get_layer("p0_regressions") == MetricLayer.HARD_GATE


def test_layered_dimensions_get_layer_outcome():
    dims = LayeredDimensionScores(
        task_success_rate=0.9,
        groundedness=0.85,
        user_satisfaction_proxy=0.8,
    )

    assert dims.get_layer("task_success_rate") == MetricLayer.OUTCOME
    assert dims.get_layer("groundedness") == MetricLayer.OUTCOME


def test_layered_dimensions_get_layer_slo():
    dims = LayeredDimensionScores(
        latency_p50=1500.0,
        latency_p95=4000.0,
        escalation_rate=0.15,
    )

    assert dims.get_layer("latency_p50") == MetricLayer.SLO
    assert dims.get_layer("escalation_rate") == MetricLayer.SLO


def test_layered_dimensions_get_by_layer():
    dims = LayeredDimensionScores(
        safety_compliance=1.0,
        task_success_rate=0.9,
        latency_p50=1500.0,
        tool_correctness=0.95,
    )

    hard_gates = dims.get_by_layer(MetricLayer.HARD_GATE)
    outcomes = dims.get_by_layer(MetricLayer.OUTCOME)
    slos = dims.get_by_layer(MetricLayer.SLO)
    diagnostics = dims.get_by_layer(MetricLayer.DIAGNOSTIC)

    assert "safety_compliance" in hard_gates
    assert "task_success_rate" in outcomes
    assert "latency_p50" in slos
    assert "tool_correctness" in diagnostics


def test_layered_dimensions_check_hard_gates_all_pass():
    dims = LayeredDimensionScores(
        safety_compliance=1.0,
        authorization_privacy=1.0,
        state_integrity=1.0,
        p0_regressions=0.0,
    )

    passed, violations = dims.check_hard_gates()

    assert passed is True
    assert len(violations) == 0


def test_layered_dimensions_check_hard_gates_safety_fail():
    dims = LayeredDimensionScores(
        safety_compliance=0.8,  # below 1.0
        authorization_privacy=1.0,
        state_integrity=1.0,
        p0_regressions=0.0,
    )

    passed, violations = dims.check_hard_gates()

    assert passed is False
    assert len(violations) > 0
    assert any("safety_compliance" in v for v in violations)


def test_layered_dimensions_check_hard_gates_p0_regression():
    dims = LayeredDimensionScores(
        safety_compliance=1.0,
        authorization_privacy=1.0,
        state_integrity=1.0,
        p0_regressions=1.0,  # above 0.0
    )

    passed, violations = dims.check_hard_gates()

    assert passed is False
    assert any("p0_regressions" in v for v in violations)


# ---------------------------------------------------------------------------
# LayeredScorer tests
# ---------------------------------------------------------------------------


def test_layered_scorer_score_returns_composite_with_layered_dimensions():
    scorer = LayeredScorer(mode="constrained")
    results = [
        EvalResult(
            case_id="c1",
            category="general",
            passed=True,
            quality_score=0.9,
            safety_passed=True,
            latency_ms=1200,
            token_count=150,
            routing_correct=True,
            handoff_context_preserved=True,
        ),
    ]

    composite = scorer.score(results)

    assert composite.dimensions is not None
    assert isinstance(composite.dimensions, LayeredDimensionScores)
    assert hasattr(composite.dimensions, "state_integrity")
    assert hasattr(composite.dimensions, "groundedness")


def test_layered_scorer_check_gates_passes():
    scorer = LayeredScorer(mode="constrained")
    dims = LayeredDimensionScores(
        safety_compliance=1.0,
        authorization_privacy=1.0,
        state_integrity=1.0,
        p0_regressions=0.0,
    )

    passed, violations = scorer.check_gates(dims)

    assert passed is True
    assert len(violations) == 0


def test_layered_scorer_check_gates_fails():
    scorer = LayeredScorer(mode="constrained")
    dims = LayeredDimensionScores(
        safety_compliance=0.9,
        authorization_privacy=1.0,
        state_integrity=1.0,
        p0_regressions=0.0,
    )

    passed, violations = scorer.check_gates(dims)

    assert passed is False
    assert len(violations) > 0


def test_layered_scorer_compute_outcome_score():
    scorer = LayeredScorer(mode="constrained")
    dims = LayeredDimensionScores(
        task_success_rate=0.9,
        groundedness=0.8,
        user_satisfaction_proxy=0.85,
    )

    outcome_score = scorer.compute_outcome_score(dims)

    assert 0.0 <= outcome_score <= 1.0
    # Should be weighted average of outcome metrics
    assert outcome_score > 0.7


def test_layered_scorer_check_slos_all_pass():
    scorer = LayeredScorer(mode="constrained")
    dims = LayeredDimensionScores(
        latency_p50=1500.0,
        latency_p95=4000.0,
        latency_p99=8000.0,
        escalation_rate=0.1,
    )

    passed, violations = scorer.check_slos(dims)

    assert passed is True
    assert len(violations) == 0


def test_layered_scorer_check_slos_latency_breach():
    scorer = LayeredScorer(mode="constrained")
    dims = LayeredDimensionScores(
        latency_p50=1500.0,
        latency_p95=6000.0,  # exceeds default 5000
        latency_p99=8000.0,
        escalation_rate=0.1,
    )

    passed, violations = scorer.check_slos(dims)

    assert passed is False
    assert any("latency_p95" in v for v in violations)


def test_layered_scorer_check_slos_custom_thresholds():
    scorer = LayeredScorer(mode="constrained")
    dims = LayeredDimensionScores(
        latency_p50=1500.0,
        latency_p95=4000.0,
    )
    custom_slos = {
        "latency_p50": 1000.0,  # stricter than default
        "latency_p95": 3000.0,
    }

    passed, violations = scorer.check_slos(dims, slo_config=custom_slos)

    assert passed is False
    assert len(violations) > 0
