"""Tests for Proposer._rank_strategies epsilon-greedy ranking (R3.4)."""

from __future__ import annotations

import random

from optimizer.proposer import Proposer
from optimizer.reflection import SurfaceEffectiveness


class _FakeReflection:
    """Minimal stand-in that only implements read_surface_effectiveness."""

    def __init__(self, table: dict[str, SurfaceEffectiveness]):
        self._t = table

    def read_surface_effectiveness(self, s):
        return self._t.get(s)


def _eff(surface, attempts, avg_improvement):
    return SurfaceEffectiveness(
        surface=surface,
        attempts=attempts,
        successes=attempts,
        avg_improvement=avg_improvement,
        last_attempted=0.0,
    )


def test_rank_strategies_prefers_high_effectiveness_surface(monkeypatch) -> None:
    # patch STRATEGY_TO_SURFACE so test isn't coupled to prod mapping
    monkeypatch.setattr(
        "optimizer.proposer.STRATEGY_TO_SURFACE",
        {
            "tighten_prompt": "api",
            "add_tool": "cli",
            "refactor": "db",
        },
    )
    reflection = _FakeReflection(
        {
            "api": _eff("api", 10, 0.20),
            "cli": _eff("cli", 5, 0.05),
            "db": _eff("db", 1, 0.01),
        }
    )
    p = Proposer()
    rng = random.Random(42)
    # epsilon=0 -> pure exploitation
    ranked = p._rank_strategies(
        ["add_tool", "tighten_prompt", "refactor"],
        reflection_engine=reflection,
        epsilon=0.0,
        rng=rng,
    )
    assert ranked[0] == "tighten_prompt"  # api has highest avg_improvement
    assert ranked[-1] == "refactor"


def test_rank_strategies_epsilon_explores_deterministically() -> None:
    """With epsilon=0.1 and seed=42, over 1000 calls ~10% should be random order."""
    monkeypatch_map = {"tighten_prompt": "api", "add_tool": "cli", "refactor": "db"}
    import optimizer.proposer as pm

    original = pm.STRATEGY_TO_SURFACE
    pm.STRATEGY_TO_SURFACE = monkeypatch_map
    try:
        reflection = _FakeReflection(
            {
                "api": _eff("api", 10, 0.20),
                "cli": _eff("cli", 5, 0.05),
                "db": _eff("db", 1, 0.01),
            }
        )
        p = Proposer()
        rng = random.Random(42)
        exploit_top = 0
        explore_hits = 0
        for _ in range(1000):
            ranked = p._rank_strategies(
                ["add_tool", "tighten_prompt", "refactor"],
                reflection_engine=reflection,
                epsilon=0.1,
                rng=rng,
            )
            if ranked[0] == "tighten_prompt":
                exploit_top += 1
            else:
                explore_hits += 1
        # Expect ~100 explorations out of 1000 (bounded tolerance)
        assert 60 <= explore_hits <= 160, f"got {explore_hits}"
    finally:
        pm.STRATEGY_TO_SURFACE = original


def test_rank_strategies_no_reflection_returns_input_order() -> None:
    p = Proposer()
    ranked = p._rank_strategies(
        ["a", "b", "c"],
        reflection_engine=None,
        epsilon=0.0,
        rng=random.Random(1),
    )
    assert ranked == ["a", "b", "c"]


def test_rank_strategies_empty_input() -> None:
    p = Proposer()
    assert (
        p._rank_strategies(
            [], reflection_engine=None, epsilon=0.0, rng=random.Random(1)
        )
        == []
    )


def test_rank_strategies_zero_epsilon_is_deterministic(monkeypatch) -> None:
    monkeypatch.setattr(
        "optimizer.proposer.STRATEGY_TO_SURFACE",
        {
            "tighten_prompt": "api",
            "add_tool": "cli",
            "refactor": "db",
        },
    )
    reflection = _FakeReflection(
        {
            "api": _eff("api", 10, 0.20),
            "cli": _eff("cli", 5, 0.05),
            "db": _eff("db", 1, 0.01),
        }
    )
    p = Proposer()
    rng = random.Random(42)
    # With epsilon=0.0, every call returns the same exploitation order.
    first = p._rank_strategies(
        ["add_tool", "tighten_prompt", "refactor"],
        reflection_engine=reflection,
        epsilon=0.0,
        rng=rng,
    )
    for _ in range(20):
        next_ranking = p._rank_strategies(
            ["add_tool", "tighten_prompt", "refactor"],
            reflection_engine=reflection,
            epsilon=0.0,
            rng=rng,
        )
        assert next_ranking == first
