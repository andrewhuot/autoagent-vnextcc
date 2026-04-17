"""Model-client protocol and turn-loop records.

These types define the contract between the orchestrator and whichever
LLM adapter produces tool-use responses. We intentionally mirror
Anthropic's tool-use message shape because (a) it's the most faithful to
how the workbench thinks about tool calls and (b) any adapter can map
that shape to its own provider without the orchestrator needing to know.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Mapping, Protocol

from cli.llm.provider_capabilities import ProviderCapabilities


# ---------------------------------------------------------------------------
# Message wire format
# ---------------------------------------------------------------------------


@dataclass
class TurnMessage:
    """One message in the conversation passed to the model.

    ``role`` is ``"user"`` | ``"assistant"``; ``content`` is either a
    plain string or a list of content blocks shaped like Anthropic's
    tool-use blocks. Keeping both forms lets callers pass human messages
    as strings while still round-tripping structured tool results.
    """

    role: str
    content: Any

    def to_wire(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict for adapters that prefer dicts
        over dataclasses."""
        return {"role": self.role, "content": self.content}


# ---------------------------------------------------------------------------
# Assistant response blocks
# ---------------------------------------------------------------------------


@dataclass
class AssistantTextBlock:
    """A streaming-friendly text chunk. ``text`` is the completed block."""

    text: str
    type: str = "text"


@dataclass
class AssistantToolUseBlock:
    """Model's request to invoke a tool.

    ``id`` pairs the request with its eventual tool_result so the model
    can match N concurrent calls in one turn — same semantics as
    Anthropic's tool-use IDs."""

    id: str
    name: str
    input: Mapping[str, Any] = field(default_factory=dict)
    type: str = "tool_use"


AssistantBlock = "AssistantTextBlock | AssistantToolUseBlock"


@dataclass
class ModelResponse:
    """One turn of model output.

    ``blocks`` is ordered: text before the first tool_use should render
    immediately; a trailing tool_use means the orchestrator runs the
    tool and issues a follow-up call with the tool_result."""

    blocks: list[Any] = field(default_factory=list)
    stop_reason: str = "end_turn"
    """Mirrors Anthropic's stop_reason vocabulary: ``"end_turn"``,
    ``"tool_use"``, ``"max_tokens"``. The orchestrator only branches on
    ``"tool_use"`` today but callers may read other values for logging."""

    usage: dict[str, int] = field(default_factory=dict)
    """Optional token accounting produced by the adapter. When supplied
    it surfaces in :class:`OrchestratorResult.usage` aggregates."""

    def tool_uses(self) -> list[AssistantToolUseBlock]:
        """Return the tool-use blocks in order."""
        return [block for block in self.blocks if isinstance(block, AssistantToolUseBlock)]

    def text_blocks(self) -> list[AssistantTextBlock]:
        return [block for block in self.blocks if isinstance(block, AssistantTextBlock)]


# ---------------------------------------------------------------------------
# ModelClient protocol
# ---------------------------------------------------------------------------


class ModelClient(Protocol):
    """Minimal contract the orchestrator needs from a model adapter.

    The adapter owns provider-specific concerns (auth, URL, retry policy,
    tokenisation). It returns a :class:`ModelResponse` per call and must
    honour the ``tools`` schema list — the orchestrator provides one via
    :meth:`ToolRegistry.to_schema`.

    Adapters declare their runtime surface via the ``capabilities``
    class attribute so the orchestrator can branch on streaming,
    thinking, prompt-cache, and vision support without importing
    provider SDKs. ``complete()`` remains on the protocol as a fallback
    path for non-streaming callers (print mode, echo tests).
    """

    capabilities: ProviderCapabilities
    """Declared runtime surface. See
    :class:`cli.llm.provider_capabilities.ProviderCapabilities`."""

    def complete(
        self,
        *,
        system_prompt: str,
        messages: list[TurnMessage],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:  # pragma: no cover - protocol
        """Return the next assistant turn.

        ``messages`` is the full conversation to date, including any
        prior tool_result blocks the orchestrator has appended. The
        adapter should *not* persist messages; state lives in
        :mod:`cli.sessions`."""
        ...

    def stream(
        self,
        *,
        system_prompt: str,
        messages: list[TurnMessage],
        tools: list[dict[str, Any]],
    ) -> Iterator[Any]:  # pragma: no cover - protocol
        """Yield :mod:`cli.llm.streaming` events for this turn.

        Adapters whose ``capabilities.streaming`` is ``False`` may
        synthesise events from a one-shot ``complete()`` call (see
        :func:`cli.llm.streaming.events_from_model_response`). The
        orchestrator's renderer contract is uniform across both paths.
        """
        ...


# ---------------------------------------------------------------------------
# Orchestrator output
# ---------------------------------------------------------------------------


@dataclass
class OrchestratorResult:
    """One turn outcome — shown to the user and appended to the session."""

    assistant_text: str
    """Concatenated text-block content, already markdown-streamed to the
    transcript. Useful for tests and for the session-history record."""

    tool_executions: list[Any] = field(default_factory=list)
    """One :class:`cli.tools.executor.ToolExecution` per tool call that
    happened during this turn, in chronological order."""

    stop_reason: str = "end_turn"
    """Stop reason reported by the *final* model call. When the
    conversation ends because of an orchestrator-side limit (max tool
    loops), this carries ``"max_tool_loops"``."""

    usage: dict[str, int] = field(default_factory=dict)
    """Sum of ``usage`` dicts returned across every model call this turn
    — useful for cost reporting without each caller aggregating."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Free-form diagnostics (hook messages, background task ids)."""


def flatten_messages(messages: Iterable[TurnMessage]) -> list[dict[str, Any]]:
    """Utility for adapters that prefer dict-shaped messages."""
    return [message.to_wire() for message in messages]


__all__ = [
    "AssistantBlock",
    "AssistantTextBlock",
    "AssistantToolUseBlock",
    "ModelClient",
    "ModelResponse",
    "OrchestratorResult",
    "ProviderCapabilities",
    "TurnMessage",
    "flatten_messages",
]
