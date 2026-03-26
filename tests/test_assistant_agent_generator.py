"""Tests for agent configuration generation."""

from __future__ import annotations

import pytest

from assistant.agent_generator import AgentGenerator, GeneratedAgentConfig, SpecialistAgent
from assistant.intent_extractor import FailureMode, Intent, RoutingPattern


@pytest.fixture
def sample_intents():
    """Sample intents for testing."""
    return [
        Intent(
            name="shipping_inquiry",
            description="Questions about order shipping",
            keywords=["order", "tracking", "delivery"],
            frequency=50,
            success_rate=0.85,
            avg_turns=4.2,
            requires_tools=["orders_db"],
        ),
        Intent(
            name="product_return",
            description="Product return requests",
            keywords=["refund", "return", "exchange"],
            frequency=30,
            success_rate=0.75,
            avg_turns=5.8,
            requires_tools=["orders_db"],
        ),
        Intent(
            name="billing_inquiry",
            description="Billing and payment questions",
            keywords=["bill", "charge", "payment"],
            frequency=20,
            success_rate=0.90,
            avg_turns=3.5,
            requires_tools=["billing_system"],
        ),
    ]


@pytest.fixture
def sample_routing_patterns():
    """Sample routing patterns for testing."""
    return [
        RoutingPattern(
            intent_name="shipping_inquiry",
            specialist_name="orders",
            confidence=0.85,
            supporting_keywords=["order", "tracking", "delivery"],
        ),
        RoutingPattern(
            intent_name="product_return",
            specialist_name="orders",
            confidence=0.75,
            supporting_keywords=["refund", "return", "exchange"],
        ),
        RoutingPattern(
            intent_name="billing_inquiry",
            specialist_name="billing",
            confidence=0.90,
            supporting_keywords=["bill", "charge", "payment"],
        ),
    ]


@pytest.fixture
def sample_failure_modes():
    """Sample failure modes for testing."""
    return [
        FailureMode(
            failure_type="routing_error",
            description="Wrong specialist routing",
            frequency=15,
            severity=0.7,
            example_conversation_ids=["conv_1", "conv_2"],
            suggested_fix="Improve routing keywords",
        ),
        FailureMode(
            failure_type="missing_tool",
            description="Required tool not available",
            frequency=5,
            severity=0.8,
            example_conversation_ids=["conv_3"],
            suggested_fix="Add tool integration",
        ),
    ]


def test_agent_generator_init():
    """Test AgentGenerator initialization."""
    generator = AgentGenerator()
    assert generator is not None


def test_generate_config(
    sample_intents, sample_routing_patterns, sample_failure_modes
):
    """Test complete agent configuration generation."""
    generator = AgentGenerator()

    result = generator.generate_config(
        intents=sample_intents,
        routing_patterns=sample_routing_patterns,
        failure_modes=sample_failure_modes,
        required_tools=["orders_db", "billing_system"],
    )

    # Verify result type
    assert isinstance(result, GeneratedAgentConfig)

    # Check config structure
    assert result.config is not None
    assert result.config.model == "gemini-2.0-flash"

    # Check specialists
    assert len(result.specialists) > 0
    assert all(isinstance(s, SpecialistAgent) for s in result.specialists)

    # Check routing configuration
    assert len(result.config.routing.rules) > 0

    # Check coverage
    assert 0.0 <= result.coverage_pct <= 100.0

    # Check metadata
    assert result.estimated_intents == len(sample_intents)
    assert isinstance(result.routing_logic, str)


def test_build_specialists(sample_intents, sample_routing_patterns):
    """Test specialist agent building."""
    generator = AgentGenerator()

    specialists = generator._build_specialists(
        intents=sample_intents,
        routing_patterns=sample_routing_patterns,
        required_tools=["orders_db", "billing_system"],
        few_shot_examples=[],
    )

    # Should have multiple specialists
    assert len(specialists) > 0

    # Find orders specialist
    orders_specialist = next((s for s in specialists if s.name == "orders"), None)
    assert orders_specialist is not None
    assert "shipping_inquiry" in orders_specialist.handles_intents
    assert "product_return" in orders_specialist.handles_intents
    assert len(orders_specialist.instructions) > 0
    assert "orders_db" in orders_specialist.required_tools

    # Find billing specialist
    billing_specialist = next((s for s in specialists if s.name == "billing"), None)
    assert billing_specialist is not None
    assert "billing_inquiry" in billing_specialist.handles_intents


