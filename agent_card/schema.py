"""Agent Card Pydantic schema.

The Agent Card is the standardized, human-readable representation of an agent
that AgentLab uses for building, evaluation, and optimization. It captures
the complete agent definition — instructions, tools, callbacks, routing,
guardrails, policies, sub-agents, and environment config — in a single
structured object that can be serialized to markdown and round-tripped.

Layer: Layer 0 (shared types). No imports from api/, web/, builder/, adk/.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class CallbackTiming(str, Enum):
    """When a callback fires relative to its target."""

    BEFORE_MODEL = "before_model"
    AFTER_MODEL = "after_model"
    BEFORE_AGENT = "before_agent"
    AFTER_AGENT = "after_agent"
    BEFORE_TOOL = "before_tool"
    AFTER_TOOL = "after_tool"


class ToolEntry(BaseModel):
    """A tool available to an agent, with full signature and metadata."""

    name: str
    description: str = ""
    parameters: list[dict[str, Any]] = Field(default_factory=list)
    timeout_ms: int | None = None
    invocation_hint: str = "auto"
    source_platform: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class CallbackEntry(BaseModel):
    """A callback function attached to an agent lifecycle event."""

    name: str
    timing: CallbackTiming
    description: str = ""
    function_name: str = ""
    signature: str = ""
    body: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class RoutingRuleEntry(BaseModel):
    """A rule for routing messages to a sub-agent or specialist."""

    target: str
    condition_type: str = "keyword"
    keywords: list[str] = Field(default_factory=list)
    patterns: list[str] = Field(default_factory=list)
    priority: int = 0
    fallback: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class GuardrailEntry(BaseModel):
    """A safety or quality gate on agent input/output."""

    name: str
    type: str = "both"
    description: str = ""
    enforcement: str = "block"
    condition: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class PolicyEntry(BaseModel):
    """A behavioral constraint or operational policy."""

    name: str
    type: str = "behavioral"
    description: str = ""
    enforcement: str = "recommended"
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class HandoffEntry(BaseModel):
    """A transfer of control between agents."""

    source: str = ""
    target: str
    condition: str = ""
    context_transfer: str = "full"
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class McpServerEntry(BaseModel):
    """Reference to an MCP server and its exposed tools."""

    name: str
    config: dict[str, Any] = Field(default_factory=dict)
    tools_exposed: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class EnvironmentEntry(BaseModel):
    """Runtime environment and generation settings."""

    model: str = ""
    provider: str = ""
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    top_k: int | None = None
    settings: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class SubAgentSection(BaseModel):
    """A sub-agent within the agent hierarchy.

    Recursive: sub-agents can themselves contain sub-agents, mirroring the
    actual agent tree structure from ADK or other frameworks.
    """

    name: str
    description: str = ""
    agent_type: str = "llm_agent"
    instructions: str = ""
    tools: list[ToolEntry] = Field(default_factory=list)
    callbacks: list[CallbackEntry] = Field(default_factory=list)
    routing_rules: list[RoutingRuleEntry] = Field(default_factory=list)
    guardrails: list[GuardrailEntry] = Field(default_factory=list)
    policies: list[PolicyEntry] = Field(default_factory=list)
    handoffs: list[HandoffEntry] = Field(default_factory=list)
    mcp_servers: list[McpServerEntry] = Field(default_factory=list)
    environment: EnvironmentEntry = Field(default_factory=EnvironmentEntry)
    sub_agents: list[SubAgentSection] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}

    def all_tool_names(self) -> list[str]:
        """Collect tool names from this sub-agent and all nested sub-agents."""
        names = [t.name for t in self.tools]
        for sa in self.sub_agents:
            names.extend(sa.all_tool_names())
        return names


class AgentCardModel(BaseModel):
    """The complete Agent Card: standardized representation of an agent.

    This is the single object that AgentLab reasons over for building,
    evaluation, and optimization — regardless of the source framework.
    """

    name: str
    description: str = ""
    version: str = "1.0"
    platform_origin: str = ""

    # Root agent surfaces
    instructions: str = ""
    tools: list[ToolEntry] = Field(default_factory=list)
    callbacks: list[CallbackEntry] = Field(default_factory=list)
    routing_rules: list[RoutingRuleEntry] = Field(default_factory=list)
    guardrails: list[GuardrailEntry] = Field(default_factory=list)
    policies: list[PolicyEntry] = Field(default_factory=list)
    handoffs: list[HandoffEntry] = Field(default_factory=list)
    mcp_servers: list[McpServerEntry] = Field(default_factory=list)
    environment: EnvironmentEntry = Field(default_factory=EnvironmentEntry)

    # Agent hierarchy
    sub_agents: list[SubAgentSection] = Field(default_factory=list)

    # Traces and examples
    example_traces: list[dict[str, Any]] = Field(default_factory=list)

    # Extensible metadata
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def all_tool_names(self) -> list[str]:
        """Collect tool names from root and all sub-agents."""
        names = [t.name for t in self.tools]
        for sa in self.sub_agents:
            names.extend(sa.all_tool_names())
        return names

    def all_agent_names(self) -> list[str]:
        """Return names of root + all sub-agents recursively."""
        names = [self.name]
        for sa in self.sub_agents:
            names.extend(_collect_agent_names(sa))
        return names

    def find_sub_agent(self, name: str) -> SubAgentSection | None:
        """Find a sub-agent by name anywhere in the hierarchy."""
        for sa in self.sub_agents:
            if sa.name == name:
                return sa
            found = _find_nested(sa, name)
            if found is not None:
                return found
        return None

    def all_callbacks(self) -> list[CallbackEntry]:
        """Collect callbacks from root and all sub-agents."""
        cbs = list(self.callbacks)
        for sa in self.sub_agents:
            cbs.extend(_collect_callbacks(sa))
        return cbs

    def surface_summary(self) -> dict[str, int]:
        """Return counts of each surface type for quick inspection."""
        return {
            "instructions": 1 + sum(1 for sa in self.sub_agents if sa.instructions),
            "tools": len(self.all_tool_names()),
            "callbacks": len(self.all_callbacks()),
            "routing_rules": len(self.routing_rules),
            "guardrails": len(self.guardrails),
            "policies": len(self.policies),
            "handoffs": len(self.handoffs),
            "sub_agents": len(self.sub_agents),
            "mcp_servers": len(self.mcp_servers),
        }


# ------------------------------------------------------------------
# Private recursive helpers
# ------------------------------------------------------------------


def _collect_agent_names(sa: SubAgentSection) -> list[str]:
    names = [sa.name]
    for child in sa.sub_agents:
        names.extend(_collect_agent_names(child))
    return names


def _find_nested(sa: SubAgentSection, name: str) -> SubAgentSection | None:
    for child in sa.sub_agents:
        if child.name == name:
            return child
        found = _find_nested(child, name)
        if found is not None:
            return found
    return None


def _collect_callbacks(sa: SubAgentSection) -> list[CallbackEntry]:
    cbs = list(sa.callbacks)
    for child in sa.sub_agents:
        cbs.extend(_collect_callbacks(child))
    return cbs
