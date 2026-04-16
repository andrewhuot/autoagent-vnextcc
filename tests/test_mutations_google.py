"""Tests for LLM-driven prompt optimization operators."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from optimizer.mutations_google import (
    DataDrivenOptimizer,
    FewShotOptimizer,
    ZeroShotOptimizer,
    register_google_operators,
)
from optimizer.mutations import MutationRegistry


class MockLLMRouter:
    """Minimal mock LLM router for testing operator apply functions."""

    def __init__(self, response_text: str):
        self.response_text = response_text
        self.last_request = None

    def generate(self, request):
        self.last_request = request
        return SimpleNamespace(
            text=self.response_text,
            provider="mock",
            model="mock-test",
            prompt_tokens=100,
            completion_tokens=200,
            total_tokens=300,
            latency_ms=50.0,
        )


class FailingRouter:
    """Router that always raises an exception."""

    def generate(self, request):
        raise RuntimeError("Provider unavailable")


def _base_config() -> dict:
    return {
        "prompts": {
            "root": "You are a customer service agent.",
            "support": "You handle support queries.",
        },
        "routing": {
            "rules": [
                {"specialist": "support", "keywords": ["help", "issue"]},
            ],
        },
        "tools": {"faq": {"timeout_ms": 5000}},
    }


class TestZeroShotOptimizer:
    def test_operator_is_ready(self):
        op = ZeroShotOptimizer.create_operator()
        assert op.ready is True
        assert op.name == "llm_zero_shot_optimize"

    def test_apply_rewrites_prompt(self):
        improved = "You are an expert customer service agent. Always verify before responding."
        router = MockLLMRouter(json.dumps({"improved_prompt": improved}))

        config = _base_config()
        result = ZeroShotOptimizer._apply(config, {
            "llm_router": router,
            "target_prompt_key": "root",
            "failure_context": "Agent gives vague responses",
        })

        assert result["prompts"]["root"] == improved
        assert router.last_request is not None
        assert "zero_shot_prompt_optimize" in router.last_request.metadata.get("task", "")

    def test_apply_preserves_other_prompts(self):
        router = MockLLMRouter(json.dumps({"improved_prompt": "New root prompt"}))
        config = _base_config()
        result = ZeroShotOptimizer._apply(config, {"llm_router": router})
        assert result["prompts"]["support"] == "You handle support queries."

    def test_apply_no_router_returns_original(self):
        config = _base_config()
        result = ZeroShotOptimizer._apply(config, {})
        assert result is config

    def test_apply_handles_router_error(self):
        config = _base_config()
        result = ZeroShotOptimizer._apply(config, {"llm_router": FailingRouter()})
        assert result["prompts"]["root"] == config["prompts"]["root"]

    def test_apply_handles_invalid_json(self):
        router = MockLLMRouter("This is not JSON at all")
        config = _base_config()
        result = ZeroShotOptimizer._apply(config, {"llm_router": router})
        assert result["prompts"]["root"] == config["prompts"]["root"]

    def test_apply_empty_prompt_returns_original(self):
        router = MockLLMRouter(json.dumps({"improved_prompt": "Better"}))
        config = _base_config()
        config["prompts"]["root"] = ""
        result = ZeroShotOptimizer._apply(config, {"llm_router": router, "target_prompt_key": "root"})
        assert result is config


class TestFewShotOptimizer:
    def test_operator_is_ready(self):
        op = FewShotOptimizer.create_operator()
        assert op.ready is True
        assert op.name == "llm_few_shot_optimize"

    def test_apply_generates_examples(self):
        examples = [
            {"input": "Where is my order?", "output": "Let me look up your order..."},
            {"input": "I need help", "output": "I'd be happy to help. What issue..."},
        ]
        router = MockLLMRouter(json.dumps({"examples": examples}))

        config = _base_config()
        result = FewShotOptimizer._apply(config, {
            "llm_router": router,
            "target_specialist": "support",
            "failure_samples": [
                {"user_message": "My order is late", "error_message": "routing_error"},
            ],
        })

        assert "few_shot" in result
        assert "support" in result["few_shot"]
        assert len(result["few_shot"]["support"]) == 2

    def test_apply_respects_max_examples(self):
        examples = [{"input": f"q{i}", "output": f"a{i}"} for i in range(10)]
        router = MockLLMRouter(json.dumps({"examples": examples}))

        config = _base_config()
        result = FewShotOptimizer._apply(config, {
            "llm_router": router,
            "max_examples": 2,
        })

        assert len(result.get("few_shot", {}).get("root", [])) <= 2

    def test_apply_no_router_returns_original(self):
        config = _base_config()
        result = FewShotOptimizer._apply(config, {})
        assert result is config


class TestDataDrivenOptimizer:
    def test_operator_is_ready(self):
        op = DataDrivenOptimizer.create_operator()
        assert op.ready is True
        assert op.name == "llm_data_driven_optimize"

    def test_apply_merges_config_patch(self):
        patch = {
            "prompts": {"root": "Improved root prompt"},
            "thresholds": {"max_turns": 15},
        }
        router = MockLLMRouter(json.dumps({
            "config_patch": patch,
            "reasoning": "Reducing max_turns to prevent timeouts",
            "target_surface": "thresholds",
        }))

        config = _base_config()
        result = DataDrivenOptimizer._apply(config, {
            "llm_router": router,
            "eval_history": [{"score": 0.7}, {"score": 0.65}],
            "failure_trends": {"timeout": 5, "routing_error": 3},
        })

        assert result["prompts"]["root"] == "Improved root prompt"
        assert result["thresholds"]["max_turns"] == 15
        # Original tools should be preserved
        assert result["tools"]["faq"]["timeout_ms"] == 5000

    def test_apply_no_router_returns_original(self):
        config = _base_config()
        result = DataDrivenOptimizer._apply(config, {})
        assert result is config

    def test_apply_handles_error(self):
        config = _base_config()
        result = DataDrivenOptimizer._apply(config, {"llm_router": FailingRouter()})
        assert result["prompts"]["root"] == config["prompts"]["root"]


class TestRegistration:
    def test_register_all_operators(self):
        registry = MutationRegistry()
        register_google_operators(registry)

        ops = registry.list_all()
        names = [op.name for op in ops]
        assert "llm_zero_shot_optimize" in names
        assert "llm_few_shot_optimize" in names
        assert "llm_data_driven_optimize" in names

    def test_all_operators_are_ready(self):
        registry = MutationRegistry()
        register_google_operators(registry)

        for op in registry.list_all():
            assert op.ready is True, f"{op.name} should be ready"
