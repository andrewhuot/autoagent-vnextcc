"""Integration tests for the real optimization loop.

Tests the full pipeline: Agent Card → Failure Analysis → LLM Proposal →
Reflection, verifying that all components work together.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from agent_card.converter import from_config_dict, to_config_dict
from agent_card.renderer import render_to_markdown, parse_from_markdown
from agent_card.schema import AgentCardModel
from optimizer.failure_analyzer import FailureAnalyzer, FailureAnalysis
from optimizer.llm_proposer import LLMProposer
from optimizer.proposer import Proposal, Proposer
from optimizer.reflection import ReflectionEngine


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class MockLLMRouter:
    """Mock LLM router that returns configurable responses."""

    def __init__(self, responses: list[str] | None = None):
        self._responses = list(responses or [])
        self._call_index = 0
        self.calls: list[Any] = []
        self.mock_mode = False
        self.mock_reason = ""

    def generate(self, request):
        self.calls.append(request)
        if self._call_index < len(self._responses):
            text = self._responses[self._call_index]
            self._call_index += 1
        else:
            text = json.dumps({"error": "no more mock responses"})
        return SimpleNamespace(
            text=text,
            provider="mock",
            model="mock-test",
            prompt_tokens=100,
            completion_tokens=200,
            total_tokens=300,
            latency_ms=50.0,
        )


def _test_config() -> dict:
    """A realistic agent config for testing."""
    return {
        "name": "customer_service",
        "description": "Multi-agent customer service system",
        "model": "gemini-2.0-flash",
        "prompts": {
            "root": "You are a customer service orchestrator. Route queries to the appropriate specialist.",
            "support": "You are a support specialist. Help users resolve their issues.",
            "orders": "You are an orders specialist. Help with order tracking and returns.",
        },
        "routing": {
            "rules": [
                {"specialist": "support", "keywords": ["help", "issue", "problem", "error"]},
                {"specialist": "orders", "keywords": ["order", "shipping", "track", "delivery"]},
            ],
        },
        "tools": {
            "faq": {"description": "FAQ lookup", "timeout_ms": 5000},
            "orders_db": {"description": "Orders database", "timeout_ms": 3000},
        },
        "thresholds": {"max_turns": 20, "confidence_threshold": 0.6},
        "generation": {"temperature": 0.3, "max_tokens": 2048},
    }


def _test_failure_samples() -> list[dict]:
    return [
        {
            "id": "sample-1",
            "user_message": "I want to return my order",
            "expected_specialist": "orders",
            "actual_specialist": "support",
            "error_message": "Routing error: expected=orders got=support",
            "failure_type": "routing_error",
        },
        {
            "id": "sample-2",
            "user_message": "Where is my package?",
            "expected_specialist": "orders",
            "actual_specialist": "support",
            "error_message": "Routing error: expected=orders got=support",
            "failure_type": "routing_error",
        },
        {
            "id": "sample-3",
            "user_message": "The product broke after one day",
            "expected_specialist": "support",
            "actual_specialist": "support",
            "error_message": "Response too short",
            "failure_type": "unhelpful_response",
        },
    ]


# ---------------------------------------------------------------------------
# Agent Card integration
# ---------------------------------------------------------------------------


class TestAgentCardIntegration:
    """Agent Card correctly captures the full config and round-trips."""

    def test_config_to_card_preserves_hierarchy(self):
        config = _test_config()
        card = from_config_dict(config, name="customer_service")

        assert card.name == "customer_service"
        assert "orchestrator" in card.instructions
        assert len(card.sub_agents) == 2
        assert len(card.routing_rules) == 2
        assert len(card.tools) == 2

    def test_card_to_markdown_to_card(self):
        config = _test_config()
        card = from_config_dict(config, name="customer_service")
        md = render_to_markdown(card)

        # Verify markdown contains key sections
        assert "# Agent Card: customer_service" in md
        assert "## Routing Rules" in md
        assert "## Tools" in md
        assert "## Sub-Agents" in md

        # Round-trip
        parsed = parse_from_markdown(md)
        assert parsed.name == card.name
        assert len(parsed.routing_rules) == len(card.routing_rules)
        assert len(parsed.sub_agents) == len(card.sub_agents)

    def test_card_to_config_preserves_prompts(self):
        config = _test_config()
        card = from_config_dict(config, name="customer_service")
        recovered = to_config_dict(card)

        assert recovered["prompts"]["root"] == config["prompts"]["root"]
        assert recovered["prompts"]["support"] == config["prompts"]["support"]
        assert recovered["prompts"]["orders"] == config["prompts"]["orders"]


# ---------------------------------------------------------------------------
# Failure Analyzer integration
# ---------------------------------------------------------------------------


class TestFailureAnalyzerIntegration:
    """Failure analyzer correctly processes eval results."""

    def test_deterministic_analysis(self):
        config = _test_config()
        card = from_config_dict(config, name="customer_service")
        md = render_to_markdown(card)

        analyzer = FailureAnalyzer()
        analysis = analyzer.analyze(
            eval_results={
                "failure_buckets": {
                    "routing_error": 5,
                    "unhelpful_response": 2,
                    "timeout": 0,
                },
                "failure_samples": _test_failure_samples(),
            },
            agent_card_markdown=md,
        )

        assert len(analysis.clusters) >= 2  # routing_error + unhelpful_response
        assert analysis.clusters[0].count >= analysis.clusters[1].count  # sorted by count
        assert len(analysis.surface_recommendations) >= 2
        assert analysis.summary  # non-empty summary

    def test_llm_analysis_with_mock(self):
        llm_response = json.dumps({
            "clusters": [
                {
                    "cluster_id": "C1",
                    "description": "Order-related queries misrouted to support",
                    "root_cause_hypothesis": "Missing routing keywords for returns/packages",
                    "failure_type": "routing_error",
                    "sample_ids": ["sample-1", "sample-2"],
                    "affected_agent": "root",
                    "severity": 0.8,
                    "count": 5,
                },
            ],
            "surface_recommendations": [
                {
                    "surface": "routing",
                    "agent_path": "root",
                    "confidence": 0.9,
                    "reasoning": "Add return/package keywords to orders routing",
                    "suggested_approach": "Expand orders specialist keywords",
                    "priority": 1,
                },
            ],
            "severity_ranking": ["C1"],
            "cross_cutting_patterns": [],
            "summary": "Primary issue is routing coverage for order-related queries.",
        })

        router = MockLLMRouter([llm_response])
        analyzer = FailureAnalyzer(llm_router=router)

        analysis = analyzer.analyze(
            eval_results={
                "failure_buckets": {"routing_error": 5},
                "failure_samples": _test_failure_samples(),
            },
            agent_card_markdown="# Test Agent",
        )

        assert len(analysis.clusters) >= 1
        assert len(router.calls) == 1  # LLM was called


# ---------------------------------------------------------------------------
# LLM Proposer integration
# ---------------------------------------------------------------------------


class TestLLMProposerIntegration:
    """LLM proposer generates valid proposals from config + failures."""

    def test_proposal_from_mock_llm(self):
        config = _test_config()
        card = from_config_dict(config, name="customer_service")
        md = render_to_markdown(card)

        proposal_response = json.dumps({
            "proposal": {
                "mutation_type": "routing",
                "target_agent": "root",
                "target_surface": "routing",
                "change_description": "Add return/package keywords to orders routing rule",
                "reasoning": "5 routing errors show order-related queries going to support instead of orders",
                "config_patch": {
                    "routing": {
                        "rules": [
                            {"specialist": "support", "keywords": ["help", "issue", "problem", "error"]},
                            {"specialist": "orders", "keywords": ["order", "shipping", "track", "delivery", "return", "package"]},
                        ],
                    },
                },
                "expected_impact": "high",
                "risk_assessment": "low",
            },
            "analysis_summary": "Routing keyword gap for order-related queries",
            "confidence": 0.85,
        })

        router = MockLLMRouter([proposal_response])
        proposer = LLMProposer(llm_router=router)

        proposal = proposer.propose(
            current_config=config,
            agent_card_markdown=md,
            failure_analysis={
                "clusters": [{"id": "C1", "count": 5, "summary": "Routing errors"}],
                "summary": "Routing issues dominate",
            },
        )

        assert proposal is not None
        assert isinstance(proposal, Proposal)
        assert "routing" in proposal.config_section or "routing" in proposal.change_description.lower()
        # Verify the new config has the expanded keywords
        assert "return" in str(proposal.new_config.get("routing", {}))

    def test_proposal_preserves_original_config(self):
        config = _test_config()
        original = copy.deepcopy(config)
        card = from_config_dict(config, name="customer_service")
        md = render_to_markdown(card)

        proposal_response = json.dumps({
            "proposal": {
                "mutation_type": "instruction",
                "target_agent": "root",
                "target_surface": "instruction",
                "change_description": "Improve root instructions",
                "reasoning": "Test",
                "config_patch": {"prompts": {"root": "New prompt"}},
                "expected_impact": "medium",
                "risk_assessment": "low",
            },
            "analysis_summary": "Test",
            "confidence": 0.7,
        })

        router = MockLLMRouter([proposal_response])
        proposer = LLMProposer(llm_router=router)
        proposer.propose(current_config=config, agent_card_markdown=md)

        # Original config should not be mutated
        assert config == original


# ---------------------------------------------------------------------------
# Reflection integration
# ---------------------------------------------------------------------------


class TestReflectionIntegration:
    """Reflection engine correctly processes optimization outcomes."""

    def test_deterministic_reflection_on_success(self, tmp_path):
        engine = ReflectionEngine(db_path=str(tmp_path / "reflections.db"))

        reflection = engine.reflect(
            attempt={
                "attempt_id": "test-001",
                "status": "accepted",
                "change_description": "Added routing keywords",
                "config_section": "routing",
                "score_before": 0.65,
                "score_after": 0.78,
            },
        )

        assert reflection.outcome == "accepted"
        assert reflection.score_delta > 0
        assert len(reflection.what_worked) > 0

    def test_reflection_context_for_next_cycle(self, tmp_path):
        engine = ReflectionEngine(db_path=str(tmp_path / "reflections.db"))

        # Generate a few reflections
        for i in range(3):
            engine.reflect(attempt={
                "attempt_id": f"test-{i:03d}",
                "status": "accepted" if i % 2 == 0 else "rejected_not_significant",
                "change_description": f"Change {i}",
                "config_section": "routing" if i % 2 == 0 else "instruction",
                "score_before": 0.6,
                "score_after": 0.7 if i % 2 == 0 else 0.59,
            })

        ctx = engine.get_context_for_next_cycle()
        assert "recent_reflections" in ctx
        assert "surface_effectiveness" in ctx
        assert len(ctx["recent_reflections"]) > 0


# ---------------------------------------------------------------------------
# Full pipeline: Config → Card → Analyze → Propose → Reflect
# ---------------------------------------------------------------------------


class TestFullPipeline:
    """End-to-end test of the complete optimization pipeline."""

    def test_config_to_proposal_pipeline(self, tmp_path):
        config = _test_config()

        # 1. Build Agent Card
        card = from_config_dict(config, name="customer_service")
        md = render_to_markdown(card)
        assert "customer_service" in md

        # 2. Analyze failures (deterministic)
        analyzer = FailureAnalyzer()
        analysis = analyzer.analyze(
            eval_results={
                "failure_buckets": {"routing_error": 5, "unhelpful_response": 2},
                "failure_samples": _test_failure_samples(),
            },
            agent_card_markdown=md,
        )
        assert len(analysis.clusters) >= 2

        # 3. Generate proposal (mock LLM)
        proposal_response = json.dumps({
            "proposal": {
                "mutation_type": "routing",
                "target_agent": "root",
                "target_surface": "routing",
                "change_description": "Expand orders routing keywords",
                "reasoning": "Routing error cluster shows missing keywords",
                "config_patch": {
                    "routing": {
                        "rules": [
                            {"specialist": "support", "keywords": ["help", "issue", "problem"]},
                            {"specialist": "orders", "keywords": ["order", "shipping", "track", "return", "package"]},
                        ],
                    },
                },
                "expected_impact": "high",
                "risk_assessment": "low",
            },
            "analysis_summary": "Routing gaps",
            "confidence": 0.9,
        })

        router = MockLLMRouter([proposal_response])
        proposer = LLMProposer(llm_router=router)
        proposal = proposer.propose(
            current_config=config,
            agent_card_markdown=md,
            failure_analysis={
                "clusters": [
                    {"id": c.cluster_id, "count": c.count, "summary": c.description}
                    for c in analysis.clusters
                ],
                "summary": analysis.summary,
            },
        )
        assert proposal is not None

        # 4. Apply proposal and verify
        new_config = proposal.new_config
        assert "return" in str(new_config.get("routing", {}))

        # 5. Reflect on the outcome
        engine = ReflectionEngine(db_path=str(tmp_path / "reflections.db"))
        reflection = engine.reflect(
            attempt={
                "attempt_id": "pipeline-001",
                "status": "accepted",
                "change_description": proposal.change_description,
                "config_section": proposal.config_section,
                "score_before": 0.65,
                "score_after": 0.78,
            },
            proposal_reasoning=proposal.reasoning,
            agent_card_markdown=md,
        )
        assert reflection.score_delta > 0
        assert len(reflection.what_worked) > 0

        # 6. Verify reflection context feeds next cycle
        ctx = engine.get_context_for_next_cycle()
        assert len(ctx["recent_reflections"]) > 0

    def test_proposer_with_integrated_analyzer(self):
        """Test the Proposer class with use_mock=False and mock LLM."""
        config = _test_config()

        # Create responses for: failure analysis LLM call, then proposal LLM call
        analyzer_response = json.dumps({
            "clusters": [
                {
                    "cluster_id": "C1",
                    "description": "Routing failures",
                    "root_cause_hypothesis": "Missing keywords",
                    "failure_type": "routing_error",
                    "sample_ids": ["s1"],
                    "severity": 0.8,
                    "count": 5,
                },
            ],
            "surface_recommendations": [
                {
                    "surface": "routing",
                    "agent_path": "root",
                    "confidence": 0.9,
                    "reasoning": "Expand keywords",
                    "suggested_approach": "Add terms",
                    "priority": 1,
                },
            ],
            "severity_ranking": ["C1"],
            "cross_cutting_patterns": [],
            "summary": "Routing is the primary issue",
        })

        proposal_response = json.dumps({
            "proposal": {
                "mutation_type": "routing",
                "target_agent": "root",
                "target_surface": "routing",
                "change_description": "Expand routing keywords",
                "reasoning": "Add missing keywords",
                "config_patch": {
                    "routing": {
                        "rules": [
                            {"specialist": "orders", "keywords": ["order", "return"]},
                        ],
                    },
                },
                "expected_impact": "high",
                "risk_assessment": "low",
            },
            "analysis_summary": "Fix routing",
            "confidence": 0.85,
        })

        router = MockLLMRouter([analyzer_response, proposal_response])
        proposer = Proposer(use_mock=False, llm_router=router)

        proposal = proposer.propose(
            current_config=config,
            health_metrics={"quality": 0.65},
            failure_samples=_test_failure_samples(),
            failure_buckets={"routing_error": 5, "unhelpful_response": 2},
            past_attempts=[],
        )

        assert proposal is not None
        assert isinstance(proposal, Proposal)
        # LLM was called (analyzer + proposer)
        assert len(router.calls) >= 1

    def test_proposer_falls_back_to_mock_on_error(self):
        """When LLM fails, Proposer falls back to deterministic mock."""
        config = _test_config()

        class FailingRouter:
            mock_mode = False
            mock_reason = ""
            def generate(self, request):
                raise RuntimeError("LLM unavailable")

        proposer = Proposer(use_mock=False, llm_router=FailingRouter())

        proposal = proposer.propose(
            current_config=config,
            health_metrics={"quality": 0.65},
            failure_samples=_test_failure_samples(),
            failure_buckets={"routing_error": 5},
            past_attempts=[],
        )

        # Should fall back to mock and still return a proposal
        assert proposal is not None
        assert isinstance(proposal, Proposal)


# ---------------------------------------------------------------------------
# Multi-agent awareness
# ---------------------------------------------------------------------------


class TestMultiAgentAwareness:
    """Verify the system handles multi-agent hierarchies correctly."""

    def test_sub_agents_in_card(self):
        config = _test_config()
        card = from_config_dict(config, name="customer_service")

        # Both specialists should appear as sub-agents
        sa_names = [sa.name for sa in card.sub_agents]
        assert "support" in sa_names
        assert "orders" in sa_names

        # Each should have their instructions
        support = card.find_sub_agent("support")
        assert support is not None
        assert "support specialist" in support.instructions.lower()

    def test_proposal_can_target_sub_agent(self):
        config = _test_config()
        card = from_config_dict(config, name="customer_service")
        md = render_to_markdown(card)

        # LLM proposes changing the support agent's instructions
        proposal_response = json.dumps({
            "proposal": {
                "mutation_type": "instruction",
                "target_agent": "support",
                "target_surface": "instruction",
                "change_description": "Improve support agent instructions",
                "reasoning": "Support gives unhelpful responses",
                "config_patch": {
                    "prompts": {
                        "support": "You are an expert support specialist. Always provide detailed, actionable help."
                    }
                },
                "expected_impact": "medium",
                "risk_assessment": "low",
            },
            "analysis_summary": "Support quality",
            "confidence": 0.8,
        })

        router = MockLLMRouter([proposal_response])
        proposer = LLMProposer(llm_router=router)
        proposal = proposer.propose(
            current_config=config,
            agent_card_markdown=md,
        )

        assert proposal is not None
        assert "support" in proposal.new_config.get("prompts", {})
        # Root prompt should be preserved
        assert "orchestrator" in proposal.new_config["prompts"]["root"]
