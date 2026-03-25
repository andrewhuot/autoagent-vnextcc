"""Unit tests for optimizer.model_routing — PhaseRouter, ModelSpec, PhaseRoutingConfig."""

from __future__ import annotations

import pytest

from optimizer.model_routing import (
    ModelSpec,
    OptimizationPhase,
    PhaseRouter,
    PhaseRoutingConfig,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _spec(provider: str = "openai", model: str = "gpt-4o", **kw) -> ModelSpec:
    return ModelSpec(provider=provider, model=model, **kw)


def _config(**kw) -> PhaseRoutingConfig:
    return PhaseRoutingConfig(**kw)


# ---------------------------------------------------------------------------
# select_model() tests
# ---------------------------------------------------------------------------


class TestSelectModel:
    def test_select_model_diagnosis(self):
        cfg = _config(diagnosis_models=[_spec("anthropic", "claude-opus")])
        router = PhaseRouter(cfg)
        result = router.select_model(OptimizationPhase.DIAGNOSIS)
        assert result is not None
        assert result.provider == "anthropic"
        assert result.model == "claude-opus"

    def test_select_model_search(self):
        cfg = _config(search_models=[_spec("openai", "gpt-4o-mini")])
        router = PhaseRouter(cfg)
        result = router.select_model(OptimizationPhase.SEARCH)
        assert result is not None
        assert result.model == "gpt-4o-mini"

    def test_select_model_evaluation(self):
        cfg = _config(
            evaluation_models=[_spec("openai", "gpt-4o", pinned_version="gpt-4o-2024-05-13")]
        )
        router = PhaseRouter(cfg)
        result = router.select_model(OptimizationPhase.EVALUATION)
        assert result is not None
        assert result.pinned_version == "gpt-4o-2024-05-13"

    def test_select_model_fallback_to_default(self):
        default = _spec("fallback", "fallback-model")
        cfg = _config(default_model=default)
        router = PhaseRouter(cfg)
        result = router.select_model(OptimizationPhase.DIAGNOSIS)
        assert result is not None
        assert result.provider == "fallback"

    def test_select_model_no_config(self):
        router = PhaseRouter()
        result = router.select_model(OptimizationPhase.DIAGNOSIS)
        assert result is None

    def test_multiple_models_per_phase(self):
        models = [_spec("a", "model-a"), _spec("b", "model-b")]
        cfg = _config(diagnosis_models=models)
        router = PhaseRouter(cfg)
        result = router.select_model(OptimizationPhase.DIAGNOSIS)
        assert result is not None
        assert result.provider == "a"  # first model selected


# ---------------------------------------------------------------------------
# Phase preferences
# ---------------------------------------------------------------------------


class TestPhasePreferences:
    def test_phase_preferences(self):
        router = PhaseRouter()
        diag = router.get_phase_preference(OptimizationPhase.DIAGNOSIS)
        assert diag["prefer"] == "reasoning"
        assert diag["tier"] == "high"

        search = router.get_phase_preference(OptimizationPhase.SEARCH)
        assert search["prefer"] == "fast"

        ev = router.get_phase_preference(OptimizationPhase.EVALUATION)
        assert ev["prefer"] == "pinned"


# ---------------------------------------------------------------------------
# Eval model pin
# ---------------------------------------------------------------------------


class TestEvalModelPin:
    def test_eval_model_pin(self):
        cfg = _config(
            evaluation_models=[_spec("openai", "gpt-4o", pinned_version="v20240513")]
        )
        router = PhaseRouter(cfg)
        assert router.get_eval_model_pin() == "v20240513"

    def test_eval_model_pin_none(self):
        router = PhaseRouter()
        assert router.get_eval_model_pin() is None


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_to_dict(self):
        cfg = _config(
            diagnosis_models=[_spec("a", "m1")],
            search_models=[_spec("b", "m2")],
            evaluation_models=[_spec("c", "m3", pinned_version="v1")],
        )
        router = PhaseRouter(cfg)
        d = router.to_dict()
        assert len(d["diagnosis"]) == 1
        assert d["diagnosis"][0]["provider"] == "a"
        assert len(d["search"]) == 1
        assert d["evaluation"][0]["pinned"] == "v1"

    def test_model_spec_key(self):
        spec = _spec("openai", "gpt-4o")
        assert spec.key == "openai/gpt-4o"

    def test_default_phase_routing_config(self):
        cfg = PhaseRoutingConfig()
        assert cfg.diagnosis_models == []
        assert cfg.search_models == []
        assert cfg.evaluation_models == []
        assert cfg.default_model is None
