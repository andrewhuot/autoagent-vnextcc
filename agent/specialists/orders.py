"""Order management specialist agent."""

from __future__ import annotations

from google.adk.agents import Agent

from agent.config.schema import AgentConfig
from agent.tools.catalog import get_product, search_catalog
from agent.tools.orders_db import get_order, list_orders, update_order_status


def create_orders_agent(config: AgentConfig) -> Agent:
    """Create an order management specialist ADK agent.

    Args:
        config: Agent configuration with system prompts and tool settings.

    Returns:
        Configured ADK Agent for order management.
    """
    tools = []
    if config.tools.orders_db.enabled:
        tools.extend([get_order, list_orders, update_order_status])
    if config.tools.catalog.enabled:
        tools.extend([search_catalog, get_product])

    return Agent(
        name="orders",
        model=config.model,
        instruction=config.prompts.orders,
        tools=tools,
    )
