"""Agent Card: standardized, human-readable representation of an agent.

An Agent Card captures ALL agent data — instructions, tools, callbacks,
routing, guardrails, policies, sub-agents — in a single markdown-based
format that is both human-readable and machine-parseable.

No matter the source framework (Google ADK, CX Agent Studio, OpenAI Agents),
the Agent Card is the standardized object that AgentLab reasons over for
building, evaluation, and optimization.
"""

from .schema import AgentCardModel, CallbackEntry, SubAgentSection, ToolEntry
from .renderer import render_to_markdown, parse_from_markdown
from .converter import (
    from_canonical_agent,
    to_canonical_agent,
    from_config_dict,
    to_config_dict,
    from_adk_tree,
)
from .persistence import (
    card_exists,
    default_card_path,
    diff_with_version,
    generate_and_save_from_adk,
    generate_and_save_from_config,
    list_history,
    load_card,
    load_card_markdown,
    save_card,
)

__all__ = [
    "AgentCardModel",
    "CallbackEntry",
    "SubAgentSection",
    "ToolEntry",
    "render_to_markdown",
    "parse_from_markdown",
    "from_canonical_agent",
    "to_canonical_agent",
    "from_config_dict",
    "to_config_dict",
    "from_adk_tree",
    "card_exists",
    "default_card_path",
    "diff_with_version",
    "generate_and_save_from_adk",
    "generate_and_save_from_config",
    "list_history",
    "load_card",
    "load_card_markdown",
    "save_card",
]
