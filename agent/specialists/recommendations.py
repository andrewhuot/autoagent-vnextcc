"""Product recommendation specialist agent."""

from __future__ import annotations

from google.adk.agents import Agent

from agent.config.schema import AgentConfig
from agent.tools.catalog import get_product, search_catalog


def create_recommendations_agent(config: AgentConfig) -> Agent:
    """Create a product recommendation specialist ADK agent.

    Args:
        config: Agent configuration with system prompts and tool settings.

    Returns:
        Configured ADK Agent for product recommendations.
    """
    tools = []
    if config.tools.catalog.enabled:
        tools.extend([search_catalog, get_product])

    return Agent(
        name="recommendations",
        model=config.model,
        instruction=config.prompts.recommendations,
        tools=tools,
    )
