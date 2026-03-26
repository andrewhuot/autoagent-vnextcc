"""Tests for agent building orchestrator."""

from __future__ import annotations

import pytest

from assistant.agent_generator import AgentGenerator
from assistant.builder import AgentBuilder
from assistant.events import CardEvent, SuggestionsEvent, TextEvent, ThinkingEvent
from assistant.intent_extractor import IntentExtractor


@pytest.fixture
def sample_transcripts():
    """Sample transcript data for testing."""
    return [
        {
            "id": "conv_1",
            "messages": [
                {"role": "user", "content": "Where is my order #12345?"},
                {
                    "role": "agent",
                    "content": "Your order is in transit and will arrive tomorrow.",
                },
            ],
            "success": True,
        },
        {
            "id": "conv_2",
            "messages": [
                {"role": "user", "content": "I want a refund for order ORD-67890"},
                {
                    "role": "agent",
                    "content": "I've initiated your refund. You'll receive it in 5-7 days.",
                },
            ],
            "success": True,
        },
        {
            "id": "conv_3",
            "messages": [
                {"role": "user", "content": "Why was I charged twice?"},
                {"role": "agent", "content": "Let me check your billing history."},
            ],
            "success": False,
        },
    ]


def test_builder_init():
    """Test AgentBuilder initialization."""
    builder = AgentBuilder()
    assert builder.intent_extractor is not None
    assert builder.agent_generator is not None


def test_builder_with_custom_components():
    """Test AgentBuilder with custom components."""
    extractor = IntentExtractor(use_mock=True)
    generator = AgentGenerator()

    builder = AgentBuilder(intent_extractor=extractor, agent_generator=generator)

    assert builder.intent_extractor is extractor
    assert builder.agent_generator is generator


@pytest.mark.asyncio
async def test_build_from_transcripts(sample_transcripts):
    """Test building agent from transcripts."""
    # Use mock mode for testing
    extractor = IntentExtractor(use_mock=True)
    builder = AgentBuilder(intent_extractor=extractor)

    events = []
    async for event in builder.build_from_transcripts(sample_transcripts):
        events.append(event)

    # Verify we got events
    assert len(events) > 0

    # Check for different event types
    thinking_events = [e for e in events if isinstance(e, ThinkingEvent)]
    card_events = [e for e in events if isinstance(e, CardEvent)]
    text_events = [e for e in events if isinstance(e, TextEvent)]
    suggestion_events = [e for e in events if isinstance(e, SuggestionsEvent)]

    # Should have thinking events for progress
    assert len(thinking_events) > 0

    # Should have at least one card event (agent preview)
    assert len(card_events) > 0
    preview_card = next((e for e in card_events if e.card_type == "agent_preview"), None)
    assert preview_card is not None

    # Should have text explanations
    assert len(text_events) > 0

    # Should have suggestions for next actions
    assert len(suggestion_events) > 0


@pytest.mark.asyncio
async def test_build_from_transcripts_event_sequence(sample_transcripts):
    """Test event sequence and progress in build process."""
    extractor = IntentExtractor(use_mock=True)
    builder = AgentBuilder(intent_extractor=extractor)

    events = []
    async for event in builder.build_from_transcripts(sample_transcripts):
        events.append(event)

    # Verify progress sequence
    thinking_events = [e for e in events if isinstance(e, ThinkingEvent)]

    # Progress should be monotonically increasing
    for i in range(len(thinking_events) - 1):
        assert thinking_events[i].progress <= thinking_events[i + 1].progress

    # Last progress should be close to 1.0
    assert thinking_events[-1].progress >= 0.8


@pytest.mark.asyncio
async def test_build_guided():
    """Test guided agent building."""
    builder = AgentBuilder()

    events = []
    async for event in builder.build_guided(
        domain="e-commerce customer support",
        goal="help customers with orders and returns",
    ):
        events.append(event)

    # Should have some events
    assert len(events) > 0

    # Should have text events with questions
    text_events = [e for e in events if isinstance(e, TextEvent)]
    assert len(text_events) > 0

    # Should have suggestions
    suggestion_events = [e for e in events if isinstance(e, SuggestionsEvent)]
    assert len(suggestion_events) > 0


@pytest.mark.asyncio
async def test_build_from_documents():
    """Test building from documents."""
    builder = AgentBuilder()

    documents = [
        {
            "content": "Return Policy: All returns must be made within 30 days.",
            "type": "policy",
            "title": "Return Policy",
        },
        {
            "content": "Step 1: Verify order. Step 2: Process refund.",
            "type": "sop",
            "title": "Refund SOP",
        },
    ]

    events = []
    async for event in builder.build_from_documents(documents):
        events.append(event)

    # Should have some events (currently returns "under development" message)
    assert len(events) > 0


def test_parse_transcripts(sample_transcripts):
    """Test transcript parsing."""
    builder = AgentBuilder()

    conversations = builder._parse_transcripts(sample_transcripts)

    # Should parse all transcripts
    assert len(conversations) == len(sample_transcripts)

    # Check structure
    for conv in conversations:
        assert "id" in conv
        assert "messages" in conv
        assert "success" in conv


def test_parse_transcripts_nested_format():
    """Test parsing nested transcript format."""
    builder = AgentBuilder()

    nested_transcripts = [
        {
            "id": "conv_1",
            "conversation": [
                {"role": "user", "content": "Hello"},
                {"role": "agent", "content": "Hi there"},
            ],
            "success": True,
        }
    ]

    conversations = builder._parse_transcripts(nested_transcripts)

    assert len(conversations) == 1
    assert conversations[0]["id"] == "conv_1"
    assert len(conversations[0]["messages"]) == 2


