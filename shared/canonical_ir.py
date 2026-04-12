"""Canonical typed intermediate representation for agent definitions.

This module defines the platform-neutral component graph that preserves
meaningful agent behavior across frameworks. Every agent — whether imported
from OpenAI Agents, Anthropic SDK, Google ADK, CX Agent Studio, or built
from scratch — can be represented as a CanonicalAgent.

The IR is intentionally richer than any single adapter's output so that
round-trip conversions lose less information. Fields that cannot be
populated from a given source are left at their defaults.

Layer: Layer 0 (shared types). No imports from api/, web/, builder/, adk/.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class InstructionRole(str, Enum):
    """Semantic role of an instruction block."""

    SYSTEM = "system"
    PERSONA = "persona"
    TASK = "task"
    CONSTRAINT = "constraint"
    CONTEXT = "context"


class InstructionFormat(str, Enum):
    """Encoding format of an instruction block."""

    TEXT = "text"
    XML = "xml"
    MARKDOWN = "markdown"


class ToolInvocationHint(str, Enum):
    """Hint for how the tool is expected to be invoked."""

    AUTO = "auto"
    REQUIRED = "required"
    ON_DEMAND = "on_demand"
    PARALLEL = "parallel"
    SEQUENTIAL = "sequential"


class GuardrailType(str, Enum):
    """Where the guardrail applies in the message lifecycle."""

    INPUT = "input"
    OUTPUT = "output"
    BOTH = "both"


class GuardrailEnforcement(str, Enum):
    """What happens when the guardrail triggers."""

    BLOCK = "block"
    WARN = "warn"
    LOG = "log"


class PolicyType(str, Enum):
    """Category of behavioral policy."""

    BEHAVIORAL = "behavioral"
    SAFETY = "safety"
    COMPLIANCE = "compliance"
    OPERATIONAL = "operational"


class PolicyEnforcement(str, Enum):
    """How strictly the policy must be followed."""

    REQUIRED = "required"
    RECOMMENDED = "recommended"
    OPTIONAL = "optional"


class ContextTransfer(str, Enum):
    """How much context is passed during a handoff."""

    FULL = "full"
    SUMMARY = "summary"
    NONE = "none"


class ConditionType(str, Enum):
    """How a routing rule matches incoming messages."""

    KEYWORD = "keyword"
    PATTERN = "pattern"
    INTENT = "intent"
    LLM = "llm"
    ALWAYS = "always"


class FidelityStatus(str, Enum):
    """How faithfully a field was converted."""

    FAITHFUL = "faithful"
    APPROXIMATED = "approximated"
    LOSSY = "lossy"
    MISSING = "missing"


# ---------------------------------------------------------------------------
# Component types
# ---------------------------------------------------------------------------


class FidelityNote(BaseModel):
    """Records conversion fidelity for a specific field or component."""

    field: str
    status: FidelityStatus
    rationale: str = ""

    model_config = {"extra": "allow"}


class Instruction(BaseModel):
    """A single instruction block with semantic role and format metadata."""

    role: InstructionRole = InstructionRole.SYSTEM
    content: str = ""
    format: InstructionFormat = InstructionFormat.TEXT
    priority: int = 0
    label: str = ""

    model_config = {"extra": "allow"}


class ToolParameter(BaseModel):
    """A single parameter in a tool's input schema."""

    name: str
    type: str = "string"
    description: str = ""
    required: bool = False
    default: Any = None
    enum: list[str] | None = None

    model_config = {"extra": "allow"}


class ToolContract(BaseModel):
    """Typed definition of a tool available to an agent."""

    name: str
    description: str = ""
    parameters: list[ToolParameter] = Field(default_factory=list)
    invocation_hint: ToolInvocationHint = ToolInvocationHint.AUTO
    source_platform: str = ""
    timeout_ms: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class RoutingRuleSpec(BaseModel):
    """A rule for routing messages to a specialist or sub-agent."""

    target: str
    condition_type: ConditionType = ConditionType.KEYWORD
    keywords: list[str] = Field(default_factory=list)
    patterns: list[str] = Field(default_factory=list)
    priority: int = 0
    fallback: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class PolicySpec(BaseModel):
    """A behavioral constraint or operational policy."""

    name: str
    type: PolicyType = PolicyType.BEHAVIORAL
    description: str = ""
    enforcement: PolicyEnforcement = PolicyEnforcement.RECOMMENDED
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class GuardrailSpec(BaseModel):
    """A safety or quality gate applied to agent input/output."""

    name: str
    type: GuardrailType = GuardrailType.BOTH
    description: str = ""
    enforcement: GuardrailEnforcement = GuardrailEnforcement.BLOCK
    condition: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class HandoffSpec(BaseModel):
    """A transfer of control between agents."""

    source: str = ""
    target: str
    condition: str = ""
    context_transfer: ContextTransfer = ContextTransfer.FULL
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class McpServerRef(BaseModel):
    """Reference to an MCP server and its exposed tools."""

    name: str
    config: dict[str, Any] = Field(default_factory=dict)
    tools_exposed: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class EnvironmentConfig(BaseModel):
    """Runtime environment settings for the agent."""

    model: str = ""
    provider: str = ""
    temperature: float | None = None
    max_tokens: int | None = None
    settings: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class CanonicalAgent(BaseModel):
    """Platform-neutral typed representation of an agent.

    This is the canonical intermediate representation (IR) at the center of
    all conversions. It preserves enough structure to enable higher-fidelity
    round-trips between frameworks than the flat config dict approach.
    """

    name: str = ""
    description: str = ""
    platform_origin: str = ""

    instructions: list[Instruction] = Field(default_factory=list)
    tools: list[ToolContract] = Field(default_factory=list)
    routing_rules: list[RoutingRuleSpec] = Field(default_factory=list)
    policies: list[PolicySpec] = Field(default_factory=list)
    guardrails: list[GuardrailSpec] = Field(default_factory=list)
    handoffs: list[HandoffSpec] = Field(default_factory=list)
    sub_agents: list[CanonicalAgent] = Field(default_factory=list)
    mcp_servers: list[McpServerRef] = Field(default_factory=list)
    environment: EnvironmentConfig = Field(default_factory=EnvironmentConfig)
    example_traces: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    fidelity_notes: list[FidelityNote] = Field(default_factory=list)

    model_config = {"extra": "allow"}

    def tool_names(self) -> list[str]:
        """Return the names of all tools in this agent."""
        return [tool.name for tool in self.tools]

    def guardrail_names(self) -> list[str]:
        """Return the names of all guardrails in this agent."""
        return [g.name for g in self.guardrails]

    def handoff_targets(self) -> list[str]:
        """Return unique handoff target names."""
        return list(dict.fromkeys(h.target for h in self.handoffs))

    def sub_agent_names(self) -> list[str]:
        """Return names of direct sub-agents."""
        return [sa.name for sa in self.sub_agents]

    def all_tools_recursive(self) -> list[ToolContract]:
        """Collect tools from this agent and all sub-agents."""
        result = list(self.tools)
        for sa in self.sub_agents:
            result.extend(sa.all_tools_recursive())
        return result

    def flatten_instructions(self) -> str:
        """Concatenate instruction content in priority order."""
        sorted_instructions = sorted(self.instructions, key=lambda i: -i.priority)
        return "\n\n".join(i.content for i in sorted_instructions if i.content)

    def primary_instruction(self) -> str:
        """Return the highest-priority instruction content, or empty string."""
        if not self.instructions:
            return ""
        return max(self.instructions, key=lambda i: i.priority).content
