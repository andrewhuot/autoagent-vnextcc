"""A2A (Agent-to-Agent) protocol support for AutoAgent VNextCC.

This package implements the A2A protocol for interoperable agent discovery,
task submission, and lifecycle management.

Exports:
    Types: AgentSkill, AgentCapabilities, AgentCard, A2ATask, A2AMessage, TaskStatus
    AgentCardGenerator: Build and serialise agent cards.
    A2AServer: Expose locally registered agents over A2A JSON-RPC endpoints.
    A2AClient: Discover and invoke remote A2A-compatible agents.
    TaskManager: In-memory A2A task lifecycle store.
"""

from __future__ import annotations

from a2a.agent_card import AgentCardGenerator
from a2a.client import A2AClient
from a2a.server import A2AServer
from a2a.task import TaskManager
from a2a.types import (
    A2AMessage,
    A2ATask,
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    TaskStatus,
)

__all__ = [
    # Types
    "AgentSkill",
    "AgentCapabilities",
    "AgentCard",
    "A2ATask",
    "A2AMessage",
    "TaskStatus",
    # Classes
    "AgentCardGenerator",
    "A2AServer",
    "A2AClient",
    "TaskManager",
]
