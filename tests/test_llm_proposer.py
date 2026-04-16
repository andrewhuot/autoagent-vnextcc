"""Tests for LLMProposer — structured LLM-driven proposal generation."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from optimizer.llm_proposer import (
    LLMProposer,
    ProposalCandidate,
    ProposalResult,
    _deep_merge,
)
from optimizer.proposer import Proposal
from optimizer.providers import LLMRequest


# ---------------------------------------------------------------------------
# Mock LLM router
# ---------------------------------------------------------------------------


class MockLLMRouter:
    """Deterministic mock that returns pre-configured text responses."""

    def __init__(self, response_text: str) -> None:
        self.response_text = response_text
        self.last_request: LLMRequest | None = None
        self.call_count: int = 0

    def generate(self, request: LLMRequest) -> SimpleNamespace:
        self.last_request = request
        self.call_count += 1
        return SimpleNamespace(
            text=self.response_text,
            model="mock-model",
            provider="mock",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            latency_ms=10.0,
            metadata={},
        )


class FailingLLMRouter:
    """Router that always raises."""

    def generate(self, request: LLMRequest) -> SimpleNamespace:
        raise RuntimeError("provider outage")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_BASE_CONFIG: dict = {
    "name": "customer_agent",
    "prompts": {
        "root": "You are a helpful customer service agent.",
        "support": "Handle support tickets with empathy.",
        "orders": "Process order inquiries accurately.",
    },
    "routing": {
        "rules": [
            {"specialist": "support", "keywords": ["help", "issue"]},
            {"specialist": "orders", "keywords": ["order", "track"]},
        ]
    },
    "tools": {
        "catalog": {"description": "Product catalog lookup", "timeout_ms": 5000},
        "orders_db": {"description": "Order database", "timeout_ms": 5000},
    },
}

_AGENT_CARD_MD = "# Agent: customer_agent\n\nA customer service agent."

_FAILURE_ANALYSIS: dict = {
    "clusters": [
        {
            "id": "C1",
            "count": 12,
            "summary": "Routing misclassifies support queries as orders",
            "recommended_surface": "routing",
        },
        {
            "id": "C2",
            "count": 5,
            "summary": "Tool timeouts during peak hours",
            "recommended_surface": "tool_description",
        },
    ],
    "surface_recommendations": {
        "routing": "Add more keywords to support rules",
        "tool_description": "Increase timeout for orders_db",
    },
    "summary": "Primary issue is routing misclassification (C1).",
}


def _valid_llm_response(
    *,
    mutation_type: str = "instruction",
    target_agent: str = "support",
    config_patch: dict | None = None,
    expected_impact: str = "high",
    risk_assessment: str = "low",
    confidence: float = 0.85,
) -> str:
    """Build a well-formed JSON response string."""
    if config_patch is None:
        config_patch = {
            "prompts": {
                "support": (
                    "Handle support tickets with empathy. "
                    "Always verify the customer's issue before escalating."
                )
            }
        }

    return json.dumps({
        "proposal": {
            "mutation_type": mutation_type,
            "target_agent": target_agent,
            "target_surface": mutation_type,
            "change_description": "Rewrite support instructions for clarity",
            "reasoning": "Cluster C1 shows 70% of routing errors stem from support",
            "config_patch": config_patch,
            "expected_impact": expected_impact,
            "risk_assessment": risk_assessment,
        },
        "analysis_summary": "The primary issue is routing misclassification.",
        "confidence": confidence,
        "alternative_proposals": [],
    })


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    """Valid LLM response produces a correct Proposal."""

    def test_returns_proposal_object(self) -> None:
        router = MockLLMRouter(_valid_llm_response())
        proposer = LLMProposer(llm_router=router)

        result = proposer.propose(
            current_config=_BASE_CONFIG,
            agent_card_markdown=_AGENT_CARD_MD,
            failure_analysis=_FAILURE_ANALYSIS,
        )

        assert result is not None
        assert isinstance(result, Proposal)
        assert result.config_section == "instruction"
        assert "support" in result.change_description.lower() or "rewrite" in result.change_description.lower()
        assert result.reasoning
        assert isinstance(result.new_config, dict)

    def test_config_patch_applied_via_deep_merge(self) -> None:
        new_prompt = "New support instructions here."
        router = MockLLMRouter(
            _valid_llm_response(config_patch={"prompts": {"support": new_prompt}})
        )
        proposer = LLMProposer(llm_router=router)

        result = proposer.propose(
            current_config=_BASE_CONFIG,
            agent_card_markdown=_AGENT_CARD_MD,
        )

        assert result is not None
        # Deep merge should have replaced the support prompt
        assert result.new_config["prompts"]["support"] == new_prompt
        # Root prompt should be preserved
        assert result.new_config["prompts"]["root"] == _BASE_CONFIG["prompts"]["root"]
        # Original config should not be mutated
        assert _BASE_CONFIG["prompts"]["support"] != new_prompt

    def test_routing_mutation_type(self) -> None:
        router = MockLLMRouter(
            _valid_llm_response(
                mutation_type="routing",
                target_agent="root",
                config_patch={
                    "routing": {
                        "rules": [
                            {"specialist": "support", "keywords": ["help", "issue", "problem"]},
                            {"specialist": "orders", "keywords": ["order", "track"]},
                        ]
                    }
                },
            )
        )
        proposer = LLMProposer(llm_router=router)

        result = proposer.propose(
            current_config=_BASE_CONFIG,
            agent_card_markdown=_AGENT_CARD_MD,
        )

        assert result is not None
        assert result.config_section == "routing"


# ---------------------------------------------------------------------------
# Prompt content verification
# ---------------------------------------------------------------------------


class TestPromptContent:
    """Verify that prompts sent to the LLM contain expected context."""

    def test_agent_card_included(self) -> None:
        router = MockLLMRouter(_valid_llm_response())
        proposer = LLMProposer(llm_router=router)

        proposer.propose(
            current_config=_BASE_CONFIG,
            agent_card_markdown=_AGENT_CARD_MD,
        )

        assert router.last_request is not None
        assert _AGENT_CARD_MD in router.last_request.prompt

    def test_failure_analysis_included(self) -> None:
        router = MockLLMRouter(_valid_llm_response())
        proposer = LLMProposer(llm_router=router)

        proposer.propose(
            current_config=_BASE_CONFIG,
            agent_card_markdown=_AGENT_CARD_MD,
            failure_analysis=_FAILURE_ANALYSIS,
        )

        prompt = router.last_request.prompt
        assert "C1" in prompt
        assert "routing" in prompt.lower()
        assert "Routing misclassifies" in prompt

    def test_past_attempts_included(self) -> None:
        past = [
            {
                "change_description": "Added routing keywords",
                "config_section": "routing",
                "outcome": "improved",
                "score_delta": 0.05,
            },
            {
                "change_description": "Increased tool timeout",
                "config_section": "tools",
                "outcome": "no_change",
                "score_delta": 0.0,
            },
        ]
        router = MockLLMRouter(_valid_llm_response())
        proposer = LLMProposer(llm_router=router)

        proposer.propose(
            current_config=_BASE_CONFIG,
            agent_card_markdown=_AGENT_CARD_MD,
            past_attempts=past,
        )

        prompt = router.last_request.prompt
        assert "Added routing keywords" in prompt
        assert "Increased tool timeout" in prompt
        assert "improved" in prompt

    def test_constraints_immutable_surfaces_in_prompt(self) -> None:
        router = MockLLMRouter(_valid_llm_response())
        proposer = LLMProposer(llm_router=router)

        proposer.propose(
            current_config=_BASE_CONFIG,
            agent_card_markdown=_AGENT_CARD_MD,
            constraints={"immutable_surfaces": ["model", "callback"]},
        )

        prompt = router.last_request.prompt
        assert "model" in prompt
        assert "callback" in prompt
        assert "Immutable" in prompt or "immutable" in prompt

    def test_objective_in_prompt(self) -> None:
        router = MockLLMRouter(_valid_llm_response())
        proposer = LLMProposer(llm_router=router)

        proposer.propose(
            current_config=_BASE_CONFIG,
            agent_card_markdown=_AGENT_CARD_MD,
            objective="Reduce routing errors by 50%",
        )

        prompt = router.last_request.prompt
        assert "Reduce routing errors by 50%" in prompt

    def test_available_mutations_in_prompt(self) -> None:
        router = MockLLMRouter(_valid_llm_response())
        proposer = LLMProposer(llm_router=router)

        proposer.propose(
            current_config=_BASE_CONFIG,
            agent_card_markdown=_AGENT_CARD_MD,
        )

        prompt = router.last_request.prompt
        # Should list mutation types
        assert "instruction" in prompt
        assert "routing" in prompt
        assert "generation_settings" in prompt

    def test_immutable_surfaces_excluded_from_mutations_list(self) -> None:
        router = MockLLMRouter(_valid_llm_response())
        proposer = LLMProposer(llm_router=router)

        proposer.propose(
            current_config=_BASE_CONFIG,
            agent_card_markdown=_AGENT_CARD_MD,
            constraints={"immutable_surfaces": ["model", "callback"]},
        )

        prompt = router.last_request.prompt
        # "model" should appear in the immutable section but NOT in
        # the available mutation types section (as a mutation entry).
        # We check that the mutations section doesn't contain a line like
        # "- **model**: ..." by looking at the available mutations list
        # that the proposer builds internally.
        mutations = proposer._available_mutations(
            {"immutable_surfaces": ["model", "callback"]}
        )
        mutation_types = {m["type"] for m in mutations}
        assert "model" not in mutation_types
        assert "callback" not in mutation_types
        # But other types should still be present
        assert "instruction" in mutation_types
        assert "routing" in mutation_types

    def test_system_prompt_content(self) -> None:
        router = MockLLMRouter(_valid_llm_response())
        proposer = LLMProposer(llm_router=router)

        proposer.propose(
            current_config=_BASE_CONFIG,
            agent_card_markdown=_AGENT_CARD_MD,
        )

        system = router.last_request.system
        assert "expert AI agent optimizer" in system
        assert "Instructions:" in system or "Instructions" in system
        assert "RULES:" in system
        assert "guardrails" in system.lower()


# ---------------------------------------------------------------------------
# Invalid / malformed responses
# ---------------------------------------------------------------------------


class TestInvalidResponses:
    """LLMProposer returns None for unparseable or invalid responses."""

    def test_garbage_text_returns_none(self) -> None:
        router = MockLLMRouter("This is not JSON at all! Just some random text.")
        proposer = LLMProposer(llm_router=router)

        result = proposer.propose(
            current_config=_BASE_CONFIG,
            agent_card_markdown=_AGENT_CARD_MD,
        )

        assert result is None

    def test_empty_response_returns_none(self) -> None:
        router = MockLLMRouter("")
        proposer = LLMProposer(llm_router=router)

        result = proposer.propose(
            current_config=_BASE_CONFIG,
            agent_card_markdown=_AGENT_CARD_MD,
        )

        assert result is None

    def test_missing_proposal_key_returns_none(self) -> None:
        router = MockLLMRouter(json.dumps({
            "analysis_summary": "something",
            "confidence": 0.5,
        }))
        proposer = LLMProposer(llm_router=router)

        result = proposer.propose(
            current_config=_BASE_CONFIG,
            agent_card_markdown=_AGENT_CARD_MD,
        )

        assert result is None

    def test_missing_required_fields_returns_none(self) -> None:
        # Proposal with no mutation_type
        router = MockLLMRouter(json.dumps({
            "proposal": {
                "target_agent": "root",
                "change_description": "do something",
                "config_patch": {},
            },
            "analysis_summary": "x",
            "confidence": 0.5,
        }))
        proposer = LLMProposer(llm_router=router)

        result = proposer.propose(
            current_config=_BASE_CONFIG,
            agent_card_markdown=_AGENT_CARD_MD,
        )

        # Empty mutation_type is not in _VALID_MUTATION_TYPES
        assert result is None

    def test_invalid_mutation_type_returns_none(self) -> None:
        router = MockLLMRouter(json.dumps({
            "proposal": {
                "mutation_type": "totally_invalid_surface",
                "target_agent": "root",
                "target_surface": "instruction",
                "change_description": "fix things",
                "reasoning": "because",
                "config_patch": {"prompts": {"root": "new text"}},
                "expected_impact": "high",
                "risk_assessment": "low",
            },
            "analysis_summary": "x",
            "confidence": 0.5,
        }))
        proposer = LLMProposer(llm_router=router)

        result = proposer.propose(
            current_config=_BASE_CONFIG,
            agent_card_markdown=_AGENT_CARD_MD,
        )

        assert result is None

    def test_config_patch_not_dict_returns_none(self) -> None:
        router = MockLLMRouter(json.dumps({
            "proposal": {
                "mutation_type": "instruction",
                "target_agent": "root",
                "target_surface": "instruction",
                "change_description": "rewrite prompt",
                "reasoning": "because",
                "config_patch": "this should be a dict",
                "expected_impact": "high",
                "risk_assessment": "low",
            },
            "analysis_summary": "x",
            "confidence": 0.5,
        }))
        proposer = LLMProposer(llm_router=router)

        result = proposer.propose(
            current_config=_BASE_CONFIG,
            agent_card_markdown=_AGENT_CARD_MD,
        )

        assert result is None

    def test_nonexistent_target_agent_returns_none(self) -> None:
        router = MockLLMRouter(
            _valid_llm_response(target_agent="hallucinated_agent")
        )
        proposer = LLMProposer(llm_router=router)

        result = proposer.propose(
            current_config=_BASE_CONFIG,
            agent_card_markdown=_AGENT_CARD_MD,
        )

        assert result is None

    def test_immutable_surface_violation_returns_none(self) -> None:
        router = MockLLMRouter(_valid_llm_response(mutation_type="model"))
        proposer = LLMProposer(llm_router=router)

        result = proposer.propose(
            current_config=_BASE_CONFIG,
            agent_card_markdown=_AGENT_CARD_MD,
            constraints={"immutable_surfaces": ["model"]},
        )

        assert result is None


# ---------------------------------------------------------------------------
# JSON parsing edge cases
# ---------------------------------------------------------------------------


class TestJSONParsing:
    """Robust parsing handles markdown fences, leading prose, etc."""

    def test_json_in_code_fences(self) -> None:
        fenced = "```json\n" + _valid_llm_response() + "\n```"
        router = MockLLMRouter(fenced)
        proposer = LLMProposer(llm_router=router)

        result = proposer.propose(
            current_config=_BASE_CONFIG,
            agent_card_markdown=_AGENT_CARD_MD,
        )

        assert result is not None
        assert isinstance(result, Proposal)

    def test_json_with_leading_prose(self) -> None:
        with_prose = "Sure! Here is my proposal:\n\n" + _valid_llm_response()
        router = MockLLMRouter(with_prose)
        proposer = LLMProposer(llm_router=router)

        result = proposer.propose(
            current_config=_BASE_CONFIG,
            agent_card_markdown=_AGENT_CARD_MD,
        )

        assert result is not None
        assert isinstance(result, Proposal)


# ---------------------------------------------------------------------------
# LLM errors
# ---------------------------------------------------------------------------


class TestLLMErrors:
    """LLMProposer gracefully handles provider failures."""

    def test_provider_exception_returns_none(self) -> None:
        router = FailingLLMRouter()
        proposer = LLMProposer(llm_router=router)

        result = proposer.propose(
            current_config=_BASE_CONFIG,
            agent_card_markdown=_AGENT_CARD_MD,
        )

        assert result is None


# ---------------------------------------------------------------------------
# Deep merge
# ---------------------------------------------------------------------------


class TestDeepMerge:
    """Config patch application via deep merge."""

    def test_simple_overwrite(self) -> None:
        base = {"a": 1, "b": 2}
        patch = {"b": 3, "c": 4}
        result = _deep_merge(base, patch)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self) -> None:
        base = {"prompts": {"root": "old", "support": "old support"}, "model": "gpt-4o"}
        patch = {"prompts": {"support": "new support"}}
        result = _deep_merge(base, patch)
        assert result["prompts"]["root"] == "old"
        assert result["prompts"]["support"] == "new support"
        assert result["model"] == "gpt-4o"

    def test_deep_nested_merge(self) -> None:
        base = {"a": {"b": {"c": 1, "d": 2}, "e": 3}}
        patch = {"a": {"b": {"c": 10, "f": 20}}}
        result = _deep_merge(base, patch)
        assert result == {"a": {"b": {"c": 10, "d": 2, "f": 20}, "e": 3}}

    def test_overwrite_non_dict_with_dict(self) -> None:
        base = {"a": "string_value"}
        patch = {"a": {"nested": "value"}}
        result = _deep_merge(base, patch)
        assert result == {"a": {"nested": "value"}}

    def test_empty_patch(self) -> None:
        base = {"a": 1}
        result = _deep_merge(base, {})
        assert result == {"a": 1}

    def test_original_not_mutated_in_propose(self) -> None:
        """Proposer should deepcopy before merging so the original is untouched."""
        original = {"prompts": {"root": "original text"}, "tools": {}}
        router = MockLLMRouter(
            _valid_llm_response(
                config_patch={"prompts": {"root": "changed text"}},
                target_agent="root",
            )
        )
        proposer = LLMProposer(llm_router=router)

        result = proposer.propose(
            current_config=original,
            agent_card_markdown=_AGENT_CARD_MD,
        )

        assert result is not None
        assert result.new_config["prompts"]["root"] == "changed text"
        assert original["prompts"]["root"] == "original text"


# ---------------------------------------------------------------------------
# Multi-surface awareness
# ---------------------------------------------------------------------------


class TestMultiSurface:
    """Verify that all agent surfaces are represented in prompts."""

    def test_prompt_mentions_all_major_surfaces(self) -> None:
        router = MockLLMRouter(_valid_llm_response())
        proposer = LLMProposer(llm_router=router)

        proposer.propose(
            current_config=_BASE_CONFIG,
            agent_card_markdown=_AGENT_CARD_MD,
        )

        system = router.last_request.system
        surfaces = [
            "Instructions",
            "Tools",
            "Callbacks",
            "Routing",
            "Guardrails",
            "Policies",
            "Generation Settings",
            "Model Selection",
        ]
        for surface in surfaces:
            assert surface in system, f"System prompt missing surface: {surface}"

    def test_all_mutation_types_available(self) -> None:
        """When there are no constraints, all mutation types should be listed."""
        proposer = LLMProposer(llm_router=MockLLMRouter(""))
        mutations = proposer._available_mutations(constraints=None)
        types = {m["type"] for m in mutations}

        from optimizer.mutations import MutationSurface

        for ms in MutationSurface:
            assert ms.value in types, f"Missing mutation type: {ms.value}"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Misc edge cases in proposal generation."""

    def test_no_failure_analysis(self) -> None:
        router = MockLLMRouter(_valid_llm_response())
        proposer = LLMProposer(llm_router=router)

        result = proposer.propose(
            current_config=_BASE_CONFIG,
            agent_card_markdown=_AGENT_CARD_MD,
            failure_analysis=None,
        )

        assert result is not None
        assert "No failure analysis" in router.last_request.prompt

    def test_no_past_attempts(self) -> None:
        router = MockLLMRouter(_valid_llm_response())
        proposer = LLMProposer(llm_router=router)

        result = proposer.propose(
            current_config=_BASE_CONFIG,
            agent_card_markdown=_AGENT_CARD_MD,
            past_attempts=None,
        )

        assert result is not None
        assert "No previous attempts" in router.last_request.prompt

    def test_empty_config_patch_still_works(self) -> None:
        """An empty config_patch {} is valid — it means no-op merge."""
        # Empty change_description should fail, but we need a non-empty one
        response = json.dumps({
            "proposal": {
                "mutation_type": "instruction",
                "target_agent": "root",
                "target_surface": "instruction",
                "change_description": "No-op proposal for observation",
                "reasoning": "Testing baseline",
                "config_patch": {},
                "expected_impact": "low",
                "risk_assessment": "low",
            },
            "analysis_summary": "baseline",
            "confidence": 0.1,
        })
        router = MockLLMRouter(response)
        proposer = LLMProposer(llm_router=router)

        result = proposer.propose(
            current_config=_BASE_CONFIG,
            agent_card_markdown=_AGENT_CARD_MD,
        )

        assert result is not None
        # Config should be unchanged
        assert result.new_config["prompts"]["root"] == _BASE_CONFIG["prompts"]["root"]

    def test_root_target_agent_always_valid(self) -> None:
        """'root' is always a valid target_agent regardless of the config."""
        router = MockLLMRouter(
            _valid_llm_response(target_agent="root")
        )
        proposer = LLMProposer(llm_router=router)

        result = proposer.propose(
            current_config={"prompts": {"root": "hello"}},
            agent_card_markdown=_AGENT_CARD_MD,
        )

        assert result is not None

    def test_impact_and_risk_normalized(self) -> None:
        """Invalid impact/risk strings should be normalized to 'medium'."""
        response = json.dumps({
            "proposal": {
                "mutation_type": "instruction",
                "target_agent": "root",
                "target_surface": "instruction",
                "change_description": "rewrite",
                "reasoning": "because",
                "config_patch": {"prompts": {"root": "new"}},
                "expected_impact": "very_high",
                "risk_assessment": "minimal",
            },
            "analysis_summary": "x",
            "confidence": 0.5,
        })
        router = MockLLMRouter(response)
        proposer = LLMProposer(llm_router=router)

        result = proposer.propose(
            current_config=_BASE_CONFIG,
            agent_card_markdown=_AGENT_CARD_MD,
        )

        # Should still succeed — invalid impact/risk get normalized
        assert result is not None
