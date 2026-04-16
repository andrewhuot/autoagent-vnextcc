"""Tests for Optimizer auto-grow case generation (R3.6)."""

from unittest.mock import MagicMock

from evals.coverage_analyzer import CoverageAnalyzer, CoverageReport
from optimizer.loop import Optimizer


def _analyzer_with_coverage(by_surface: dict[str, float]) -> CoverageAnalyzer:
    analyzer = CoverageAnalyzer()
    analyzer._last_report = CoverageReport(
        total_cases=0, gaps=[], coverage_by_surface=by_surface,
    )
    return analyzer


def _make_optimizer(**overrides) -> Optimizer:
    """Build an Optimizer with minimum-viable dependencies for unit testing."""
    base = dict(
        eval_runner=MagicMock(),
        coverage_analyzer=None,
        card_case_generator=None,
        agent_card=None,
        auto_grow_cases=True,
    )
    base.update(overrides)
    return Optimizer(**base)


def test_auto_grow_fires_for_low_coverage_surface() -> None:
    analyzer = _analyzer_with_coverage({"routing": 0.20, "tools": 0.90})
    gen = MagicMock()
    gen.generate_routing_cases.return_value = ["r1", "r2"]
    gen.generate_tool_cases.return_value = []
    card = MagicMock()
    opt = _make_optimizer(
        coverage_analyzer=analyzer,
        card_case_generator=gen,
        agent_card=card,
    )
    count = opt._maybe_auto_grow_cases()
    assert count == 2
    gen.generate_routing_cases.assert_called_once()
    gen.generate_tool_cases.assert_not_called()


def test_auto_grow_skips_when_all_surfaces_above_threshold() -> None:
    analyzer = _analyzer_with_coverage({"routing": 0.50, "tools": 0.80})
    gen = MagicMock()
    card = MagicMock()
    opt = _make_optimizer(
        coverage_analyzer=analyzer,
        card_case_generator=gen,
        agent_card=card,
    )
    assert opt._maybe_auto_grow_cases() == 0
    gen.generate_routing_cases.assert_not_called()


def test_auto_grow_disabled_by_flag() -> None:
    analyzer = _analyzer_with_coverage({"routing": 0.10})
    gen = MagicMock()
    gen.generate_routing_cases.return_value = ["r1"]
    opt = _make_optimizer(
        coverage_analyzer=analyzer,
        card_case_generator=gen,
        agent_card=MagicMock(),
        auto_grow_cases=False,
    )
    assert opt._maybe_auto_grow_cases() == 0
    gen.generate_routing_cases.assert_not_called()


def test_auto_grow_noop_when_dependencies_missing() -> None:
    opt = _make_optimizer()  # all coverage/generator/card fields None
    assert opt._maybe_auto_grow_cases() == 0


def test_auto_grow_noop_when_no_prior_report() -> None:
    analyzer = CoverageAnalyzer()  # _last_report is None
    gen = MagicMock()
    opt = _make_optimizer(
        coverage_analyzer=analyzer,
        card_case_generator=gen,
        agent_card=MagicMock(),
    )
    assert opt._maybe_auto_grow_cases() == 0
    gen.generate_routing_cases.assert_not_called()


def test_auto_grow_swallows_generator_errors() -> None:
    analyzer = _analyzer_with_coverage({"routing": 0.10})
    gen = MagicMock()
    gen.generate_routing_cases.side_effect = RuntimeError("kaboom")
    opt = _make_optimizer(
        coverage_analyzer=analyzer,
        card_case_generator=gen,
        agent_card=MagicMock(),
    )
    # Should not raise; returns 0 generated cases.
    assert opt._maybe_auto_grow_cases() == 0
