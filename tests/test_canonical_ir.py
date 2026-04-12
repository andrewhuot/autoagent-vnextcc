"""Tests for canonical IR types, conversions, and adapter integration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from shared.canonical_ir import (
    CanonicalAgent,
    ConditionType,
    ContextTransfer,
    EnvironmentConfig,
    FidelityNote,
    FidelityStatus,
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
from shared.canonical_ir_convert import (
    from_adk_tree,
    from_config_dict,
    from_imported_spec,
    to_config_dict,
    to_imported_spec,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_imported_spec(**overrides: Any) -> Any:
    """Build an ImportedAgentSpec-like object for testing conversions."""
    from adapters.base import ImportedAgentSpec

    defaults: dict[str, Any] = {
        "adapter": "openai-agents",
        "source": "/tmp/test-agent",
        "agent_name": "TestAgent",
        "platform": "OpenAI Agents",
        "system_prompts": ["You are a helpful support agent."],
        "tools": [
            {
                "name": "lookup_order",
                "description": "Look up order status by ID",
                "parameters": [
                    {"name": "order_id", "type": "string", "required": True},
                ],
            },
            {
                "name": "search_faq",
                "description": "Search the FAQ database",
            },
        ],
        "guardrails": [
            {"name": "pii_filter", "description": "Block PII in output", "type": "output"},
            {"name": "tone_check"},
        ],
        "handoffs": [
            {"source": "TestAgent", "target": "BillingAgent"},
            {"source": "TestAgent", "target": "TechSupport", "condition": "technical issue"},
        ],
        "mcp_refs": [
            {"name": "docs_server", "config": {"command": "npx", "args": ["docs"]}},
        ],
        "session_patterns": ["messages.create"],
        "traces": [
            {
                "id": "trace-1",
                "messages": [
                    {"role": "user", "content": "Where is my order?"},
                    {"role": "assistant", "content": "Let me check that for you."},
                ],
            }
        ],
        "config": {"model": "gpt-4"},
        "starter_evals": [],
        "adapter_config": {"adapter": "openai-agents"},
        "metadata": {"detected_agents": ["TestAgent", "BillingAgent"]},
    }
    defaults.update(overrides)
    return ImportedAgentSpec(**defaults)


@pytest.fixture
def sample_spec():
    return _make_imported_spec()


@pytest.fixture
def sample_canonical() -> CanonicalAgent:
    return CanonicalAgent(
        name="TestAgent",
        description="A test agent",
        platform_origin="OpenAI Agents",
        instructions=[
            Instruction(
                role=InstructionRole.SYSTEM,
                content="You are a helpful support agent.",
                priority=100,
                label="root",
            ),
        ],
        tools=[
            ToolContract(
                name="lookup_order",
                description="Look up order status by ID",
                parameters=[
                    ToolParameter(name="order_id", type="string", required=True),
                ],
                source_platform="OpenAI Agents",
            ),
            ToolContract(
                name="search_faq",
                description="Search the FAQ database",
                source_platform="OpenAI Agents",
            ),
        ],
        routing_rules=[
            RoutingRuleSpec(
                target="BillingAgent",
                condition_type=ConditionType.KEYWORD,
                keywords=["billingagent"],
            ),
        ],
        guardrails=[
            GuardrailSpec(
                name="pii_filter",
                type=GuardrailType.OUTPUT,
                description="Block PII in output",
            ),
        ],
        handoffs=[
            HandoffSpec(source="TestAgent", target="BillingAgent"),
            HandoffSpec(source="TestAgent", target="TechSupport", condition="technical issue"),
        ],
        mcp_servers=[
            McpServerRef(name="docs_server", config={"command": "npx", "args": ["docs"]}),
        ],
        environment=EnvironmentConfig(model="gpt-4", provider="openai-agents"),
        example_traces=[{"id": "trace-1"}],
        metadata={"adapter": "openai-agents", "source": "/tmp/test"},
    )


# ---------------------------------------------------------------------------
# CanonicalAgent type tests
# ---------------------------------------------------------------------------


class TestCanonicalAgentTypes:
    """Test the IR type definitions themselves."""

    def test_create_minimal_agent(self) -> None:
        agent = CanonicalAgent(name="minimal")
        assert agent.name == "minimal"
        assert agent.tools == []
        assert agent.instructions == []
        assert agent.guardrails == []
        assert agent.handoffs == []
        assert agent.sub_agents == []
        assert agent.environment.model == ""

    def test_create_full_agent(self, sample_canonical: CanonicalAgent) -> None:
        assert sample_canonical.name == "TestAgent"
        assert len(sample_canonical.tools) == 2
        assert len(sample_canonical.handoffs) == 2
        assert sample_canonical.environment.model == "gpt-4"

    def test_tool_names(self, sample_canonical: CanonicalAgent) -> None:
        assert sample_canonical.tool_names() == ["lookup_order", "search_faq"]

    def test_guardrail_names(self, sample_canonical: CanonicalAgent) -> None:
        assert sample_canonical.guardrail_names() == ["pii_filter"]

    def test_handoff_targets(self, sample_canonical: CanonicalAgent) -> None:
        assert sample_canonical.handoff_targets() == ["BillingAgent", "TechSupport"]

    def test_primary_instruction(self, sample_canonical: CanonicalAgent) -> None:
        assert "helpful support agent" in sample_canonical.primary_instruction()

    def test_flatten_instructions(self) -> None:
        agent = CanonicalAgent(
            name="multi",
            instructions=[
                Instruction(content="Low priority", priority=10),
                Instruction(content="High priority", priority=100),
                Instruction(content="Medium priority", priority=50),
            ],
        )
        flat = agent.flatten_instructions()
        assert flat.startswith("High priority")
        assert "Medium priority" in flat
        assert flat.endswith("Low priority")

    def test_sub_agents_recursive(self) -> None:
        child_tool = ToolContract(name="child_tool", description="Child tool")
        child = CanonicalAgent(name="child", tools=[child_tool])
        parent_tool = ToolContract(name="parent_tool", description="Parent tool")
        parent = CanonicalAgent(name="parent", tools=[parent_tool], sub_agents=[child])

        all_tools = parent.all_tools_recursive()
        assert len(all_tools) == 2
        assert [t.name for t in all_tools] == ["parent_tool", "child_tool"]

    def test_sub_agent_names(self) -> None:
        child1 = CanonicalAgent(name="billing")
        child2 = CanonicalAgent(name="support")
        parent = CanonicalAgent(name="root", sub_agents=[child1, child2])
        assert parent.sub_agent_names() == ["billing", "support"]

    def test_serialization_round_trip(self, sample_canonical: CanonicalAgent) -> None:
        dumped = sample_canonical.model_dump()
        restored = CanonicalAgent.model_validate(dumped)
        assert restored.name == sample_canonical.name
        assert len(restored.tools) == len(sample_canonical.tools)
        assert restored.tools[0].name == "lookup_order"
        assert restored.tools[0].parameters[0].name == "order_id"
        assert restored.environment.model == "gpt-4"

    def test_json_round_trip(self, sample_canonical: CanonicalAgent) -> None:
        json_str = sample_canonical.model_dump_json()
        restored = CanonicalAgent.model_validate_json(json_str)
        assert restored.name == sample_canonical.name
        assert len(restored.handoffs) == 2

    def test_extra_fields_allowed(self) -> None:
        agent = CanonicalAgent(name="extra", custom_field="preserved")
        dumped = agent.model_dump()
        assert dumped["custom_field"] == "preserved"

    def test_tool_parameter_enum(self) -> None:
        param = ToolParameter(
            name="status", type="string", enum=["active", "inactive"],
        )
        assert param.enum == ["active", "inactive"]


# ---------------------------------------------------------------------------
# ImportedAgentSpec → CanonicalAgent
# ---------------------------------------------------------------------------


class TestFromImportedSpec:
    """Test conversion from ImportedAgentSpec to CanonicalAgent."""

    def test_basic_conversion(self, sample_spec) -> None:
        agent = from_imported_spec(sample_spec)
        assert agent.name == "TestAgent"
        assert agent.platform_origin == "OpenAI Agents"

    def test_instructions_converted(self, sample_spec) -> None:
        agent = from_imported_spec(sample_spec)
        assert len(agent.instructions) == 1
        assert agent.instructions[0].role == InstructionRole.SYSTEM
        assert "helpful support agent" in agent.instructions[0].content
        assert agent.instructions[0].priority == 100
        assert agent.instructions[0].label == "root"

    def test_tools_converted_with_parameters(self, sample_spec) -> None:
        agent = from_imported_spec(sample_spec)
        assert len(agent.tools) == 2

        lookup = agent.tools[0]
        assert lookup.name == "lookup_order"
        assert lookup.description == "Look up order status by ID"
        assert len(lookup.parameters) == 1
        assert lookup.parameters[0].name == "order_id"
        assert lookup.parameters[0].type == "string"
        assert lookup.parameters[0].required is True

        faq = agent.tools[1]
        assert faq.name == "search_faq"
        assert faq.parameters == []

    def test_tools_from_input_schema(self) -> None:
        spec = _make_imported_spec(tools=[
            {
                "name": "create_ticket",
                "description": "Create support ticket",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Ticket title"},
                        "priority": {"type": "integer", "description": "Priority 1-5"},
                    },
                    "required": ["title"],
                },
            }
        ])
        agent = from_imported_spec(spec)
        tool = agent.tools[0]
        assert len(tool.parameters) == 2
        title_param = next(p for p in tool.parameters if p.name == "title")
        assert title_param.required is True
        assert title_param.type == "string"
        priority_param = next(p for p in tool.parameters if p.name == "priority")
        assert priority_param.required is False

    def test_guardrails_converted(self, sample_spec) -> None:
        agent = from_imported_spec(sample_spec)
        assert len(agent.guardrails) == 2
        pii = agent.guardrails[0]
        assert pii.name == "pii_filter"
        assert pii.type == GuardrailType.OUTPUT
        assert pii.description == "Block PII in output"

        tone = agent.guardrails[1]
        assert tone.name == "tone_check"
        assert tone.type == GuardrailType.BOTH

    def test_handoffs_converted(self, sample_spec) -> None:
        agent = from_imported_spec(sample_spec)
        assert len(agent.handoffs) == 2
        assert agent.handoffs[0].source == "TestAgent"
        assert agent.handoffs[0].target == "BillingAgent"
        assert agent.handoffs[1].condition == "technical issue"

    def test_mcp_servers_converted(self, sample_spec) -> None:
        agent = from_imported_spec(sample_spec)
        assert len(agent.mcp_servers) == 1
        assert agent.mcp_servers[0].name == "docs_server"
        assert agent.mcp_servers[0].config["command"] == "npx"

    def test_routing_rules_inferred_from_handoffs(self, sample_spec) -> None:
        agent = from_imported_spec(sample_spec)
        assert len(agent.routing_rules) >= 2
        targets = [r.target for r in agent.routing_rules]
        assert "BillingAgent" in targets
        assert "TechSupport" in targets

    def test_environment_extracted(self, sample_spec) -> None:
        agent = from_imported_spec(sample_spec)
        assert agent.environment.model == "gpt-4"

    def test_traces_preserved(self, sample_spec) -> None:
        agent = from_imported_spec(sample_spec)
        assert len(agent.example_traces) == 1
        assert agent.example_traces[0]["id"] == "trace-1"

    def test_fidelity_notes_attached(self, sample_spec) -> None:
        agent = from_imported_spec(sample_spec)
        assert len(agent.fidelity_notes) > 0
        fields = [n.field for n in agent.fidelity_notes]
        assert "instructions" in fields
        assert "tools" in fields
        assert "handoffs" in fields

    def test_to_canonical_method_on_spec(self, sample_spec) -> None:
        agent = sample_spec.to_canonical()
        assert isinstance(agent, CanonicalAgent)
        assert agent.name == "TestAgent"
        assert len(agent.tools) == 2


# ---------------------------------------------------------------------------
# CanonicalAgent → config dict
# ---------------------------------------------------------------------------


class TestToConfigDict:
    """Test conversion from CanonicalAgent to AgentLab config dict."""

    def test_prompts_mapped(self, sample_canonical: CanonicalAgent) -> None:
        config = to_config_dict(sample_canonical)
        assert config["prompts"]["root"] == "You are a helpful support agent."

    def test_tools_config_mapped(self, sample_canonical: CanonicalAgent) -> None:
        config = to_config_dict(sample_canonical)
        assert "tools_config" in config
        assert "lookup_order" in config["tools_config"]
        assert config["tools_config"]["lookup_order"]["enabled"] is True
        assert "parameters" in config["tools_config"]["lookup_order"]
        assert len(config["tools_config"]["lookup_order"]["parameters"]) == 1

    def test_routing_rules_mapped(self, sample_canonical: CanonicalAgent) -> None:
        config = to_config_dict(sample_canonical)
        assert "routing" in config
        rules = config["routing"]["rules"]
        specialists = [r["specialist"] for r in rules]
        assert "BillingAgent" in specialists

    def test_guardrails_mapped(self, sample_canonical: CanonicalAgent) -> None:
        config = to_config_dict(sample_canonical)
        assert "guardrails" in config
        assert config["guardrails"][0]["name"] == "pii_filter"
        assert config["guardrails"][0]["type"] == "output"

    def test_handoffs_mapped(self, sample_canonical: CanonicalAgent) -> None:
        config = to_config_dict(sample_canonical)
        assert "handoffs" in config
        assert len(config["handoffs"]) == 2
        assert config["handoffs"][0]["target"] == "BillingAgent"

    def test_model_mapped(self, sample_canonical: CanonicalAgent) -> None:
        config = to_config_dict(sample_canonical)
        assert config["model"] == "gpt-4"

    def test_mcp_servers_mapped(self, sample_canonical: CanonicalAgent) -> None:
        config = to_config_dict(sample_canonical)
        assert "mcp_servers" in config
        assert config["mcp_servers"][0]["name"] == "docs_server"

    def test_sub_agents_flattened_to_routing_and_prompts(self) -> None:
        child = CanonicalAgent(
            name="billing",
            instructions=[Instruction(content="Handle billing", priority=100, label="root")],
        )
        parent = CanonicalAgent(
            name="root",
            instructions=[Instruction(content="Route requests", priority=100, label="root")],
            sub_agents=[child],
        )
        config = to_config_dict(parent)
        assert config["prompts"]["billing"] == "Handle billing"
        specialists = [r["specialist"] for r in config["routing"]["rules"]]
        assert "billing" in specialists

    def test_empty_agent_produces_minimal_config(self) -> None:
        agent = CanonicalAgent(name="empty")
        config = to_config_dict(agent)
        assert "tools_config" not in config
        assert "guardrails" not in config
        assert "handoffs" not in config


# ---------------------------------------------------------------------------
# config dict → CanonicalAgent
# ---------------------------------------------------------------------------


class TestFromConfigDict:
    """Test reconstruction from persisted config dict."""

    def test_basic_round_trip(self, sample_canonical: CanonicalAgent) -> None:
        config = to_config_dict(sample_canonical)
        restored = from_config_dict(config, name="TestAgent")
        assert restored.name == "TestAgent"
        assert restored.primary_instruction() == "You are a helpful support agent."

    def test_tools_restored_with_parameters(self, sample_canonical: CanonicalAgent) -> None:
        config = to_config_dict(sample_canonical)
        restored = from_config_dict(config)
        lookup = next(t for t in restored.tools if t.name == "lookup_order")
        assert len(lookup.parameters) == 1
        assert lookup.parameters[0].name == "order_id"

    def test_guardrails_restored(self, sample_canonical: CanonicalAgent) -> None:
        config = to_config_dict(sample_canonical)
        restored = from_config_dict(config)
        assert len(restored.guardrails) == 1
        assert restored.guardrails[0].name == "pii_filter"
        assert restored.guardrails[0].type == GuardrailType.OUTPUT

    def test_legacy_tools_loaded(self) -> None:
        config = {
            "tools": {
                "catalog": {"enabled": True, "timeout_ms": 5000},
                "orders_db": {"enabled": True, "timeout_ms": 3000, "description": "Order DB"},
            }
        }
        agent = from_config_dict(config)
        assert len(agent.tools) == 2
        orders = next(t for t in agent.tools if t.name == "orders_db")
        assert orders.description == "Order DB"

    def test_guardrails_from_string_list(self) -> None:
        config = {"guardrails": ["pii_filter", "profanity_check"]}
        agent = from_config_dict(config)
        assert len(agent.guardrails) == 2
        assert agent.guardrails[0].name == "pii_filter"

    def test_fidelity_notes_on_legacy_tools(self) -> None:
        config = {
            "tools": {"my_tool": {"enabled": True}},
        }
        agent = from_config_dict(config)
        tool_notes = [n for n in agent.fidelity_notes if n.field == "tools"]
        assert tool_notes[0].status == FidelityStatus.APPROXIMATED

    def test_fidelity_notes_on_new_tools(self) -> None:
        config = {
            "tools_config": {
                "my_tool": {"description": "A tool", "parameters": [{"name": "x"}]},
            },
        }
        agent = from_config_dict(config)
        tool_notes = [n for n in agent.fidelity_notes if n.field == "tools"]
        assert tool_notes[0].status == FidelityStatus.FAITHFUL


# ---------------------------------------------------------------------------
# CanonicalAgent → ImportedAgentSpec (downgrade)
# ---------------------------------------------------------------------------


class TestToImportedSpec:
    """Test downgrade from CanonicalAgent to ImportedAgentSpec dict."""

    def test_system_prompts_preserved(self, sample_canonical: CanonicalAgent) -> None:
        spec_dict = to_imported_spec(sample_canonical)
        assert spec_dict["system_prompts"] == ["You are a helpful support agent."]

    def test_tools_preserved(self, sample_canonical: CanonicalAgent) -> None:
        spec_dict = to_imported_spec(sample_canonical)
        assert len(spec_dict["tools"]) == 2
        assert spec_dict["tools"][0]["name"] == "lookup_order"
        assert "parameters" in spec_dict["tools"][0]

    def test_guardrails_preserved(self, sample_canonical: CanonicalAgent) -> None:
        spec_dict = to_imported_spec(sample_canonical)
        assert len(spec_dict["guardrails"]) == 1
        assert spec_dict["guardrails"][0]["name"] == "pii_filter"

    def test_handoffs_preserved(self, sample_canonical: CanonicalAgent) -> None:
        spec_dict = to_imported_spec(sample_canonical)
        assert len(spec_dict["handoffs"]) == 2
        assert spec_dict["handoffs"][0]["target"] == "BillingAgent"

    def test_config_included(self, sample_canonical: CanonicalAgent) -> None:
        spec_dict = to_imported_spec(sample_canonical)
        assert "prompts" in spec_dict["config"]
        assert "tools_config" in spec_dict["config"]


# ---------------------------------------------------------------------------
# Full round-trip: ImportedAgentSpec → CanonicalAgent → config dict → CanonicalAgent
# ---------------------------------------------------------------------------


class TestFullRoundTrip:
    """Test the full conversion chain for information preservation."""

    def test_spec_to_canonical_to_config_to_canonical(self, sample_spec) -> None:
        canonical1 = from_imported_spec(sample_spec)
        config = to_config_dict(canonical1)
        canonical2 = from_config_dict(config, name=canonical1.name)

        assert canonical2.name == canonical1.name
        assert canonical2.primary_instruction() == canonical1.primary_instruction()
        assert len(canonical2.tools) == len(canonical1.tools)
        assert canonical2.tools[0].name == canonical1.tools[0].name
        assert len(canonical2.tools[0].parameters) == len(canonical1.tools[0].parameters)
        assert canonical2.environment.model == canonical1.environment.model

    def test_tool_parameters_survive_round_trip(self) -> None:
        spec = _make_imported_spec(tools=[
            {
                "name": "calculate",
                "description": "Math calculator",
                "parameters": [
                    {"name": "expression", "type": "string", "required": True},
                    {"name": "precision", "type": "integer", "required": False, "default": 2},
                ],
            }
        ])
        canonical1 = from_imported_spec(spec)
        config = to_config_dict(canonical1)
        canonical2 = from_config_dict(config)

        tool = canonical2.tools[0]
        assert tool.name == "calculate"
        assert len(tool.parameters) == 2
        assert tool.parameters[0].name == "expression"
        assert tool.parameters[0].required is True
        assert tool.parameters[1].name == "precision"

    def test_guardrails_survive_round_trip(self) -> None:
        spec = _make_imported_spec(guardrails=[
            {"name": "pii_filter", "description": "Block PII", "type": "output",
             "enforcement": "block"},
        ])
        canonical1 = from_imported_spec(spec)
        config = to_config_dict(canonical1)
        canonical2 = from_config_dict(config)

        g = canonical2.guardrails[0]
        assert g.name == "pii_filter"
        assert g.type == GuardrailType.OUTPUT
        assert g.enforcement == GuardrailEnforcement.BLOCK
        assert g.description == "Block PII"


# ---------------------------------------------------------------------------
# Adapter integration tests
# ---------------------------------------------------------------------------


class TestOpenAIAdapterCanonical:
    """Test OpenAI Agents adapter produces enriched canonical IR."""

    def test_discover_and_convert(self, tmp_path: Path) -> None:
        source = tmp_path / "agent.py"
        source.write_text(
            """
