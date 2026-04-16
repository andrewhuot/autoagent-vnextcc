"""Tests for strategy-ranking explanation output (R3.5)."""

from __future__ import annotations

import random

from optimizer.proposer import (
    Proposer,
    StrategyExplanation,
    format_strategy_explanation,
)
from optimizer.reflection import SurfaceEffectiveness


class _FakeReflection:
    def __init__(self, table):
        self._t = table

    def read_surface_effectiveness(self, surface):
        return self._t.get(surface)


def _eff(surface, attempts, avg_improvement):
    return SurfaceEffectiveness(
        surface=surface,
        attempts=attempts,
        successes=attempts,
        avg_improvement=avg_improvement,
        last_attempted=0.0,
    )


def test_format_strategy_explanation_one_line() -> None:
    e = StrategyExplanation(
        strategy="tighten_prompt",
        surface="prompting",
        effectiveness=0.70,
        samples=12,
        explored=False,
    )
    line = format_strategy_explanation(e)
    assert line == (
        "selected mutation tighten_prompt because effectiveness=0.70 "
        "on similar surfaces (n=12 samples)"
    )


def test_format_strategy_explanation_exploration_marker() -> None:
    e = StrategyExplanation(
        strategy="refactor",
        surface="architecture",
        effectiveness=0.0,
        samples=0,
        explored=True,
    )
    line = format_strategy_explanation(e)
    assert "refactor" in line
    assert "exploration" in line.lower()


def test_rank_strategies_populates_last_explanation(monkeypatch) -> None:
    monkeypatch.setattr(
        "optimizer.proposer.STRATEGY_TO_SURFACE",
        {"tighten_prompt": "api", "add_tool": "cli"},
    )
    reflection = _FakeReflection(
        {
            "api": _eff("api", 12, 0.70),
            "cli": _eff("cli", 4, 0.10),
        }
    )
    p = Proposer()
    rng = random.Random(0)  # rng.random() first call at seed=0 is ~0.84 — NOT in explore band
    ranked = p._rank_strategies(
        ["add_tool", "tighten_prompt"],
        reflection_engine=reflection,
        epsilon=0.1,
        rng=rng,
    )
    assert ranked[0] == "tighten_prompt"
    assert hasattr(p, "_last_explanation")
    assert len(p._last_explanation) == 2
    first = p._last_explanation[0]
    assert first.strategy == "tighten_prompt"
    assert first.effectiveness == 0.70
    assert first.samples == 12
    assert first.explored is False


def test_rank_strategies_explanation_marks_exploration(monkeypatch) -> None:
    monkeypatch.setattr(
        "optimizer.proposer.STRATEGY_TO_SURFACE",
        {"tighten_prompt": "api", "add_tool": "cli"},
    )
    reflection = _FakeReflection(
        {
            "api": _eff("api", 12, 0.70),
            "cli": _eff("cli", 4, 0.10),
        }
    )
    p = Proposer()
    # Force the explore branch: epsilon=1.0 always shuffles.
    rng = random.Random(42)
    p._rank_strategies(
        ["add_tool", "tighten_prompt"],
        reflection_engine=reflection,
        epsilon=1.0,
        rng=rng,
    )
    assert all(e.explored for e in p._last_explanation)


def test_rank_strategies_no_reflection_no_explanation() -> None:
    p = Proposer()
    p._rank_strategies(
        ["a", "b"],
        reflection_engine=None,
        epsilon=0.0,
        rng=random.Random(0),
    )
    # No reflection -> no useful explanation; expect empty list.
    assert p._last_explanation == []
