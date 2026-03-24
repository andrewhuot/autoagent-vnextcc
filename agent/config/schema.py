"""Agent configuration schema and validation."""

from __future__ import annotations

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
    """System prompts for all agents."""

    root: str = "You are a helpful customer service agent."
    support: str = "You are a customer support specialist."
    orders: str = "You are an order management specialist."
    recommendations: str = "You are a product recommendation specialist."


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


class AgentConfig(BaseModel):
    """Top-level agent configuration."""

    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    prompts: PromptsConfig = Field(default_factory=PromptsConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    thresholds: ThresholdsConfig = Field(default_factory=ThresholdsConfig)
    context_caching: ContextCachingConfig = Field(
        default_factory=ContextCachingConfig
    )
    compaction: CompactionConfig = Field(default_factory=CompactionConfig)
    memory_policy: MemoryPolicyConfig = Field(
        default_factory=MemoryPolicyConfig
    )
    model: str = "gemini-2.0-flash"
    quality_boost: bool = False


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