from agents import Agent, function_tool

@function_tool
def lookup_order(order_id: str) -> str:
    \"\"\"Return order status.\"\"\"
    return "shipped"

billing_agent = Agent(name="Billing", instructions="Handle invoices and payments.")
support_agent = Agent(
    name="Support",
    instructions="Help customers with orders and refunds.",
    tools=[lookup_order],
    handoffs=[billing_agent],
)
""".strip(),
            encoding="utf-8",
        )

        from adapters.openai_agents import OpenAIAgentsAdapter

        spec = OpenAIAgentsAdapter(str(tmp_path)).discover()
        agent = spec.to_canonical()

        assert isinstance(agent, CanonicalAgent)
        assert agent.name == "Support"
        assert len(agent.tools) >= 1

        lookup = next(t for t in agent.tools if t.name == "lookup_order")
        assert lookup.description == "Return order status."
        assert len(lookup.parameters) == 1
        assert lookup.parameters[0].name == "order_id"
        assert lookup.parameters[0].type == "str"

        assert len(agent.handoffs) >= 1
        assert agent.handoffs[0].target == "Billing"

    def test_fidelity_notes_present(self, tmp_path: Path) -> None:
        source = tmp_path / "agent.py"
        source.write_text(
            """
from agents import Agent
agent = Agent(name="Simple", instructions="A simple agent.")
""".strip(),
            encoding="utf-8",
        )

        from adapters.openai_agents import OpenAIAgentsAdapter

        spec = OpenAIAgentsAdapter(str(tmp_path)).discover()
        agent = spec.to_canonical()
        assert any(n.field == "instructions" for n in agent.fidelity_notes)


class TestAnthropicAdapterCanonical:
    """Test Anthropic adapter produces enriched canonical IR."""

    def test_discover_and_convert(self, tmp_path: Path) -> None:
        source = tmp_path / "app.py"
        source.write_text(
            """
