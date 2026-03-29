"""Types for the conversational agent builder flow."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from builder.types import new_id, now_ts


@dataclass
class BuilderChatMessage:
    """One conversational turn in the builder session."""

    message_id: str = field(default_factory=new_id)
    role: str = "assistant"
    content: str = ""
    created_at: float = field(default_factory=now_ts)


@dataclass
class BuilderToolDraft:
    """A tool included in the generated agent config."""

    name: str
    description: str
    when_to_use: str


@dataclass
class BuilderRoutingRuleDraft:
    """A routing rule included in the generated agent config."""

    name: str
    intent: str
    description: str


@dataclass
class BuilderPolicyDraft:
    """A policy included in the generated agent config."""

    name: str
    description: str


@dataclass
class BuilderEvalCriterionDraft:
    """An eval criterion used to validate the generated agent."""

    name: str
    description: str


@dataclass
class BuilderConfigDraft:
    """Mutable agent config assembled through conversation."""

    agent_name: str = "Customer Support Agent"
    system_prompt: str = ""
    tools: list[BuilderToolDraft] = field(default_factory=list)
    routing_rules: list[BuilderRoutingRuleDraft] = field(default_factory=list)
    policies: list[BuilderPolicyDraft] = field(default_factory=list)
    eval_criteria: list[BuilderEvalCriterionDraft] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BuilderEvalDraft:
    """Generated eval summary for the draft config."""

    case_count: int = 0
    scenarios: list[dict[str, str]] = field(default_factory=list)


@dataclass
class BuilderChatSession:
    """State for one conversational builder session."""

    session_id: str = field(default_factory=new_id)
    created_at: float = field(default_factory=now_ts)
    updated_at: float = field(default_factory=now_ts)
    messages: list[BuilderChatMessage] = field(default_factory=list)
    config: BuilderConfigDraft = field(default_factory=BuilderConfigDraft)
    evals: BuilderEvalDraft | None = None