def test_parse_transcripts_plain_text():
    """Test parsing plain text conversations."""
    builder = AgentBuilder()

    plain_text_transcripts = [
        """
        User: Where is my order?
        Agent: Let me check that for you.
        Agent: Your order is on the way.
        User: Thank you!
        """
    ]

    conversations = builder._parse_transcripts(plain_text_transcripts)

    assert len(conversations) == 1
    assert len(conversations[0]["messages"]) > 0

    # Check roles are parsed
    messages = conversations[0]["messages"]
    assert any(m["role"] == "user" for m in messages)
    assert any(m["role"] == "agent" for m in messages)


def test_parse_plain_text_conversation():
    """Test plain text conversation parsing."""
    builder = AgentBuilder()

    text = """
    User: Hello, I need help
    Agent: Of course! How can I assist you?
    User: My order hasn't arrived
    Agent: Let me check your order status
    """

    messages = builder._parse_plain_text_conversation(text)

    assert len(messages) > 0

    # Should have both user and agent messages
    user_messages = [m for m in messages if m["role"] == "user"]
    agent_messages = [m for m in messages if m["role"] == "agent"]

    assert len(user_messages) > 0
    assert len(agent_messages) > 0

    # Check content is extracted
    assert all(m["content"] for m in messages)


def test_parse_plain_text_conversation_alternate_labels():
    """Test parsing with alternate role labels."""
    builder = AgentBuilder()

    text = """
    Customer: I need a refund
    Support: I can help with that
    """

    messages = builder._parse_plain_text_conversation(text)

    assert len(messages) == 2
    assert messages[0]["role"] == "user"  # Customer mapped to user
    assert messages[1]["role"] == "agent"  # Support mapped to agent


def test_extract_knowledge():
    """Test knowledge extraction from conversations."""
    builder = AgentBuilder()

    conversations = [
        {
            "id": "1",
            "messages": [
                {"role": "user", "content": "Need help"},
                {
                    "role": "agent",
                    "content": "I've resolved your issue by doing X and Y.",
                },
            ],
            "success": True,
        },
        {
            "id": "2",
            "messages": [
                {"role": "user", "content": "Problem"},
                {"role": "agent", "content": "I couldn't help"},
            ],
            "success": False,
        },
    ]

    knowledge = builder._extract_knowledge(conversations, [])

    # Should extract from successful conversations only
    assert "successful_patterns" in knowledge
    assert len(knowledge["successful_patterns"]) > 0


def test_generate_domain_questions():
    """Test domain question generation."""
    builder = AgentBuilder()

    # E-commerce domain
    questions = builder._generate_domain_questions("e-commerce")
    assert len(questions) > 0
    assert any("order" in q.lower() for q in questions)

    # Support domain
    questions = builder._generate_domain_questions("support")
    assert len(questions) > 0

    # Unknown domain - should return common questions
    questions = builder._generate_domain_questions("unknown domain")
    assert len(questions) > 0


def test_parse_documents():
    """Test document parsing."""
    builder = AgentBuilder()

    documents = [
        {"content": "SOP content", "type": "sop", "title": "SOP Doc"},
        {"content": "FAQ content"},  # Missing type and title
    ]

    parsed = builder._parse_documents(documents)

    assert len(parsed) == 2
    assert parsed[0]["type"] == "sop"
    assert parsed[0]["title"] == "SOP Doc"
    assert parsed[1]["type"] == "knowledge"  # Default type
    assert parsed[1]["title"] == "Untitled"  # Default title


def test_extract_procedures():
    """Test procedure extraction from documents."""
    builder = AgentBuilder()

    documents = [
        {
            "content": "Step 1: Do this. Step 2: Do that.",
            "type": "sop",
            "title": "Refund Procedure",
        },
        {
            "content": "Just some text",
            "type": "sop",
            "title": "No Steps",
        },
        {
            "content": "1. First step 2. Second step",
            "type": "procedure",
            "title": "Order Process",
        },
    ]

    procedures = builder._extract_procedures(documents)

    # Should find documents with step markers
    assert len(procedures) > 0
    assert "Refund Procedure" in procedures or "Order Process" in procedures


def test_extract_policies():
    """Test policy extraction from documents."""
    builder = AgentBuilder()

    documents = [
        {"content": "Policy text", "type": "policy", "title": "Return Policy"},
        {"content": "Guideline text", "type": "guideline", "title": "Service Guidelines"},
        {"content": "SOP text", "type": "sop", "title": "Not a Policy"},
    ]

    policies = builder._extract_policies(documents)

    # Should extract policy and guideline types only
    assert len(policies) == 2
    assert "Return Policy" in policies
    assert "Service Guidelines" in policies


def test_event_to_dict():
    """Test event serialization to dict."""
    thinking = ThinkingEvent(step="Testing", progress=0.5, details={"key": "value"})
    thinking_dict = thinking.to_dict()

    assert thinking_dict["type"] == "thinking"
    assert thinking_dict["step"] == "Testing"
    assert thinking_dict["progress"] == 0.5
    assert thinking_dict["details"]["key"] == "value"

    card = CardEvent(card_type="test_card", data={"field": "data"})
    card_dict = card.to_dict()

    assert card_dict["type"] == "card"
    assert card_dict["card_type"] == "test_card"
    assert card_dict["data"]["field"] == "data"

    text = TextEvent(content="Test message")
    text_dict = text.to_dict()

    assert text_dict["type"] == "text"
    assert text_dict["content"] == "Test message"

    suggestions = SuggestionsEvent(actions=["Action 1", "Action 2"])
    suggestions_dict = suggestions.to_dict()

    assert suggestions_dict["type"] == "suggestions"
    assert len(suggestions_dict["actions"]) == 2
