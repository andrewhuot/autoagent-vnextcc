"""Tests for simulation sandbox and synthetic conversation generation."""

from __future__ import annotations

import pytest

from simulator.persona import PERSONAS, get_persona_by_name, get_personas_by_difficulty
from simulator.sandbox import SimulationSandbox, SyntheticConversation


class TestPersonas:
    """Test persona definitions and lookups."""

    def test_personas_exist(self):
        """Verify all expected personas are defined."""
        assert len(PERSONAS) >= 5
        persona_names = [p.name for p in PERSONAS]
        assert "angry_customer" in persona_names
        assert "confused_customer" in persona_names
        assert "technical_user" in persona_names

    def test_get_persona_by_name(self):
        """Test persona lookup by name."""
        persona = get_persona_by_name("angry_customer")
        assert persona is not None
        assert persona.name == "angry_customer"
        assert len(persona.traits) > 0

    def test_get_persona_by_name_not_found(self):
        """Test persona lookup with invalid name."""
        persona = get_persona_by_name("nonexistent_persona")
        assert persona is None

    def test_get_personas_by_difficulty_normal(self):
        """Test getting personas for normal difficulty."""
        personas = get_personas_by_difficulty("normal")
        assert len(personas) > 0
        assert all(p.name in ["polite_customer", "brief_customer", "technical_user"] for p in personas)

    def test_get_personas_by_difficulty_edge_case(self):
        """Test getting personas for edge case difficulty."""
        personas = get_personas_by_difficulty("edge_case")
        assert len(personas) > 0
        assert any(p.name == "confused_customer" for p in personas)

    def test_get_personas_by_difficulty_adversarial(self):
        """Test getting personas for adversarial difficulty."""
        personas = get_personas_by_difficulty("adversarial")
        assert len(personas) > 0
        assert any(p.name == "angry_customer" for p in personas)


class TestSyntheticConversation:
    """Test synthetic conversation generation."""

    def test_synthetic_conversation_creation(self):
        """Test creating a synthetic conversation."""
        conv = SyntheticConversation(
            conversation_id="test-001",
            domain="customer-support",
            difficulty="normal",
            persona="polite_customer",
            user_message="I need help with my order",
            expected_intent="order_status",
            expected_specialist="orders",
            expected_tools=["query_orders"],
        )
        assert conv.conversation_id == "test-001"
        assert conv.difficulty == "normal"
        assert conv.expected_intent == "order_status"


