"""Tests for intent extraction from customer support transcripts."""

from __future__ import annotations

import pytest

from assistant.intent_extractor import (
    ConversationAnalysis,
    Entity,
    FailureMode,
    Intent,
    IntentExtractor,
    RoutingPattern,
)


@pytest.fixture
def sample_conversations():
    """Sample conversation transcripts for testing."""
    return [
        {
            "id": "conv_1",
            "messages": [
                {"role": "user", "content": "Where is my order #12345?"},
                {
                    "role": "agent",
                    "content": "Let me check that for you. Order #12345 is currently in transit and will arrive tomorrow.",
                },
            ],
            "success": True,
        },
        {
            "id": "conv_2",
            "messages": [
                {
                    "role": "user",
                    "content": "I want to return this broken product and get a refund",
                },
                {
                    "role": "agent",
                    "content": "I can help with that. What's your order number?",
                },
                {"role": "user", "content": "ORD-67890"},
                {
                    "role": "agent",
                    "content": "I've initiated a return for order 67890. You'll receive a refund within 5-7 business days.",
                },
            ],
            "success": True,
        },
        {
            "id": "conv_3",
            "messages": [
                {"role": "user", "content": "Why was I charged twice for my last bill?"},
                {
                    "role": "agent",
                    "content": "I apologize for the confusion. Let me look into your billing history.",
                },
            ],
            "success": False,
        },
    ]


def test_intent_extractor_init():
    """Test IntentExtractor initialization."""
    extractor = IntentExtractor(use_mock=True)
    assert extractor.use_mock is True
    assert extractor.llm_router is None


@pytest.mark.asyncio
async def test_extract_intents_mock(sample_conversations):
    """Test intent extraction with mock mode."""
    extractor = IntentExtractor(use_mock=True)

    intents, routing_patterns, failure_modes, tools = await extractor.extract_intents(
        sample_conversations
    )

    # Verify intents were extracted
    assert len(intents) > 0
    assert all(isinstance(i, Intent) for i in intents)

    # Check intent structure
    for intent in intents:
        assert intent.name
        assert intent.description
        assert isinstance(intent.keywords, list)
        assert intent.frequency > 0
        assert 0.0 <= intent.success_rate <= 1.0

    # Verify routing patterns
    assert len(routing_patterns) > 0
    assert all(isinstance(p, RoutingPattern) for p in routing_patterns)

    for pattern in routing_patterns:
        assert pattern.intent_name
        assert pattern.specialist_name
        assert 0.0 <= pattern.confidence <= 1.0

    # Verify failure modes
    assert isinstance(failure_modes, list)

    # Verify tools
    assert isinstance(tools, list)
    assert len(tools) > 0


@pytest.mark.asyncio
async def test_pattern_based_analysis(sample_conversations):
    """Test pattern-based analysis fallback."""
    extractor = IntentExtractor(use_mock=False, llm_router=None)

    # Test pattern matching on shipping conversation
    result = extractor._pattern_based_analysis(
        "user: Where is my order #12345?\nagent: It's in transit", success=True
    )

    assert "shipping_inquiry" in result["intents"]
    assert len(result["entities"]) > 0
    assert result["success"] is True

    # Test pattern matching on billing conversation
    result = extractor._pattern_based_analysis(
        "user: Why was I charged twice?\nagent: Let me check", success=False
    )

    assert "billing_inquiry" in result["intents"]
    assert result["success"] is False


def test_aggregate_intents():
    """Test intent aggregation from conversation analyses."""
    extractor = IntentExtractor(use_mock=True)

    analyses = [
        ConversationAnalysis(
            conversation_id="1",
            intents=["shipping_inquiry"],
            entities=[],
            success=True,
            turn_count=4,
        ),
        ConversationAnalysis(
            conversation_id="2",
            intents=["shipping_inquiry", "product_return"],
            entities=[],
            success=True,
            turn_count=6,
        ),
        ConversationAnalysis(
            conversation_id="3",
            intents=["billing_inquiry"],
            entities=[],
            success=False,
            turn_count=3,
        ),
    ]

    intents = extractor._aggregate_intents(analyses)

    # Check shipping_inquiry intent (appears twice, both successful)
    shipping = next((i for i in intents if i.name == "shipping_inquiry"), None)
    assert shipping is not None
    assert shipping.frequency == 2
    assert shipping.success_rate == 1.0
    assert shipping.avg_turns == 5.0  # (4 + 6) / 2

    # Check billing_inquiry intent (appears once, unsuccessful)
    billing = next((i for i in intents if i.name == "billing_inquiry"), None)
    assert billing is not None
    assert billing.frequency == 1
    assert billing.success_rate == 0.0
    assert billing.avg_turns == 3.0


def test_discover_routing():
    """Test routing pattern discovery."""
    extractor = IntentExtractor(use_mock=True)

    intents = [
        Intent(
            name="shipping_inquiry",
            description="Shipping questions",
            keywords=["order", "tracking", "delivery"],
            frequency=10,
            success_rate=0.9,
        ),
        Intent(
            name="billing_inquiry",
            description="Billing questions",
            keywords=["bill", "charge", "payment"],
            frequency=5,
            success_rate=0.8,
        ),
    ]

    analyses = []  # Not used in current implementation

    routing_patterns = extractor._discover_routing(analyses, intents)

    assert len(routing_patterns) == 2

    # Check shipping routing
    shipping_route = next(
        (p for p in routing_patterns if p.intent_name == "shipping_inquiry"), None
    )
    assert shipping_route is not None
    assert shipping_route.specialist_name == "orders"
    assert shipping_route.confidence == 0.9

    # Check billing routing
    billing_route = next(
        (p for p in routing_patterns if p.intent_name == "billing_inquiry"), None
    )
    assert billing_route is not None
    assert billing_route.specialist_name == "billing"
    assert billing_route.confidence == 0.8


