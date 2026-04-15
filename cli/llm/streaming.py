"""Streaming primitives for the LLM orchestrator.

Live LLM calls emit a sequence of low-level events (text deltas, tool-use
start/stop, thinking blocks, usage deltas) rather than one finished
response. This module defines the tagged-union event type the orchestrator
and renderer consume, plus :func:`collect_stream` which rebuilds the
final :class:`ModelResponse` from an event iterable.

Keeping the protocol small and provider-agnostic means the
:class:`AnthropicClient`, a future OpenAI client, and test stubs can all
conform without leaking SDK types upward. The orchestrator's only job is
to dispatch each event to the renderer and to accumulate the final
response for bookkeeping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Protocol

from cli.llm.types import (
    AssistantTextBlock,
    AssistantToolUseBlock,
    ModelResponse,
)


# ---------------------------------------------------------------------------
# Event tagged union
# ---------------------------------------------------------------------------


@dataclass
class TextDelta:
    """Incremental text produced by the model.

    ``text`` is the *new* chunk — callers concatenate chunks themselves.
    Emitting deltas rather than cumulative strings keeps the wire format
    memory-bounded on long responses."""

    text: str
    type: str = "text_delta"


@dataclass
class ThinkingDelta:
    """Extended-thinking content (Claude Opus 4.x). We keep it distinct so
    the renderer can fold it into a collapsible panel rather than the
    main transcript."""

    text: str
    type: str = "thinking_delta"


@dataclass
class ToolUseStart:
    """A tool-use block is starting.

    ``input`` is usually empty here; the model streams the JSON incrementally
    via :class:`ToolUseDelta`. The orchestrator uses this to initialise a
    buffer keyed by ``id``."""

    id: str
    name: str
    input: dict[str, Any] = field(default_factory=dict)
    type: str = "tool_use_start"


@dataclass
class ToolUseDelta:
    """Incremental JSON fragment for the tool input.

    Anthropic streams the input as ``input_json`` deltas that concatenate
    into a complete JSON blob; OpenAI streams deltas on the function
    ``arguments`` string. Both shapes land here as a raw text chunk."""

    id: str
    input_json: str
    type: str = "tool_use_delta"


@dataclass
class ToolUseEnd:
    """A tool-use block finished. ``input`` is the parsed JSON, ready for
    the orchestrator to hand to :func:`execute_tool_call`."""

    id: str
    name: str
    input: dict[str, Any]
    type: str = "tool_use_end"


@dataclass
class UsageDelta:
    """Token-usage update. Some providers emit this periodically during
    streaming; others only at message_stop. Accumulate across a turn."""

    usage: dict[str, int]
    type: str = "usage"


@dataclass
class MessageStop:
    """End-of-response sentinel. ``stop_reason`` mirrors
    :class:`ModelResponse.stop_reason` and determines whether the
    orchestrator loops for tool results."""

    stop_reason: str
    type: str = "message_stop"


StreamEvent = (
    "TextDelta | ThinkingDelta | ToolUseStart | ToolUseDelta | "
    "ToolUseEnd | UsageDelta | MessageStop"
)
"""Type-alias used in annotations. Runtime checks use ``isinstance`` against
the individual dataclasses."""


class StreamingModelClient(Protocol):
    """Extension of :class:`~cli.llm.types.ModelClient` that streams.

    Any client that implements :meth:`stream` gets streaming UX for free.
    Clients that cannot stream (e.g. a fake ``EchoModel``) stay on the
    base protocol and the orchestrator synthesises one-shot rendering."""

    def stream(
        self,
        *,
        system_prompt: str,
        messages: list[Any],
        tools: list[dict[str, Any]],
    ) -> Iterator[Any]:  # pragma: no cover - protocol
        ...


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------


def collect_stream(events: Iterable[Any]) -> ModelResponse:
    """Fold an event stream into one :class:`ModelResponse`.

    Used by non-streaming call sites (tests, :class:`EchoModel`) and by
    the orchestrator after it has forwarded deltas to the renderer. The
    function is pure — it never reaches out to the network — so the same
    logic drives production and test code paths."""
    blocks: list[Any] = []
    text_buffer: list[str] = []
    tool_inputs: dict[str, list[str]] = {}
    tool_names: dict[str, str] = {}
    usage: dict[str, int] = {}
    stop_reason = "end_turn"

    for event in events:
        if isinstance(event, TextDelta):
            text_buffer.append(event.text)
        elif isinstance(event, ThinkingDelta):
            # Thinking is intentionally *not* folded into the assistant text
            # — callers that want it can inspect the raw events. Carrying
            # it as a separate block would bloat the ModelResponse shape
            # without changing orchestrator behaviour.
            continue
        elif isinstance(event, ToolUseStart):
            tool_inputs.setdefault(event.id, [])
            tool_names[event.id] = event.name
            # Start block claims its position in the output order so later
            # flushes can interleave text ↔ tool_use correctly.
            _flush_text(blocks, text_buffer)
            blocks.append(_pending_tool_use(event.id, event.name))
        elif isinstance(event, ToolUseDelta):
            tool_inputs.setdefault(event.id, []).append(event.input_json)
        elif isinstance(event, ToolUseEnd):
            _resolve_tool_use(
                blocks,
                event.id,
                event.name,
                event.input if event.input else _parse_json(tool_inputs.get(event.id, [])),
            )
        elif isinstance(event, UsageDelta):
            for key, value in event.usage.items():
                try:
                    usage[key] = usage.get(key, 0) + int(value)
                except (TypeError, ValueError):
                    continue
        elif isinstance(event, MessageStop):
            stop_reason = event.stop_reason or "end_turn"
        # Unknown event shapes are ignored; new providers can emit extras
        # without breaking existing consumers.

    _flush_text(blocks, text_buffer)
    # Ensure every tool-use placeholder has resolved inputs by the end of
    # the stream; providers that omit ToolUseEnd still close out via the
    # streaming SDK's message_stop signal.
    for block in blocks:
        if isinstance(block, dict) and block.get("__pending") and block["id"] in tool_inputs:
            block["input"] = _parse_json(tool_inputs[block["id"]])
    blocks = [_materialise_block(block) for block in blocks]
    return ModelResponse(blocks=blocks, stop_reason=stop_reason, usage=usage)


def _flush_text(blocks: list[Any], buffer: list[str]) -> None:
    if not buffer:
        return
    text = "".join(buffer)
    buffer.clear()
    if not text:
        return
    blocks.append(AssistantTextBlock(text=text))


def _pending_tool_use(id: str, name: str) -> dict[str, Any]:
    """Return a placeholder dict we can mutate as deltas arrive."""
    return {"__pending": True, "id": id, "name": name, "input": {}}


def _resolve_tool_use(
    blocks: list[Any], id: str, name: str, input_data: dict[str, Any]
) -> None:
    for index, block in enumerate(blocks):
        if isinstance(block, dict) and block.get("__pending") and block["id"] == id:
            blocks[index] = {
                "__pending": False,
                "id": id,
                "name": name,
                "input": input_data,
            }
            return
    # No pending block — this provider skipped the start event, so we just
    # append the resolved block in stream order.
    blocks.append({"__pending": False, "id": id, "name": name, "input": input_data})


def _materialise_block(block: Any) -> Any:
    """Convert pending dicts to real :class:`AssistantToolUseBlock`s."""
    if isinstance(block, dict) and "__pending" in block:
        return AssistantToolUseBlock(
            id=block["id"],
            name=block["name"],
            input=block.get("input") or {},
        )
    return block


def _parse_json(fragments: list[str]) -> dict[str, Any]:
    """Best-effort parse of concatenated JSON fragments.

    Streaming providers frequently send the JSON in small slices; we
    assemble and parse once at the end. An unparseable payload becomes an
    empty dict rather than raising — the orchestrator will then pass
    ``{}`` to the tool which reports a clearer error than a JSON
    exception."""
    import json as _json

    combined = "".join(fragments).strip()
    if not combined:
        return {}
    try:
        result = _json.loads(combined)
    except _json.JSONDecodeError:
        return {}
    return result if isinstance(result, dict) else {}


# ---------------------------------------------------------------------------
# Adapter helpers
# ---------------------------------------------------------------------------


def events_from_model_response(response: ModelResponse) -> Iterable[Any]:
    """Synthesize a stream from a one-shot :class:`ModelResponse`.

    Used by :class:`LLMOrchestrator` when a client implements only the
    non-streaming ``complete()`` method — we still want the renderer to
    see text events so the UI is uniform. One event per block preserves
    block ordering without fragmenting content needlessly."""
    for block in response.blocks:
        if isinstance(block, AssistantTextBlock):
            yield TextDelta(text=block.text)
        elif isinstance(block, AssistantToolUseBlock):
            yield ToolUseStart(id=block.id, name=block.name)
            yield ToolUseEnd(id=block.id, name=block.name, input=dict(block.input or {}))
    if response.usage:
        yield UsageDelta(usage=dict(response.usage))
    yield MessageStop(stop_reason=response.stop_reason or "end_turn")


__all__ = [
    "MessageStop",
    "StreamingModelClient",
    "TextDelta",
    "ThinkingDelta",
    "ToolUseDelta",
    "ToolUseEnd",
    "ToolUseStart",
    "UsageDelta",
    "collect_stream",
    "events_from_model_response",
]