def test_generate_specialist_description():
    """Test specialist description generation."""
    generator = AgentGenerator()

    # Known specialists
    orders_desc = generator._generate_specialist_description(
        "orders", ["shipping_inquiry", "product_return"]
    )
    assert "order" in orders_desc.lower()

    billing_desc = generator._generate_specialist_description(
        "billing", ["billing_inquiry"]
    )
    assert "billing" in billing_desc.lower()

    # Unknown specialist - should generate from intent names
    custom_desc = generator._generate_specialist_description(
        "custom", ["custom_intent_1", "custom_intent_2"]
    )
    assert "custom intent" in custom_desc.lower()


def test_generate_specialist_instructions():
    """Test specialist instruction generation."""
    generator = AgentGenerator()

    intents = [
        Intent(
            name="shipping_inquiry",
            description="Shipping questions",
            keywords=["order", "tracking"],
            frequency=10,
            success_rate=0.8,
        )
    ]

    # Test orders specialist
    instructions = generator._generate_specialist_instructions(
        specialist_name="orders",
        intents=intents,
        tools=["orders_db"],
    )

    assert len(instructions) > 0
    assert "order" in instructions.lower()
    assert "orders_db" in instructions.lower()

    # Test support specialist
    support_instructions = generator._generate_specialist_instructions(
        specialist_name="support",
        intents=[],
        tools=[],
    )

    assert len(support_instructions) > 0
    assert "support" in support_instructions.lower()


def test_build_routing_config(sample_routing_patterns):
    """Test routing configuration building."""
    generator = AgentGenerator()

    routing_config = generator._build_routing_config(sample_routing_patterns)

    # Check structure
    assert len(routing_config.rules) > 0

    # Check orders routing rule
    orders_rule = next((r for r in routing_config.rules if r.specialist == "orders"), None)
    assert orders_rule is not None
    assert "order" in orders_rule.keywords
    assert "tracking" in orders_rule.keywords
    assert "refund" in orders_rule.keywords

    # Check billing routing rule
    billing_rule = next((r for r in routing_config.rules if r.specialist == "billing"), None)
    assert billing_rule is not None
    assert "bill" in billing_rule.keywords


def test_build_prompts_config(sample_intents, sample_routing_patterns):
    """Test prompts configuration building."""
    generator = AgentGenerator()

    specialists = generator._build_specialists(
        intents=sample_intents,
        routing_patterns=sample_routing_patterns,
        required_tools=[],
        few_shot_examples=[],
    )

    prompts_config = generator._build_prompts_config(specialists, {})

    # Check root prompt
    assert prompts_config.root
    assert "orchestrator" in prompts_config.root.lower()

    # Check that known specialist prompts exist in config
    # PromptsConfig has predefined fields: root, support, orders, recommendations
    assert prompts_config.orders  # orders specialist should exist
    assert prompts_config.support  # support should have default
    assert prompts_config.recommendations  # recommendations should have default


def test_build_tools_config():
    """Test tools configuration building."""
    generator = AgentGenerator()

    tools_config = generator._build_tools_config(
        ["orders_db", "catalog", "billing_system"]
    )

    # Check that tools are configured
    assert tools_config.orders_db.enabled is True
    assert tools_config.catalog.enabled is True


def test_map_tool_name():
    """Test tool name mapping."""
    generator = AgentGenerator()

    assert generator._map_tool_name("orders_db") == "orders_db"
    assert generator._map_tool_name("catalog") == "catalog"
    assert generator._map_tool_name("billing_system") == "faq"  # Mapped
    assert generator._map_tool_name("knowledge_base") == "faq"  # Mapped


