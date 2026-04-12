"""Tests for eval failure attribution to canonical components."""

from __future__ import annotations

from evals.results_model import EvalResultSet
from evals.runner import EvalRunner, TestCase


def test_eval_failures_include_component_attributions() -> None:
    """Failures should point to concrete graph components instead of only buckets."""

    def failing_agent(user_message: str, config: dict | None = None) -> dict:
        return {
            "response": "No.",
            "specialist_used": "orders",
            "tool_calls": [],
            "safety_violation": True,
            "latency_ms": 12,
            "token_count": 7,
        }

    config = {
        "prompts": {"root": "Route users to the right specialist."},
        "routing": {"rules": [{"specialist": "support", "keywords": ["help"], "patterns": []}]},
        "tools_config": {"faq": {"description": "Look up FAQ answers.", "parameters": []}},
        "guardrails": [
            {
                "name": "harm_guard",
                "type": "both",
                "enforcement": "block",
                "description": "Block harmful requests.",
            }
        ],
    }
    case = TestCase(
        id="case_component_credit",
        category="regression",
        user_message="I need help with an unsafe account action.",
        expected_specialist="support",
        expected_behavior="answer",
        expected_tool="faq",
    )
    runner = EvalRunner(agent_fn=failing_agent, cache_enabled=False)

    result = runner.evaluate_case(case, config)

    component_types = {
        attribution["component"]["component_type"]
        for attribution in result.component_attributions
    }
    assert "routing_rule" in component_types
    assert "tool_contract" in component_types
    assert "guardrail" in component_types
    assert any(
        attribution["failure_reason"] == "routing mismatch"
        and attribution["component"]["name"] == "support"
        for attribution in result.component_attributions
    )


def test_structured_eval_results_preserve_component_attributions() -> None:
    """Component credit assignment should survive the structured result projection."""

    def failing_agent(user_message: str, config: dict | None = None) -> dict:
        return {
            "response": "No.",
            "specialist_used": "orders",
            "tool_calls": [],
            "latency_ms": 5,
            "token_count": 3,
        }

    config = {
        "routing": {"rules": [{"specialist": "support", "keywords": ["help"], "patterns": []}]},
    }
    case = TestCase(
        id="case_structured_credit",
        category="routing",
        user_message="Help me with billing.",
        expected_specialist="support",
        expected_behavior="route_correctly",
    )
    runner = EvalRunner(agent_fn=failing_agent, cache_enabled=False)

    score = runner.run_cases([case], config=config)
    result_set = EvalResultSet.from_score(
        run_id="run-credit",
        score=score,
        cases=[case],
        mode="mock",
        config_snapshot=config,
    )

    example = result_set.examples[0]
    assert example.component_attributions
    assert example.component_attributions[0]["component"]["component_type"] == "routing_rule"