import anthropic

SYSTEM_PROMPT = "You are a careful assistant."
TOOLS = [{"name": "lookup_faq", "description": "Search FAQ",
          "input_schema": {
              "type": "object",
              "properties": {"query": {"type": "string", "description": "Search query"}},
              "required": ["query"]
          }}]

def check_guardrail(text: str) -> bool:
    return "override" not in text
""".strip(),
            encoding="utf-8",
        )

        from adapters.anthropic_claude import AnthropicClaudeAdapter

        spec = AnthropicClaudeAdapter(str(tmp_path)).discover()
        agent = spec.to_canonical()

        assert isinstance(agent, CanonicalAgent)
        assert "careful assistant" in agent.primary_instruction()
        assert len(agent.tools) >= 1

        faq_tool = next(t for t in agent.tools if t.name == "lookup_faq")
        assert len(faq_tool.parameters) == 1
        assert faq_tool.parameters[0].name == "query"
        assert faq_tool.parameters[0].required is True


class TestTranscriptAdapterCanonical:
    """Test transcript adapter → canonical conversion."""

    def test_discover_and_convert(self, tmp_path: Path) -> None:
        transcript_file = tmp_path / "conversations.jsonl"
        transcript_file.write_text(
            json.dumps({
                "id": "conv-1",
                "messages": [
                    {"role": "user", "content": "Where is my order?"},
                    {"role": "assistant", "content": "Checking.", "tool_calls": [{"name": "lookup"}]},
                ],
            }),
            encoding="utf-8",
        )

        from adapters.transcript import TranscriptAdapter

        spec = TranscriptAdapter(str(transcript_file)).discover()
        agent = spec.to_canonical()

        assert isinstance(agent, CanonicalAgent)
        assert len(agent.tools) == 1
        assert agent.tools[0].name == "lookup"
        assert len(agent.example_traces) == 1


# ---------------------------------------------------------------------------
# AgentConfig integration
# ---------------------------------------------------------------------------


class TestAgentConfigIntegration:
    """Test AgentConfig ↔ CanonicalAgent conversions."""

    def test_agent_config_to_canonical(self) -> None:
        from agent.config.schema import AgentConfig, GuardrailConfig

        config = AgentConfig(
            model="gpt-4",
            guardrails=[GuardrailConfig(name="pii_filter", type="output")],
            tools_config={
                "my_tool": {"description": "A tool", "enabled": True},
            },
        )
        agent = config.to_canonical(name="test-agent")
        assert agent.name == "test-agent"
        assert agent.environment.model == "gpt-4"
        assert len(agent.guardrails) == 1
        assert agent.guardrails[0].name == "pii_filter"

    def test_canonical_to_agent_config(self, sample_canonical: CanonicalAgent) -> None:
        from agent.config.schema import AgentConfig

        config = AgentConfig.from_canonical(sample_canonical)
        assert isinstance(config, AgentConfig)
        assert config.model == "gpt-4"
        assert "lookup_order" in config.tools_config
        assert len(config.guardrails) == 1


# ---------------------------------------------------------------------------
# ADK → CanonicalAgent
# ---------------------------------------------------------------------------


class TestAdkCanonical:
    """Test ADK mapper canonical IR conversion."""

    def test_adk_tree_to_canonical(self) -> None:
        from adk.types import AdkAgent, AdkAgentTree, AdkTool

        child_agent = AdkAgent(name="billing", instruction="Handle billing")
        child_tree = AdkAgentTree(
            agent=child_agent,
            tools=[],
            sub_agents=[],
            config={},
        )

        root_agent = AdkAgent(
            name="support",
            instruction="Help customers",
            model="gemini-2.0-flash",
            generate_config={"temperature": 0.3},
        )
        root_tree = AdkAgentTree(
            agent=root_agent,
            tools=[
                AdkTool(
                    name="lookup_order",
                    description="Look up order",
                    signature="lookup_order(order_id: str)",
                ),
            ],
            sub_agents=[child_tree],
            config={"model": "gemini-2.0-flash"},
        )

        agent = from_adk_tree(root_tree)

        assert isinstance(agent, CanonicalAgent)
        assert agent.name == "support"
        assert agent.platform_origin == "adk"
        assert "Help customers" in agent.primary_instruction()
        assert len(agent.tools) == 1
        assert agent.tools[0].name == "lookup_order"
        assert len(agent.tools[0].parameters) == 1
        assert agent.tools[0].parameters[0].name == "order_id"
        assert len(agent.sub_agents) == 1
        assert agent.sub_agents[0].name == "billing"
        assert agent.environment.model == "gemini-2.0-flash"
        assert agent.environment.temperature == 0.3

    def test_adk_mapper_to_canonical(self) -> None:
        from adk.mapper import AdkMapper
        from adk.types import AdkAgent, AdkAgentTree, AdkTool

        tree = AdkAgentTree(
            agent=AdkAgent(name="test", instruction="Test agent"),
            tools=[AdkTool(name="tool1", description="Tool 1")],
            sub_agents=[],
            config={},
        )

        mapper = AdkMapper()
        agent = mapper.to_canonical(tree)

        assert isinstance(agent, CanonicalAgent)
        assert agent.name == "test"
        assert len(agent.tools) == 1

    def test_adk_callbacks_become_policies(self) -> None:
        from adk.types import AdkAgent, AdkAgentTree, AdkCallbackSpec

        tree = AdkAgentTree(
            agent=AdkAgent(name="agent_with_callbacks"),
            tools=[],
            callbacks=[
                AdkCallbackSpec(
                    name="rate_limiter",
                    callback_type="before_model",
                    function_name="check_rate_limit",
                    description="Rate limit API calls",
                ),
            ],
            sub_agents=[],
            config={},
        )

        agent = from_adk_tree(tree)
        assert len(agent.policies) == 1
        assert agent.policies[0].name == "check_rate_limit"
        assert agent.policies[0].type == PolicyType.OPERATIONAL


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Test handling of edge cases and malformed data."""

    def test_empty_spec(self) -> None:
        spec = _make_imported_spec(
            system_prompts=[],
            tools=[],
            guardrails=[],
            handoffs=[],
            mcp_refs=[],
            traces=[],
            config={},
            metadata={},
        )
        agent = from_imported_spec(spec)
        assert agent.name == "TestAgent"
        assert agent.instructions == []
        assert agent.tools == []

    def test_tools_without_names_skipped(self) -> None:
        spec = _make_imported_spec(tools=[
            {"description": "No name"},
            {"name": "", "description": "Empty name"},
            {"name": "valid_tool", "description": "Has a name"},
        ])
        agent = from_imported_spec(spec)
        assert len(agent.tools) == 1
        assert agent.tools[0].name == "valid_tool"

    def test_unknown_enum_values_fall_back(self) -> None:
        spec = _make_imported_spec(guardrails=[
            {"name": "test", "type": "unknown_type", "enforcement": "unknown_enforcement"},
        ])
        agent = from_imported_spec(spec)
        assert agent.guardrails[0].type == GuardrailType.BOTH
        assert agent.guardrails[0].enforcement == GuardrailEnforcement.BLOCK

    def test_xml_instruction_detected(self) -> None:
        spec = _make_imported_spec(
            system_prompts=["<instructions>\n<role>You are an agent</role>\n</instructions>"],
        )
        agent = from_imported_spec(spec)
        assert agent.instructions[0].format == InstructionFormat.XML

    def test_config_dict_with_generation_settings(self) -> None:
        config = {
            "model": "claude-3-opus",
            "generation": {"temperature": 0.7, "max_tokens": 4096},
        }
        agent = from_config_dict(config)
        assert agent.environment.model == "claude-3-opus"
        assert agent.environment.temperature == 0.7
        assert agent.environment.max_tokens == 4096
