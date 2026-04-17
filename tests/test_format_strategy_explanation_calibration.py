"""Tests for the calibration_factor extension to format_strategy_explanation (R6.B.3).

When calibration_factor is None (default), output must be byte-identical to
pre-R6 behavior — preserving the existing --explain-strategy golden and all
other callers. When set, a calibrated-effectiveness clause is appended.
"""

from __future__ import annotations

import pytest

from optimizer.proposer import StrategyExplanation, format_strategy_explanation


def _ranked_fixture() -> StrategyExplanation:
    return StrategyExplanation(
        strategy="rewrite_prompt",
        surface="system_prompt",
        effectiveness=0.62,
        samples=15,
        explored=False,
    )


def _explored_fixture() -> StrategyExplanation:
    return StrategyExplanation(
        strategy="tighten_constraint",
        surface="system_prompt",
        effectiveness=0.70,
        samples=8,
        explored=True,
    )


def test_format_explanation_no_factor_preserves_output_ranked() -> None:
    """Without calibration_factor, ranked output matches pre-R6 byte-for-byte."""
    e = _ranked_fixture()
    expected = (
        "selected mutation rewrite_prompt because "
        "effectiveness=0.62 on similar surfaces "
        "(n=15 samples)"
    )
    assert format_strategy_explanation(e) == expected


def test_format_explanation_no_factor_preserves_output_explored() -> None:
    """Without calibration_factor, explored output matches pre-R6 byte-for-byte."""
    e = _explored_fixture()
    expected = (
        "selected mutation tighten_constraint via random exploration "
        "(epsilon-greedy; past effectiveness=0.70)"
    )
    assert format_strategy_explanation(e) == expected


def test_format_explanation_positive_factor_renders_overperform() -> None:
    """Positive factor appends an overperformed clause with calibrated value."""
    e = _ranked_fixture()
    result = format_strategy_explanation(e, calibration_factor=0.04)
    assert "overperformed by 0.04" in result
    assert "calibrated effectiveness=0.66" in result


def test_format_explanation_negative_factor_renders_underperform() -> None:
    """Negative factor appends an underperformed clause with calibrated value."""
    e = _ranked_fixture()
    result = format_strategy_explanation(e, calibration_factor=-0.06)
    assert "underperformed by 0.06" in result
    assert "calibrated effectiveness=0.56" in result


def test_format_explanation_factor_zero_no_clause() -> None:
    """factor=0.0 carries no signal — output identical to the no-factor case."""
    e = _ranked_fixture()
    base = format_strategy_explanation(e)
    with_zero = format_strategy_explanation(e, calibration_factor=0.0)
    assert with_zero == base


def test_format_explanation_clamps_above_one() -> None:
    """Calibrated effectiveness clamped to 1.00 when sum exceeds 1.0."""
    e = StrategyExplanation(
        strategy="rewrite_prompt",
        surface="system_prompt",
        effectiveness=0.95,
        samples=15,
        explored=False,
    )
    result = format_strategy_explanation(e, calibration_factor=0.20)
    assert "calibrated effectiveness=1.00" in result


def test_format_explanation_clamps_below_zero() -> None:
    """Calibrated effectiveness clamped to 0.00 when sum drops below 0.0."""
    e = StrategyExplanation(
        strategy="rewrite_prompt",
        surface="system_prompt",
        effectiveness=0.05,
        samples=15,
        explored=False,
    )
    result = format_strategy_explanation(e, calibration_factor=-0.20)
    assert "calibrated effectiveness=0.00" in result


def test_format_explanation_keyword_only_enforced() -> None:
    """calibration_factor MUST be keyword-only — positional passing is a TypeError."""
    e = _ranked_fixture()
    with pytest.raises(TypeError):
        format_strategy_explanation(e, 0.05)  # type: ignore[misc]


def test_format_explanation_prefix_unchanged_with_factor() -> None:
    """The calibration clause is strictly appended, not woven into the base."""
    e = _ranked_fixture()
    base = format_strategy_explanation(e)
    with_factor = format_strategy_explanation(e, calibration_factor=0.04)
    assert with_factor.startswith(base)