def test_discover_failures():
    """Test failure mode discovery."""
    extractor = IntentExtractor(use_mock=True)

    analyses = [
        ConversationAnalysis(
            conversation_id="1",
            intents=["shipping_inquiry"],
            entities=[],
            success=False,
            turn_count=4,
            failure_modes=["routing_error"],
        ),
        ConversationAnalysis(
            conversation_id="2",
            intents=["billing_inquiry"],
            entities=[],
            success=False,
            turn_count=3,
            failure_modes=["routing_error", "missing_tool"],
        ),
        ConversationAnalysis(
            conversation_id="3",
            intents=["general_inquiry"],
            entities=[],
            success=False,
            turn_count=2,
            failure_modes=["unclear_response"],
        ),
    ]

    failure_modes = extractor._discover_failures(analyses, [])

    assert len(failure_modes) > 0

    # Check routing_error (appears twice)
    routing_error = next(
        (f for f in failure_modes if f.failure_type == "routing_error"), None
    )
    assert routing_error is not None
    assert routing_error.frequency == 2
    assert routing_error.severity > 0
    assert len(routing_error.example_conversation_ids) > 0

    # Verify failures are sorted by impact (frequency * severity)
    for i in range(len(failure_modes) - 1):
        current_impact = failure_modes[i].frequency * failure_modes[i].severity
        next_impact = failure_modes[i + 1].frequency * failure_modes[i + 1].severity
        assert current_impact >= next_impact


def test_discover_tools():
    """Test tool discovery from conversation patterns."""
    extractor = IntentExtractor(use_mock=True)

    analyses = [
        ConversationAnalysis(
            conversation_id="1",
            intents=["shipping_inquiry"],
            entities=[],
            success=True,
            turn_count=4,
        ),
        ConversationAnalysis(
            conversation_id="2",
            intents=["billing_inquiry"],
            entities=[],
            success=True,
            turn_count=3,
        ),
        ConversationAnalysis(
            conversation_id="3",
            intents=["product_recommendation"],
            entities=[],
            success=True,
            turn_count=5,
        ),
    ]

    tools = extractor._discover_tools(analyses, [])

    # Should discover tools based on intents
    assert "orders_db" in tools  # For shipping_inquiry
    assert "billing_system" in tools  # For billing_inquiry
    assert "catalog" in tools  # For product_recommendation

    # Tools should be sorted
    assert tools == sorted(tools)


def test_entity_extraction():
    """Test entity extraction from conversations."""
    extractor = IntentExtractor(use_mock=False, llm_router=None)

    conv_text = "User: Where is my order #12345? Agent: Let me check order ORD-67890"

    result = extractor._pattern_based_analysis(conv_text, success=True)

    # Should extract order IDs
    entities = result["entities"]
    assert len(entities) > 0

    order_ids = [e["value"] for e in entities if e["type"] == "order_id"]
    assert "12345" in order_ids or "67890" in order_ids


def test_generate_intent_description():
    """Test intent description generation."""
    extractor = IntentExtractor(use_mock=True)

    # Known intents
    assert "shipping" in extractor._generate_intent_description(
        "shipping_inquiry"
    ).lower()
    billing_desc = extractor._generate_intent_description("billing_inquiry").lower()
    assert "charge" in billing_desc or "payment" in billing_desc or "invoice" in billing_desc

    # Unknown intent
    desc = extractor._generate_intent_description("custom_intent")
    assert "custom intent" in desc.lower()


def test_generate_intent_keywords():
    """Test intent keyword generation."""
    extractor = IntentExtractor(use_mock=True)

    # Shipping keywords
    shipping_kw = extractor._generate_intent_keywords("shipping_inquiry")
    assert "order" in shipping_kw
    assert "tracking" in shipping_kw

    # Billing keywords
    billing_kw = extractor._generate_intent_keywords("billing_inquiry")
    assert "bill" in billing_kw
    assert "payment" in billing_kw

    # Unknown intent returns empty list
    unknown_kw = extractor._generate_intent_keywords("unknown_intent")
    assert unknown_kw == []


def test_parse_llm_response():
    """Test LLM response parsing."""
    extractor = IntentExtractor(use_mock=True)

    # Test with markdown code block
    markdown_response = """```json
{
    "intents": ["shipping_inquiry"],
    "entities": [{"type": "order_id", "value": "12345"}],
    "success": true,
    "failure_modes": [],
    "resolution_pattern": "Provided tracking info"
}
```"""

    result = extractor._parse_llm_response(markdown_response)
    assert result["intents"] == ["shipping_inquiry"]
    assert len(result["entities"]) == 1
    assert result["success"] is True

    # Test with plain JSON
    plain_json = '{"intents": ["billing_inquiry"], "entities": [], "success": false, "failure_modes": ["missing_tool"], "resolution_pattern": ""}'
    result = extractor._parse_llm_response(plain_json)
    assert result["intents"] == ["billing_inquiry"]
    assert result["success"] is False

    # Test with invalid JSON
    invalid = "This is not JSON"
    result = extractor._parse_llm_response(invalid)
    assert result["intents"] == []
    assert result["success"] is True  # Default fallback
