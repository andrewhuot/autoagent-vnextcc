"""Tests for ADK mapper."""
from __future__ import annotations

import pytest

from adk.mapper import AdkMapper
from adk.parser import parse_agent_directory
from adk.types import AdkAgent, AdkAgentTree, AdkTool


@pytest.fixture
def sample_agent_path(tmp_path):
    """Return path to sample ADK agent fixture."""
    from pathlib import Path
    return Path(__file__).parent / "fixtures" / "sample_adk_agent"


@pytest.fixture
def sample_tree(sample_agent_path):
    """Parse sample agent into tree."""
    return parse_agent_directory(sample_agent_path)


@pytest.fixture
def mapper():
    """Create AdkMapper instance."""
    return AdkMapper()


def test_to_agentlab_basic(mapper, sample_tree):
    """Test basic ADK to AgentLab mapping."""
    config = mapper.to_agentlab(sample_tree)

    assert "prompts" in config
    assert "tools" in config
    assert "routing" in config
    assert "_adk_metadata" in config

    # Check root prompt was mapped
    assert "root" in config["prompts"]
    assert "support" in config["prompts"]["root"].lower()


def test_to_agentlab_with_subagents(mapper, sample_tree):
    """Test hierarchy flattened to prompts + routing."""
    config = mapper.to_agentlab(sample_tree)

    # Sub-agent instruction should be in prompts
    assert "billing_agent" in config["prompts"]
    assert "billing specialist" in config["prompts"]["billing_agent"].lower()

    # Routing rules should be derived
    assert "rules" in config["routing"]
    assert len(config["routing"]["rules"]) > 0

    # Check routing rule for billing
    billing_rule = None
    for rule in config["routing"]["rules"]:
        if rule["specialist"] == "billing_agent":
            billing_rule = rule
            break

    assert billing_rule is not None
    assert "billing" in billing_rule["keywords"]


def test_to_agentlab_with_tools(mapper, sample_tree):
    """Test tool docstrings extracted."""
    config = mapper.to_agentlab(sample_tree)

    assert "tools" in config
    assert len(config["tools"]) > 0

    # Check a specific tool
    assert "lookup_order" in config["tools"]
    tool_config = config["tools"]["lookup_order"]
    assert tool_config["enabled"] is True
    assert "order" in tool_config["description"].lower()
    assert "signature" in tool_config


def test_to_agentlab_with_config(mapper, sample_tree):
    """Test generation settings mapped."""
    config = mapper.to_agentlab(sample_tree)

    # Check model
    assert "model" in config
    assert config["model"] == "gemini-2.0-flash"

    # Check generation settings
    assert "generation" in config
    assert config["generation"]["temperature"] == 0.3
    assert config["generation"]["max_tokens"] == 1024


def test_to_adk_roundtrip(mapper, sample_tree):
    """Test config → tree → config preserves data."""
    # Convert to config
    config1 = mapper.to_agentlab(sample_tree)

    # Convert back to tree
    tree2 = mapper.to_adk(config1, sample_tree)

    # Convert to config again
    config2 = mapper.to_agentlab(tree2)

    # Should preserve key fields
    assert config1["prompts"]["root"] == config2["prompts"]["root"]
    assert config1["model"] == config2["model"]
    assert len(config1["tools"]) == len(config2["tools"])


def test_apply_prompts_updates_instructions(mapper, sample_tree):
    """Test applying updated prompts to tree."""
    config = {
        "prompts": {
            "root": "Updated root instruction",
            "billing_agent": "Updated billing instruction",
        }
    }

    updated_tree = mapper.to_adk(config, sample_tree)

    assert updated_tree.agent.instruction == "Updated root instruction"
    assert updated_tree.sub_agents[0].agent.instruction == "Updated billing instruction"


def test_metadata_preserved(mapper, sample_tree):
    """Test _adk_metadata stored."""
    config = mapper.to_agentlab(sample_tree)

    assert "_adk_metadata" in config
    metadata = config["_adk_metadata"]
    assert "agent_name" in metadata
    assert "source_path" in metadata
    assert "agent_tree" in metadata


def test_derive_keywords_from_name(mapper):
    """Test keyword derivation from agent name."""
    keywords = mapper._derive_keywords_from_name("billing_agent")
    assert "billing" in keywords

    keywords = mapper._derive_keywords_from_name("support")
    assert "support" in keywords
    assert "help" in keywords


def test_map_routing_creates_rules(mapper):
    """Test routing rules created for sub-agents."""
    sub_tree = AdkAgentTree(
        agent=AdkAgent(name="billing_agent", instruction="Billing help"),
        tools=[],
        sub_agents=[],
        config={},
    )

    routing = mapper._map_routing([sub_tree])

    assert "rules" in routing
    assert len(routing["rules"]) == 1
    assert routing["rules"][0]["specialist"] == "billing_agent"


def test_extract_generation_settings(mapper):
    """Test generation settings extraction."""
    tree = AdkAgentTree(
        agent=AdkAgent(
            name="test",
            generate_config={"temperature": 0.5, "max_output_tokens": 512}
        ),
        tools=[],
        sub_agents=[],
        config={"temperature": 0.3},  # Should be overridden by agent config
    )

    settings = mapper._extract_generation_settings(tree)
    assert settings["temperature"] == 0.5
    assert settings["max_tokens"] == 512


def test_map_tools_includes_metadata(mapper):
    """Test tool mapping includes function body reference."""
    tool = AdkTool(
        name="test_tool",
        description="Test tool",
        signature="test_tool(arg1, arg2)",
        function_body="def test_tool(arg1, arg2):\n    return arg1 + arg2",
    )

    tools_config = mapper._map_tools([tool])

    assert "test_tool" in tools_config
    assert tools_config["test_tool"]["description"] == "Test tool"
    assert "_adk_function_body" in tools_config["test_tool"]


def test_apply_generation_settings(mapper, sample_tree):
    """Test applying generation settings to tree."""
    config = {
        "generation": {
            "temperature": 0.7,
            "max_tokens": 2048,
        }
    }

    updated_tree = mapper.to_adk(config, sample_tree)

    assert updated_tree.agent.generate_config["temperature"] == 0.7
    assert updated_tree.agent.generate_config["max_output_tokens"] == 2048


def test_to_agentlab_projects_cx_native_contract(mapper, sample_tree):
    """ADK imports should produce a best-effort CX-native editable contract."""
    config = mapper.to_agentlab(sample_tree)

    assert "cx" in config

    cx = config["cx"]
    assert cx["source_platform"] == "adk"
    assert cx["target_platform"] == "cx_agent_studio"
    assert cx["projection_summary"]["faithful_count"] >= 2
    assert cx["projection_summary"]["approximated_count"] >= 2

    assert "support_agent" in cx["playbooks"]
    assert cx["playbooks"]["support_agent"]["projection"]["quality"] == "faithful"

    assert "support_agent_router" in cx["flows"]
    assert cx["flows"]["support_agent_router"]["projection"]["quality"] == "approximated"

    assert "billing_agent" in cx["intents"]
    assert cx["intents"]["billing_agent"]["projection"]["quality"] == "approximated"

    assert cx["preserved"]["tools"][0]["name"] == "lookup_order"
