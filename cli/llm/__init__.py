"""LLM orchestration layer.

This package is the Phase-7 wiring point: it composes every primitive the
earlier phases built into a single turn loop. A :class:`ModelClient`
produces text and tool-use blocks; the :class:`LLMOrchestrator` routes
tool calls through :mod:`cli.tools.executor` (which consults permissions,
hooks, and skill overlays), feeds tool results back to the model, streams
assistant output through :mod:`cli.workbench_app.markdown_stream`, and
emits one :class:`OrchestratorResult` per user turn.

The orchestrator is adapter-agnostic: it accepts any object implementing
:class:`ModelClient` so we can plug the existing
:mod:`adapters.anthropic_claude` / :mod:`adapters.openai_agents` clients
(or a stub for tests) without each adapter re-implementing the
permission/tool-use plumbing.
"""

from __future__ import annotations

from cli.llm.types import (
    AssistantBlock,
    AssistantTextBlock,
    AssistantToolUseBlock,
    ModelClient,
    ModelResponse,
    OrchestratorResult,
    TurnMessage,
)
from cli.llm.orchestrator import LLMOrchestrator

__all__ = [
    "AssistantBlock",
    "AssistantTextBlock",
    "AssistantToolUseBlock",
    "LLMOrchestrator",
    "ModelClient",
    "ModelResponse",
    "OrchestratorResult",
    "TurnMessage",
]