class TestSimulationSandbox:
    """Test simulation sandbox functionality."""

    def test_sandbox_initialization(self):
        """Test sandbox initialization with default values."""
        sandbox = SimulationSandbox()
        assert sandbox.intents is not None
        assert len(sandbox.intents) > 0
        assert sandbox.tools is not None
        assert len(sandbox.tools) > 0

    def test_sandbox_initialization_with_custom_intents(self):
        """Test sandbox initialization with custom intents and tools."""
        custom_intents = ["billing", "support", "sales"]
        custom_tools = ["tool_a", "tool_b"]
        sandbox = SimulationSandbox(intents=custom_intents, tools=custom_tools)
        assert sandbox.intents == custom_intents
        assert sandbox.tools == custom_tools

    def test_generate_conversations_basic(self):
        """Test basic conversation generation."""
        sandbox = SimulationSandbox()
        conversations = sandbox.generate_conversations(
            domain="customer-support",
            count=10,
        )
        assert len(conversations) == 10
        assert all(isinstance(conv, SyntheticConversation) for conv in conversations)

    def test_generate_conversations_respects_distribution(self):
        """Test that generated conversations respect difficulty distribution."""
        sandbox = SimulationSandbox()
        distribution = {"normal": 0.5, "edge_case": 0.3, "adversarial": 0.2}
        conversations = sandbox.generate_conversations(
            domain="customer-support",
            count=100,
            difficulty_distribution=distribution,
        )

        # Count by difficulty
        difficulty_counts = {"normal": 0, "edge_case": 0, "adversarial": 0}
        for conv in conversations:
            difficulty_counts[conv.difficulty] += 1

        # Check approximate distribution (allow 10% variance)
        assert difficulty_counts["normal"] >= 40  # 50% of 100 = 50, allow ±10
        assert difficulty_counts["edge_case"] >= 20  # 30% of 100 = 30, allow ±10
        assert difficulty_counts["adversarial"] >= 10  # 20% of 100 = 20, allow ±10

    def test_generate_conversations_has_unique_ids(self):
        """Test that all generated conversations have unique IDs."""
        sandbox = SimulationSandbox()
        conversations = sandbox.generate_conversations(
            domain="customer-support",
            count=50,
        )
        conversation_ids = [conv.conversation_id for conv in conversations]
        assert len(conversation_ids) == len(set(conversation_ids))

    def test_generate_conversations_includes_expected_fields(self):
        """Test that generated conversations include all expected fields."""
        sandbox = SimulationSandbox()
        conversations = sandbox.generate_conversations(
            domain="customer-support",
            count=5,
        )
        for conv in conversations:
            assert conv.conversation_id
            assert conv.domain == "customer-support"
            assert conv.difficulty in ["normal", "edge_case", "adversarial"]
            assert conv.persona
            assert conv.user_message
            assert conv.expected_intent
            assert conv.expected_specialist
            assert isinstance(conv.expected_tools, list)

    def test_stress_test_basic(self):
        """Test basic stress test functionality."""
        sandbox = SimulationSandbox()
        conversations = sandbox.generate_conversations(
            domain="customer-support",
            count=20,
        )
        result = sandbox.stress_test(
            config={"test": "config"},
            conversations=conversations,
            config_id="test-001",
        )

        assert result.test_id.startswith("stress-")
        assert result.config_id == "test-001"
        assert result.total_conversations == 20
        assert result.passed + result.failed == 20
        assert 0.0 <= result.pass_rate <= 1.0
        assert result.avg_latency_ms >= 0

    def test_stress_test_tracks_failures_by_category(self):
        """Test that stress test tracks failures by difficulty category."""
        sandbox = SimulationSandbox()
        conversations = sandbox.generate_conversations(
            domain="customer-support",
            count=30,
        )
        result = sandbox.stress_test(
            config={"test": "config"},
            conversations=conversations,
        )

        assert isinstance(result.failures_by_category, dict)
        # Should have some failures in at least one category (with mock 70% pass rate)
        assert result.failed > 0

    def test_stress_test_captures_failure_examples(self):
        """Test that stress test captures failure examples."""
        sandbox = SimulationSandbox()
        conversations = sandbox.generate_conversations(
            domain="customer-support",
            count=50,
        )
        result = sandbox.stress_test(
            config={"test": "config"},
            conversations=conversations,
        )

        assert isinstance(result.failure_examples, list)
        # With 70% mock pass rate, we should have failures
        if result.failed > 0:
            assert len(result.failure_examples) > 0
            assert len(result.failure_examples) <= 10  # Max 10 examples
            for example in result.failure_examples:
                assert "conversation_id" in example
                assert "user_message" in example
                assert "difficulty" in example

    def test_compare_configs_basic(self):
        """Test basic A/B comparison functionality."""
        sandbox = SimulationSandbox()
        conversations = sandbox.generate_conversations(
            domain="customer-support",
            count=20,
        )
        result = sandbox.compare(
            config_a={"version": "a"},
            config_b={"version": "b"},
            conversations=conversations,
            config_a_id="config-a",
            config_b_id="config-b",
        )

        assert result.comparison_id.startswith("compare-")
        assert result.config_a_id == "config-a"
        assert result.config_b_id == "config-b"
        assert result.total_conversations == 20
        assert 0.0 <= result.config_a_score <= 1.0
        assert 0.0 <= result.config_b_score <= 1.0
        assert result.winner in ["config_a", "config_b", "tie"]
        assert -1.0 <= result.score_delta <= 1.0

    def test_compare_configs_determines_winner(self):
        """Test that comparison correctly determines winner."""
        sandbox = SimulationSandbox()
        conversations = sandbox.generate_conversations(
            domain="customer-support",
            count=30,
        )
        result = sandbox.compare(
            config_a={"version": "a"},
            config_b={"version": "b"},
            conversations=conversations,
        )

        # Verify winner logic
        if result.winner == "config_a":
            assert result.config_a_score > result.config_b_score + 0.02
        elif result.winner == "config_b":
            assert result.config_b_score > result.config_a_score + 0.02
        else:  # tie
            assert abs(result.config_a_score - result.config_b_score) <= 0.02

    def test_compare_configs_includes_category_breakdown(self):
        """Test that comparison includes category-level breakdown."""
        sandbox = SimulationSandbox()
        conversations = sandbox.generate_conversations(
            domain="customer-support",
            count=100,
        )
        result = sandbox.compare(
            config_a={"version": "a"},
            config_b={"version": "b"},
            conversations=conversations,
        )

        assert isinstance(result.category_breakdown, dict)
        # Should have breakdown for at least one category
        assert len(result.category_breakdown) > 0

        for category, breakdown in result.category_breakdown.items():
            assert category in ["normal", "edge_case", "adversarial"]
            assert "config_a_pass_rate" in breakdown
            assert "config_b_pass_rate" in breakdown
            assert "delta" in breakdown

    def test_map_intent_to_specialist(self):
        """Test intent to specialist mapping."""
        sandbox = SimulationSandbox()
        assert sandbox._map_intent_to_specialist("billing_inquiry") == "billing"
        assert sandbox._map_intent_to_specialist("order_status") == "orders"
        assert sandbox._map_intent_to_specialist("technical_support") == "tech_support"

    def test_select_tools_for_intent(self):
        """Test tool selection for intents."""
        sandbox = SimulationSandbox()
        tools = sandbox._select_tools_for_intent("refund_request")
        assert isinstance(tools, list)
        assert "process_refund" in tools

    def test_generate_user_message_varies_by_difficulty(self):
        """Test that generated messages vary by difficulty level."""
        sandbox = SimulationSandbox()
        normal_conv = sandbox._generate_conversation("customer-support", "normal")
        adversarial_conv = sandbox._generate_conversation("customer-support", "adversarial")

        # Messages should be different for different difficulty levels
        assert normal_conv.user_message != adversarial_conv.user_message
        assert normal_conv.difficulty == "normal"
        assert adversarial_conv.difficulty == "adversarial"

    def test_stress_test_with_empty_conversations(self):
        """Test stress test with empty conversation list."""
        sandbox = SimulationSandbox()
        result = sandbox.stress_test(
            config={"test": "config"},
            conversations=[],
        )

        assert result.total_conversations == 0
        assert result.passed == 0
        assert result.failed == 0
        assert result.pass_rate == 0.0
