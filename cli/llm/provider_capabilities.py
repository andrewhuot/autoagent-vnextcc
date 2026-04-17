"""Per-adapter capability descriptor.

This module is deliberately adjacent-but-distinct from
:mod:`cli.llm.capabilities`:

* ``cli/llm/capabilities.py::ModelCapability`` answers "what does *this
  model* support and cost" — a string-keyed static table.
* ``cli/llm/provider_capabilities.py::ProviderCapabilities`` answers
  "what does *this adapter* support at runtime today" — an attribute on
  the :class:`~cli.llm.types.ModelClient` that the orchestrator reads
  when it needs to branch (streaming dispatch, thinking panel,
  cache-hint, etc.).

The descriptor is a ``frozen=True`` dataclass so an adapter's declared
capabilities can't be mutated by downstream code — any change has to
happen at the adapter definition site where it's reviewable. All fields
are required; there are no defaults. An adapter that hedges by leaving a
field unset would be dishonest about its surface, which defeats the
point of the descriptor.

The field ``streaming`` intentionally reflects *current* adapter
behaviour — not future behaviour. Today's OpenAI adapter synthesises a
fake stream from a one-shot response, so ``streaming=False``. P0.5d
flips that once the adapter truly emits real-time deltas. A silent flip
before the implementation lands should fail the matrix test in
``tests/test_provider_capabilities.py``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderCapabilities:
    """Runtime capabilities declared by a :class:`ModelClient` adapter.

    Attributes:
        streaming: Adapter's ``stream()`` yields incremental events from
            the provider SDK rather than synthesising them from a
            one-shot response.
        native_tool_use: Provider has a first-class tool-use wire shape
            the adapter maps from our canonical
            :class:`~cli.llm.types.AssistantToolUseBlock`. Adapters
            without this must pass tools via the prompt — generally
            lower quality.
        parallel_tool_calls: Provider can emit more than one tool call
            in a single assistant turn. Anthropic and OpenAI do;
            Gemini currently serialises.
        thinking: Provider exposes a dedicated chain-of-thought /
            reasoning channel the adapter surfaces via
            :class:`~cli.llm.streaming.ThinkingDelta`.
        prompt_cache: Provider offers *some* form of prompt caching the
            adapter honours — may be automatic (OpenAI prefix cache)
            or explicit breakpoint markers (Anthropic ``cache_control``).
        vision: Adapter forwards image content blocks to the provider.
        json_mode: Provider supports a constrained JSON response mode
            (e.g. OpenAI's ``response_format``, Gemini's
            ``response_mime_type``). Independent of tool use.
        max_context_tokens: Maximum prompt + completion window the
            adapter targets for its default model family. Used by
            compaction / budget logic; never zero (a future divide-by
            would crash).
        max_output_tokens: Ceiling the adapter passes to the SDK by
            default when the caller doesn't override.
    """

    streaming: bool
    native_tool_use: bool
    parallel_tool_calls: bool
    thinking: bool
    prompt_cache: bool
    vision: bool
    json_mode: bool
    max_context_tokens: int
    max_output_tokens: int


__all__ = ["ProviderCapabilities"]
