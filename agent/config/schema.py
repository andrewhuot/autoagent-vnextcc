"""Agent configuration schema and validation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RoutingRule(BaseModel):
    """Routing rule for a specialist agent."""

    specialist: str
    keywords: list[str] = Field(default_factory=list)
    patterns: list[str] = Field(default_factory=list)


class RoutingConfig(BaseModel):
    """Routing configuration."""

    rules: list[RoutingRule] = Field(default_factory=list)


class PromptsConfig(BaseModel):
    """System prompts for all agents.

    Supports both the legacy fixed fields (root/support/orders/recommendations)
    and arbitrary specialist prompt keys via model_config extra="allow".
    """

    root: str = "You are a helpful customer service agent."
    support: str = "You are a customer support specialist."
    orders: str = "You are an order management specialist."
    recommendations: str = "You are a product recommendation specialist."

    model_config = {"extra": "allow"}


class ToolConfig(BaseModel):
    """Configuration for a single tool."""

    enabled: bool = True
    timeout_ms: int = 5000


class ToolsConfig(BaseModel):
    """Tool configurations."""

    catalog: ToolConfig = Field(default_factory=ToolConfig)
    orders_db: ToolConfig = Field(default_factory=ToolConfig)
    faq: ToolConfig = Field(default_factory=ToolConfig)


class ThresholdsConfig(BaseModel):
    """Operational thresholds."""

    confidence_threshold: float = 0.6
    max_turns: int = 20
    max_latency_ms: int = 10000


class ContextCachingConfig(BaseModel):
    """Context caching configuration for reducing redundant token usage."""

    enabled: bool = False
    threshold_tokens: int = 1000
    ttl_seconds: int = 300
    max_use_count: int = 10


class CompactionConfig(BaseModel):
    """Conversation compaction configuration for long-running sessions."""

    enabled: bool = False
    interval_turns: int = 10
    overlap_turns: int = 2
    summarizer_model: str = "gemini-2.0-flash"


class MemoryPolicyConfig(BaseModel):
    """Memory preload/writeback policy configuration."""

    preload: bool = True
    on_demand: bool = False
    write_back: bool = True
    max_entries: int = 100


class OptimizerConfig(BaseModel):
    """Optimizer configuration for v4 research features."""

    search_strategy: str = "simple"  # "simple" | "adaptive" | "full"
    bandit_policy: str = "ucb1"  # "ucb1" | "thompson"
    holdout_rotation: bool = False
    holdout_tuning_fraction: float = 0.6
    holdout_validation_fraction: float = 0.2
    holdout_holdout_fraction: float = 0.2
    holdout_rotation_interval: int = 10
    drift_detection_window: int = 5
    drift_threshold: float = 0.03
    curriculum_enabled: bool = False
    curriculum_min_experiments_per_tier: int = 3
    curriculum_stall_threshold: float = 0.01
    use_skills: bool = False  # Enable skill-driven optimization
    skill_selection_strategy: str = "auto"  # "auto" | "manual" | "all"
    skill_max_candidates: int = 5  # Max skills to select per cycle


class GuardrailConfig(BaseModel):
    """Configuration for a single guardrail."""

    name: str
    type: str = "both"
    enforcement: str = "block"
    description: str = ""


class HandoffConfig(BaseModel):
    """Configuration for an agent-to-agent handoff."""

    source: str = ""
    target: str
    condition: str = ""
    context_transfer: str = "full"


class PolicyConfig(BaseModel):
    """Configuration for a behavioral policy."""

    name: str
    type: str = "behavioral"
    enforcement: str = "recommended"
    description: str = ""


class McpServerConfig(BaseModel):
    """Configuration for an MCP server reference."""

    name: str
    config: dict[str, Any] = Field(default_factory=dict)
    tools_exposed: list[str] = Field(default_factory=list)


class GenerationConfig(BaseModel):
    """LLM generation settings."""

    temperature: float | None = None
    max_tokens: int | None = None


class AgentConfig(BaseModel):
    """Top-level agent configuration.

    Supports both legacy fixed-schema fields (tools, prompts with hardcoded
    specialists) and new dynamic fields (tools_config, guardrails, handoffs,
    policies, mcp_servers) for richer agent representations.
    """

    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    prompts: PromptsConfig = Field(default_factory=PromptsConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    tools_config: dict[str, Any] = Field(default_factory=dict)
    thresholds: ThresholdsConfig = Field(default_factory=ThresholdsConfig)
    context_caching: ContextCachingConfig = Field(
        default_factory=ContextCachingConfig
    )
    compaction: CompactionConfig = Field(default_factory=CompactionConfig)
    memory_policy: MemoryPolicyConfig = Field(
        default_factory=MemoryPolicyConfig
    )
    optimizer: OptimizerConfig = Field(default_factory=OptimizerConfig)
    model: str = "gemini-2.0-flash"
    quality_boost: bool = False
    guardrails: list[GuardrailConfig] = Field(default_factory=list)
    handoffs: list[HandoffConfig] = Field(default_factory=list)
    policies: list[PolicyConfig] = Field(default_factory=list)
    mcp_servers: list[McpServerConfig] = Field(default_factory=list)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    adapter: dict[str, Any] = Field(default_factory=dict)


    def to_canonical(self, *, name: str = "", platform: str = "") -> "CanonicalAgent":
        """Convert this AgentConfig to a CanonicalAgent IR."""
        from shared.canonical_ir_convert import from_config_dict

        return from_config_dict(self.model_dump(), name=name, platform=platform)

    @classmethod
    def from_canonical(cls, agent: "CanonicalAgent") -> "AgentConfig":
        """Build an AgentConfig from a CanonicalAgent IR."""
        from shared.canonical_ir_convert import to_config_dict

        config_dict = to_config_dict(agent)
        return cls.model_validate(config_dict)


# Deferred import for type annotation
from typing import TYPE_CHECKING  # noqa: E402

if TYPE_CHECKING:
    from shared.canonical_ir import CanonicalAgent  # noqa: F401


def validate_config(data: dict) -> AgentConfig:
    """Validate a raw dict against the config schema, returning AgentConfig."""
    return AgentConfig.model_validate(data)


def config_diff(old: AgentConfig, new: AgentConfig) -> str:
    """Return a human-readable diff of two configs."""
    old_dict = old.model_dump()
    new_dict = new.model_dump()
    changes: list[str] = []
    _diff_dicts(old_dict, new_dict, prefix="", changes=changes)
    if not changes:
        return "No changes."
    return "\n".join(changes)


def _diff_dicts(
    old: dict | list | object,
    new: dict | list | object,
    prefix: str,
    changes: list[str],
) -> None:
    """Recursively diff two nested structures."""
    if isinstance(old, dict) and isinstance(new, dict):
        all_keys = set(old) | set(new)
        for key in sorted(all_keys):
            path = f"{prefix}.{key}" if prefix else key
            if key not in old:
                changes.append(f"+ {path}: {new[key]}")
            elif key not in new:
                changes.append(f"- {path}: {old[key]}")
            else:
                _diff_dicts(old[key], new[key], path, changes)
    elif isinstance(old, list) and isinstance(new, list):
        if old != new:
            changes.append(f"~ {prefix}: {old!r} -> {new!r}")
    elif old != new:
        changes.append(f"~ {prefix}: {old!r} -> {new!r}")