def test_calculate_coverage(sample_intents, sample_routing_patterns):
    """Test coverage calculation."""
    generator = AgentGenerator()

    # All intents covered
    coverage = generator._calculate_coverage(sample_intents, sample_routing_patterns)
    assert coverage == 100.0

    # Partial coverage
    partial_patterns = sample_routing_patterns[:2]
    coverage = generator._calculate_coverage(sample_intents, partial_patterns)
    assert coverage < 100.0
    assert coverage > 0.0

    # Empty intents
    coverage = generator._calculate_coverage([], sample_routing_patterns)
    assert coverage == 100.0


def test_build_routing_logic_summary(sample_routing_patterns):
    """Test routing logic summary generation."""
    generator = AgentGenerator()

    specialists = [
        SpecialistAgent(
            name="orders",
            description="Order specialist",
            instructions="Handle orders",
            handles_intents=["shipping_inquiry", "product_return"],
        ),
        SpecialistAgent(
            name="billing",
            description="Billing specialist",
            instructions="Handle billing",
            handles_intents=["billing_inquiry"],
        ),
    ]

    summary = generator._build_routing_logic_summary(sample_routing_patterns, specialists)

    assert len(summary) > 0
    assert "orders" in summary.lower()
    assert "billing" in summary.lower()


def test_identify_addressed_failures(sample_failure_modes):
    """Test failure mode addressing identification."""
    generator = AgentGenerator()

    specialists = [
        SpecialistAgent(
            name="orders",
            description="Order specialist",
            instructions="Handle orders",
            handles_intents=["shipping_inquiry"],
            required_tools=["orders_db"],
        ),
        SpecialistAgent(
            name="billing",
            description="Billing specialist",
            instructions="Handle billing",
            handles_intents=["billing_inquiry"],
        ),
    ]

    addressed = generator._identify_addressed_failures(sample_failure_modes, specialists)

    # Should address routing_error (multiple specialists exist)
    assert "routing_error" in addressed

    # Should address missing_tool (specialists have tools)
    assert "missing_tool" in addressed


def test_to_preview(sample_intents, sample_routing_patterns, sample_failure_modes):
    """Test preview card generation."""
    generator = AgentGenerator()

    result = generator.generate_config(
        intents=sample_intents,
        routing_patterns=sample_routing_patterns,
        failure_modes=sample_failure_modes,
        required_tools=["orders_db"],
    )

    preview = result.to_preview()

    # Check preview structure
    assert "specialists" in preview
    assert "routing_logic" in preview
    assert "coverage_pct" in preview
    assert "estimated_intents" in preview
    assert "failure_modes_addressed" in preview
    assert "config_summary" in preview

    # Check specialists in preview
    assert len(preview["specialists"]) > 0
    for specialist in preview["specialists"]:
        assert "name" in specialist
        assert "description" in specialist
        assert "handles_intents" in specialist
        assert "required_tools" in specialist

    # Check config summary
    assert preview["config_summary"]["model"] == "gemini-2.0-flash"


def test_extract_few_shot_examples():
    """Test few-shot example extraction."""
    generator = AgentGenerator()

    all_examples = [
        {
            "intent": "shipping_inquiry",
            "user_message": "Where is my order?",
            "agent_response": "Let me check that for you.",
        },
        {
            "intent": "billing_inquiry",
            "user_message": "What's this charge?",
            "agent_response": "I'll look into your billing.",
        },
        {
            "intent": "shipping_inquiry",
            "user_message": "When will it arrive?",
            "agent_response": "It will arrive tomorrow.",
        },
    ]

    examples = generator._extract_few_shot_examples(
        specialist_name="orders",
        intent_names=["shipping_inquiry"],
        all_examples=all_examples,
    )

    # Should get shipping examples only
    assert len(examples) == 2
    for example in examples:
        assert "user" in example
        assert "assistant" in example
