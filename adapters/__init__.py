"""External runtime adapters for importing existing agent systems."""

from .anthropic_claude import AnthropicClaudeAdapter
from .base import AgentAdapter, ConnectWorkspaceResult, ImportedAgentSpec
from .http_webhook import HttpWebhookAdapter
from .openai_agents import OpenAIAgentsAdapter
from .transcript import TranscriptAdapter
from .workspace_builder import create_connected_workspace

__all__ = [
    "AgentAdapter",
    "AnthropicClaudeAdapter",
    "ConnectWorkspaceResult",
    "HttpWebhookAdapter",
    "ImportedAgentSpec",
    "OpenAIAgentsAdapter",
    "TranscriptAdapter",
    "create_connected_workspace",
]
