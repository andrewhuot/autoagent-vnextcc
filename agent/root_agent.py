"""Root ADK agent with keyword-based routing to specialists."""

from __future__ import annotations
from google.adk.agents import Agent

from agent.config.schema import AgentConfig
from agent.specialists.orders import create_orders_agent
from agent.specialists.recommendations import create_recommendations_agent
from agent.specialists.support import create_support_agent


def _build_routing_instruction(config: AgentConfig) -> str:
    """Build a routing-aware system prompt from config."""
    base = config.prompts.root.strip()

    routing_hints: list[str] = []
    for rule in config.routing.rules:
        keywords = ", ".join(rule.keywords[:5])
        patterns = ", ".join(f'"{p}"' for p in rule.patterns[:3])
        routing_hints.append(
            f"- Route to **{rule.specialist}** when the user mentions: {keywords}. "
            f"Common phrases: {patterns}."
        )

    if routing_hints:
        hints_block = "\n".join(routing_hints)
        base += (
            f"\n\nRouting guidelines:\n{hints_block}\n\n"
            "If the request doesn't clearly match a specialist, ask a clarifying question. "
            "Transfer to the appropriate specialist using transfer_to_<name>."
        )

    return base


def create_root_agent(config: AgentConfig) -> Agent:
    """Create the root orchestrator ADK agent with specialist sub-agents.

    Args:
        config: Validated agent configuration.

    Returns:
        Root ADK Agent configured with sub-agents for routing.
    """
    support = create_support_agent(config)
    orders = create_orders_agent(config)
    recommendations = create_recommendations_agent(config)

    instruction = _build_routing_instruction(config)

    root = Agent(
        name="root_agent",
        model=config.model,
        instruction=instruction,
        sub_agents=[support, orders, recommendations],
    )

    return root
