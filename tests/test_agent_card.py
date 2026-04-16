"""Tests for the Agent Card module: schema, renderer, and converter."""

from __future__ import annotations

import pytest

from agent_card.schema import (
    AgentCardModel,
    CallbackEntry,
    CallbackTiming,
    EnvironmentEntry,
    GuardrailEntry,
    HandoffEntry,
    McpServerEntry,
    PolicyEntry,
    RoutingRuleEntry,
    SubAgentSection,
    ToolEntry,
)
from agent_card.renderer import render_to_markdown, parse_from_markdown
from agent_card.converter import (
    from_canonical_agent,
    to_canonical_agent,
    from_config_dict,
    to_config_dict,
)
from shared.canonical_ir import (
    CanonicalAgent,
    ConditionType,
    ContextTransfer,
    EnvironmentConfig,
    GuardrailEnforcement,
    GuardrailSpec,
    GuardrailType,
    HandoffSpec,
    Instruction,
    InstructionFormat,
    InstructionRole,
    McpServerRef,
    PolicyEnforcement,
    PolicySpec,
    PolicyType,
    RoutingRuleSpec,
    ToolContract,
    ToolInvocationHint,
    ToolParameter,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_full_card() -> AgentCardModel:
    """Create a fully populated Agent Card for testing."""
    return AgentCardModel(
        name="customer_service_bot",
        description="Multi-agent customer service system",
        version="2.0",
        platform_origin="google_adk",
        instructions="You are a customer service orchestrator. Route queries to specialists.",
        tools=[
            ToolEntry(
                name="faq_lookup",
                description="Search the FAQ database",
                parameters=[
                    {"name": "query", "type": "string", "required": True, "description": "Search query"},
                    {"name": "limit", "type": "integer", "required": False, "description": "Max results"},
                ],
                timeout_ms=5000,
            ),
        ],
        callbacks=[
            CallbackEntry(
                name="validate_input",
                timing=CallbackTiming.BEFORE_MODEL,
                description="Validates user input before model call",
                function_name="validate_input",
                signature="def validate_input(ctx: CallbackContext) -> None",
                body="if len(ctx.user_message) > 10000:\n    raise ValueError('Input too long')",
            ),
        ],
        routing_rules=[
            RoutingRuleEntry(
                target="support",
                condition_type="keyword",
                keywords=["help", "issue", "problem"],
                priority=1,
            ),
            RoutingRuleEntry(
                target="orders",
                condition_type="keyword",
                keywords=["order", "shipping", "track"],
                priority=0,
            ),
        ],
        guardrails=[
            GuardrailEntry(
                name="safety_filter",
                type="both",
                enforcement="block",
                description="Blocks harmful content",
            ),
        ],
        policies=[
            PolicyEntry(
                name="data_privacy",
                type="compliance",
                enforcement="required",
                description="Never share user PII",
            ),
        ],
        handoffs=[
            HandoffEntry(
                source="orchestrator",
                target="support",
                context_transfer="full",
                condition="routing_match",
            ),
        ],
        mcp_servers=[
            McpServerEntry(
                name="knowledge_base",
                tools_exposed=["search", "retrieve"],
                config={"url": "http://localhost:8080"},
            ),
        ],
        environment=EnvironmentEntry(
            model="gemini-2.0-flash",
            provider="google",
            temperature=0.3,
            max_tokens=2048,
        ),
        sub_agents=[
            SubAgentSection(
                name="support",
                description="Handles support queries",
                instructions="You are a support specialist. Help users with issues.",
                tools=[
                    ToolEntry(name="ticket_create", description="Create support ticket"),
                ],
                callbacks=[
                    CallbackEntry(
                        name="log_interaction",
                        timing=CallbackTiming.AFTER_MODEL,
                        description="Logs the interaction",
                        function_name="log_interaction",
                    ),
                ],
            ),
            SubAgentSection(
                name="orders",
                description="Handles order queries",
                instructions="You are an orders specialist. Help with order tracking.",
                tools=[
                    ToolEntry(name="orders_db", description="Query orders database", timeout_ms=3000),
                ],
            ),
        ],
        example_traces=[
            {"input": "Where is my order?", "output": "Let me check...", "specialist": "orders"},
        ],
    )


def _make_canonical_agent() -> CanonicalAgent:
    """Create a CanonicalAgent for conversion testing."""
    return CanonicalAgent(
        name="test_agent",
        description="A test agent",
        platform_origin="test",
        instructions=[
            Instruction(
                role=InstructionRole.SYSTEM,
                content="You are a helpful agent.",
                format=InstructionFormat.TEXT,
                priority=100,
                label="root",
            ),
        ],
        tools=[
            ToolContract(
                name="search",
                description="Search for information",
                parameters=[
                    ToolParameter(name="query", type="string", required=True, description="Search query"),
                ],
                invocation_hint=ToolInvocationHint.AUTO,
                timeout_ms=5000,
            ),
        ],
        routing_rules=[
            RoutingRuleSpec(
                target="specialist_a",
                condition_type=ConditionType.KEYWORD,
                keywords=["help", "support"],
                priority=1,
            ),
        ],
        guardrails=[
            GuardrailSpec(
                name="safety",
                type=GuardrailType.OUTPUT,
                enforcement=GuardrailEnforcement.BLOCK,
                description="Blocks unsafe output",
            ),
        ],
        policies=[
            PolicySpec(
                name="privacy",
                type=PolicyType.COMPLIANCE,
                enforcement=PolicyEnforcement.REQUIRED,
                description="Protect user privacy",
            ),
        ],
        handoffs=[
            HandoffSpec(
                source="root",
                target="specialist_a",
                context_transfer=ContextTransfer.FULL,
            ),
        ],
        mcp_servers=[
            McpServerRef(
                name="tools_server",
                tools_exposed=["tool_a", "tool_b"],
                config={"port": 9090},
            ),
        ],
        environment=EnvironmentConfig(
            model="gpt-4",
            provider="openai",
            temperature=0.5,
            max_tokens=1024,
        ),
        sub_agents=[
            CanonicalAgent(
                name="specialist_a",
                instructions=[
                    Instruction(
                        role=InstructionRole.SYSTEM,
                        content="You handle support queries.",
                        format=InstructionFormat.TEXT,
                        priority=100,
                        label="specialist_a",
                    ),
                ],
                tools=[
                    ToolContract(name="ticket_api", description="Create tickets"),
                ],
            ),
        ],
    )


def _make_config_dict() -> dict:
    """Create a typical AgentLab config dict."""
    return {
        "name": "service_bot",
        "description": "Customer service bot",
        "version": "1.0",
        "model": "gemini-2.0-flash",
        "prompts": {
            "root": "You are a customer service orchestrator.",
            "support": "You are a support specialist.",
            "orders": "You are an orders specialist.",
        },
        "tools": {
            "faq": {"description": "FAQ lookup", "timeout_ms": 5000},
            "orders_db": {"description": "Orders database"},
        },
        "routing": {
            "rules": [
                {"specialist": "support", "keywords": ["help", "issue"]},
                {"specialist": "orders", "keywords": ["order", "track"]},
            ],
        },
        "guardrails": [
            {"name": "safety", "type": "both", "enforcement": "block", "description": "Safety filter"},
        ],
        "generation": {
            "temperature": 0.3,
            "max_tokens": 2048,
        },
        "thresholds": {"max_turns": 20, "confidence_threshold": 0.6},
    }


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestAgentCardSchema:
    def test_minimal_card(self):
        card = AgentCardModel(name="minimal")
        assert card.name == "minimal"
        assert card.version == "1.0"
        assert card.sub_agents == []
        assert card.tools == []

    def test_full_card_surfaces(self):
        card = _make_full_card()
        summary = card.surface_summary()
        assert summary["tools"] >= 3  # root faq_lookup + support ticket_create + orders orders_db
        assert summary["callbacks"] >= 2
        assert summary["routing_rules"] == 2
        assert summary["sub_agents"] == 2

    def test_all_agent_names(self):
        card = _make_full_card()
        names = card.all_agent_names()
        assert "customer_service_bot" in names
        assert "support" in names
        assert "orders" in names

    def test_find_sub_agent(self):
        card = _make_full_card()
        support = card.find_sub_agent("support")
        assert support is not None
        assert support.name == "support"
        assert card.find_sub_agent("nonexistent") is None

    def test_all_tool_names(self):
        card = _make_full_card()
        names = card.all_tool_names()
        assert "faq_lookup" in names
        assert "ticket_create" in names
        assert "orders_db" in names

    def test_all_callbacks(self):
        card = _make_full_card()
        cbs = card.all_callbacks()
        names = [cb.name for cb in cbs]
        assert "validate_input" in names
        assert "log_interaction" in names

    def test_nested_sub_agents(self):
        inner = SubAgentSection(name="inner", instructions="Inner agent")
        outer = SubAgentSection(name="outer", sub_agents=[inner])
        card = AgentCardModel(name="root", sub_agents=[outer])
        names = card.all_agent_names()
        assert "inner" in names
        assert card.find_sub_agent("inner") is not None


# ---------------------------------------------------------------------------
# Renderer round-trip tests
# ---------------------------------------------------------------------------


class TestRendererRoundTrip:
    def test_minimal_round_trip(self):
        card = AgentCardModel(name="minimal", description="A minimal agent")
        md = render_to_markdown(card)
        parsed = parse_from_markdown(md)
        assert parsed.name == "minimal"
        assert parsed.description == "A minimal agent"

    def test_full_card_round_trip(self):
        original = _make_full_card()
        md = render_to_markdown(original)
        parsed = parse_from_markdown(md)

        assert parsed.name == original.name
        assert parsed.version == original.version
        assert parsed.platform_origin == original.platform_origin
        assert parsed.instructions == original.instructions

        # Environment
        assert parsed.environment.model == original.environment.model
        assert parsed.environment.temperature == original.environment.temperature

        # Tools
        assert len(parsed.tools) == len(original.tools)
        assert parsed.tools[0].name == "faq_lookup"
        assert parsed.tools[0].timeout_ms == 5000

        # Routing rules
        assert len(parsed.routing_rules) == len(original.routing_rules)
        assert parsed.routing_rules[0].target == "support"
        assert "help" in parsed.routing_rules[0].keywords

        # Guardrails
        assert len(parsed.guardrails) == len(original.guardrails)
        assert parsed.guardrails[0].name == "safety_filter"

        # Policies
        assert len(parsed.policies) == len(original.policies)
        assert parsed.policies[0].name == "data_privacy"

        # Handoffs
        assert len(parsed.handoffs) == len(original.handoffs)

        # Sub-agents
        assert len(parsed.sub_agents) == len(original.sub_agents)
        assert parsed.sub_agents[0].name == "support"
        assert "support specialist" in parsed.sub_agents[0].instructions.lower()

    def test_callbacks_round_trip(self):
        card = AgentCardModel(
            name="cb_test",
            callbacks=[
                CallbackEntry(
                    name="check",
                    timing=CallbackTiming.BEFORE_MODEL,
                    description="Pre-model check",
                    function_name="check_fn",
                    body="return True",
                ),
            ],
        )
        md = render_to_markdown(card)
        parsed = parse_from_markdown(md)
        assert len(parsed.callbacks) == 1
        assert parsed.callbacks[0].name == "check"
        assert parsed.callbacks[0].timing == CallbackTiming.BEFORE_MODEL
        assert parsed.callbacks[0].body == "return True"

    def test_mcp_servers_round_trip(self):
        card = AgentCardModel(
            name="mcp_test",
            mcp_servers=[
                McpServerEntry(
                    name="tool_server",
                    tools_exposed=["search", "create"],
                    config={"url": "http://localhost:8080"},
                ),
            ],
        )
        md = render_to_markdown(card)
        parsed = parse_from_markdown(md)
        assert len(parsed.mcp_servers) == 1
        assert parsed.mcp_servers[0].name == "tool_server"
        assert "search" in parsed.mcp_servers[0].tools_exposed

    def test_tool_parameters_round_trip(self):
        card = AgentCardModel(
            name="param_test",
            tools=[
                ToolEntry(
                    name="search",
                    description="Search tool",
                    parameters=[
                        {"name": "query", "type": "string", "required": True, "description": "The search query"},
                        {"name": "limit", "type": "integer", "required": False, "description": "Max results"},
                    ],
                ),
            ],
        )
        md = render_to_markdown(card)
        parsed = parse_from_markdown(md)
        assert len(parsed.tools) == 1
        assert len(parsed.tools[0].parameters) == 2
        assert parsed.tools[0].parameters[0]["name"] == "query"
        assert parsed.tools[0].parameters[0]["required"] is True

    def test_empty_sections_no_crash(self):
        card = AgentCardModel(name="empty")
        md = render_to_markdown(card)
        parsed = parse_from_markdown(md)
        assert parsed.name == "empty"
        assert parsed.tools == []
        assert parsed.sub_agents == []


# ---------------------------------------------------------------------------
# Converter: CanonicalAgent ↔ AgentCardModel
# ---------------------------------------------------------------------------


class TestCanonicalConversion:
    def test_canonical_to_card(self):
        agent = _make_canonical_agent()
        card = from_canonical_agent(agent)

        assert card.name == "test_agent"
        assert card.description == "A test agent"
        assert "helpful agent" in card.instructions
        assert len(card.tools) == 1
        assert card.tools[0].name == "search"
        assert len(card.routing_rules) == 1
        assert card.routing_rules[0].target == "specialist_a"
        assert len(card.guardrails) == 1
        assert len(card.policies) == 1
        assert len(card.handoffs) == 1
        assert len(card.mcp_servers) == 1
        assert len(card.sub_agents) == 1
        assert card.sub_agents[0].name == "specialist_a"

    def test_card_to_canonical(self):
        card = _make_full_card()
        agent = to_canonical_agent(card)

        assert agent.name == "customer_service_bot"
        assert len(agent.instructions) >= 1
        assert "orchestrator" in agent.instructions[0].content
        assert len(agent.tools) == 1
        assert agent.tools[0].name == "faq_lookup"
        assert len(agent.routing_rules) == 2
        assert len(agent.sub_agents) == 2

    def test_canonical_round_trip(self):
        original = _make_canonical_agent()
        card = from_canonical_agent(original)
        recovered = to_canonical_agent(card)

        assert recovered.name == original.name
        assert recovered.description == original.description
        assert len(recovered.tools) == len(original.tools)
        assert recovered.tools[0].name == original.tools[0].name
        assert len(recovered.routing_rules) == len(original.routing_rules)
        assert len(recovered.sub_agents) == len(original.sub_agents)
        assert recovered.environment.model == original.environment.model

    def test_sub_agent_tools_preserved(self):
        agent = _make_canonical_agent()
        card = from_canonical_agent(agent)
        assert card.sub_agents[0].tools[0].name == "ticket_api"

        recovered = to_canonical_agent(card)
        assert recovered.sub_agents[0].tools[0].name == "ticket_api"


# ---------------------------------------------------------------------------
# Converter: Config dict ↔ AgentCardModel
# ---------------------------------------------------------------------------


class TestConfigDictConversion:
    def test_config_to_card(self):
        config = _make_config_dict()
        card = from_config_dict(config, name="service_bot")

        assert card.name == "service_bot"
        assert "orchestrator" in card.instructions
        assert len(card.tools) == 2
        tool_names = [t.name for t in card.tools]
        assert "faq" in tool_names
        assert "orders_db" in tool_names
        assert len(card.routing_rules) == 2
        assert len(card.sub_agents) == 2  # support and orders
        assert card.environment.model == "gemini-2.0-flash"

    def test_card_to_config(self):
        card = _make_full_card()
        config = to_config_dict(card)

        assert config["name"] == "customer_service_bot"
        assert "root" in config["prompts"]
        assert "support" in config["prompts"]
        assert "faq_lookup" in config["tools"]
        assert len(config["routing"]["rules"]) == 2
        assert config["model"] == "gemini-2.0-flash"
        assert config["generation"]["temperature"] == 0.3

    def test_config_round_trip(self):
        original = _make_config_dict()
        card = from_config_dict(original, name="service_bot")
        recovered = to_config_dict(card)

        assert recovered["prompts"]["root"] == original["prompts"]["root"]
        assert recovered["model"] == original["model"]
        assert recovered["generation"]["temperature"] == original["generation"]["temperature"]
        assert len(recovered["routing"]["rules"]) == len(original["routing"]["rules"])

    def test_config_preserves_extra_metadata(self):
        config = _make_config_dict()
        card = from_config_dict(config)
        # thresholds should be carried as metadata
        assert "thresholds" in card.metadata

    def test_name_from_config(self):
        config = {"name": "auto_name", "prompts": {"root": "Hello"}}
        card = from_config_dict(config)
        assert card.name == "auto_name"

    def test_empty_config(self):
        card = from_config_dict({})
        assert card.name == "agent"
        assert card.tools == []
        assert card.sub_agents == []


# ---------------------------------------------------------------------------
# Full pipeline test: CanonicalAgent → Card → Markdown → Card → CanonicalAgent
# ---------------------------------------------------------------------------


class TestFullPipeline:
    def test_full_pipeline(self):
        original_agent = _make_canonical_agent()

        # Step 1: CanonicalAgent → AgentCard
        card = from_canonical_agent(original_agent)
        assert card.name == "test_agent"

        # Step 2: AgentCard → Markdown
        md = render_to_markdown(card)
        assert "# Agent Card: test_agent" in md

        # Step 3: Markdown → AgentCard
        parsed_card = parse_from_markdown(md)
        assert parsed_card.name == "test_agent"

        # Step 4: AgentCard → CanonicalAgent
        recovered = to_canonical_agent(parsed_card)
        assert recovered.name == original_agent.name
        assert len(recovered.tools) == len(original_agent.tools)
        assert recovered.tools[0].name == original_agent.tools[0].name

    def test_config_dict_full_pipeline(self):
        original_config = _make_config_dict()

        card = from_config_dict(original_config, name="service_bot")
        md = render_to_markdown(card)
        parsed = parse_from_markdown(md)
        recovered_config = to_config_dict(parsed)

        assert recovered_config["prompts"]["root"] == original_config["prompts"]["root"]
        assert recovered_config["model"] == original_config["model"]
