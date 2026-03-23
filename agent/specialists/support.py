"""Customer support specialist agent."""

from __future__ import annotations

from google.adk.agents import Agent

from agent.config.schema import AgentConfig
from agent.tools.catalog import get_product, search_catalog
from agent.tools.faq import search_faq


def create_support_agent(config: AgentConfig) -> Agent:
    """Create a customer support specialist ADK agent.

    Args:
        config: Agent configuration with system prompts and tool settings.

    Returns:
        Configured ADK Agent for customer support.
    """
    tools = []
    if config.tools.catalog.enabled:
        tools.extend([search_catalog, get_product])
    if config.tools.faq.enabled:
        tools.append(search_faq)

    return Agent(
        name="support",
        model=config.model,
        instruction=config.prompts.support,
        tools=tools,
    )
