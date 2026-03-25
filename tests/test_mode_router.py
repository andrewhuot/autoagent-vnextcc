"""Unit tests for optimizer.mode_router — ModeRouter, ModeConfig, legacy mapping."""

from __future__ import annotations

import pytest

from optimizer.mode_router import (
    AutonomyLevel,
    ModeConfig,
    ModeRouter,
    OptimizationMode,
    ResolvedStrategy,
    _LEGACY_STRATEGY_MAP,
    _MODE_STRATEGY_MAP,
)
from optimizer.search import BanditPolicy, SearchStrategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _router() -> ModeRouter:
    return ModeRouter()


def _config(mode: OptimizationMode = OptimizationMode.STANDARD, **kw) -> ModeConfig:
    return ModeConfig(mode=mode, **kw)


# ---------------------------------------------------------------------------
# resolve() tests
# ---------------------------------------------------------------------------


class TestResolve:
    def test_resolve_standard_mode(self):
        result = _router().resolve(_config(OptimizationMode.STANDARD))
        assert result.search_strategy == SearchStrategy.SIMPLE
        assert result.max_candidates == 3
        assert result.bandit_policy == BanditPolicy.THOMPSON

    def test_resolve_advanced_mode(self):
        result = _router().resolve(_config(OptimizationMode.ADVANCED))
        assert result.search_strategy == SearchStrategy.ADAPTIVE
        assert result.max_candidates == 10
        assert result.max_eval_budget == 5

    def test_resolve_research_mode(self):
        result = _router().resolve(_config(OptimizationMode.RESEARCH))
        assert result.search_strategy == SearchStrategy.FULL
        assert result.max_candidates == 20
        assert result.algorithm_overrides.get("enable_pareto") is True
        assert result.algorithm_overrides.get("enable_gepa") is True
        assert result.algorithm_overrides.get("enable_simba") is True
        assert result.bandit_policy == BanditPolicy.UCB


# ---------------------------------------------------------------------------
# from_legacy_strategy() tests
# ---------------------------------------------------------------------------


class TestFromLegacy:
    def test_from_legacy_simple(self):
        assert ModeRouter.from_legacy_strategy("simple") == OptimizationMode.STANDARD

    def test_from_legacy_adaptive(self):
        assert ModeRouter.from_legacy_strategy("adaptive") == OptimizationMode.ADVANCED

    def test_from_legacy_full(self):
        assert ModeRouter.from_legacy_strategy("full") == OptimizationMode.RESEARCH

    def test_from_legacy_pro(self):
        assert ModeRouter.from_legacy_strategy("pro") == OptimizationMode.RESEARCH

    def test_from_legacy_unknown(self):
        assert ModeRouter.from_legacy_strategy("nonexistent") == OptimizationMode.STANDARD


# ---------------------------------------------------------------------------
# parse_guardrails() tests
# ---------------------------------------------------------------------------


class TestParseGuardrails:
    def test_parse_guardrails_safety(self):
        result = ModeRouter.parse_guardrails(["Safety score must be 0.95"])
        assert len(result) == 1
        assert result[0]["metric"] == "safety_compliance"
        assert result[0]["direction"] == "gte"
        assert result[0]["threshold"] == 0.95

    def test_parse_guardrails_cost(self):
        result = ModeRouter.parse_guardrails(["Keep cost under $0.05"])
        assert result[0]["metric"] == "token_cost"
        assert result[0]["direction"] == "lte"
        assert result[0]["threshold"] == 0.05

    def test_parse_guardrails_latency(self):
        result = ModeRouter.parse_guardrails(["Latency under 200ms"])
        assert result[0]["metric"] == "latency_p95"
        assert result[0]["direction"] == "lte"
        assert result[0]["threshold"] == 200.0

    def test_parse_guardrails_empty(self):
        result = ModeRouter.parse_guardrails([])
        assert result == []

    def test_parse_guardrails_safety_no_threshold(self):
        result = ModeRouter.parse_guardrails(["No safety regressions"])
        assert result[0]["metric"] == "safety_compliance"
        assert result[0]["threshold"] == 1.0  # default


# ---------------------------------------------------------------------------
# migrate_config() tests
# ---------------------------------------------------------------------------


class TestMigrateConfig:
    def test_migrate_config_simple(self):
        old = {"optimizer": {"search_strategy": "simple"}}
        new = _router().migrate_config(old)
        assert new["optimization"]["mode"] == "standard"
        assert "allowed_surfaces" in new["optimization"]

    def test_migrate_config_adaptive(self):
        old = {
            "optimizer": {"search_strategy": "adaptive"},
            "budget": {"per_cycle_dollars": 2.5, "daily_dollars": 25.0},
        }
        new = _router().migrate_config(old)
        assert new["optimization"]["mode"] == "advanced"
        assert new["optimization"]["budget"]["per_cycle"] == 2.5
        assert new["optimization"]["budget"]["daily"] == 25.0


# ---------------------------------------------------------------------------
# ModeConfig defaults
# ---------------------------------------------------------------------------


class TestModeConfigDefaults:
    def test_mode_config_defaults(self):
        cfg = ModeConfig()
        assert cfg.mode == OptimizationMode.STANDARD
        assert cfg.objective == ""
        assert cfg.guardrails == []
        assert cfg.budget_per_cycle == 1.0
        assert cfg.budget_daily == 10.0
        assert cfg.autonomy == AutonomyLevel.SUPERVISED
        assert "instructions" in cfg.allowed_surfaces
