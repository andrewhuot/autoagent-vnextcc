"""OpenAI :class:`~cli.llm.types.ModelClient` implementation.

Translates OpenAI's function-calling shape into the
Anthropic-flavoured tool_use blocks the orchestrator expects, so the
upstream code path is provider-agnostic. Lazy SDK import, same as the
Anthropic adapter.

Current scope is deliberately narrow:

* Non-streaming ``complete()`` wraps OpenAI's ``chat.completions.create``
  and returns one :class:`ModelResponse`. The SDK's streaming API is
  different from Anthropic's — we translate stream events via
  :func:`events_from_model_response` once the final response lands, so
  the orchestrator's renderer still sees a uniform stream without us
  having to re-implement token-level translation right now. A future
  revision can emit deltas directly.
* Thinking blocks and prompt caching are not yet exposed on the OpenAI
  SDK in the same shape, so they're left unimplemented.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from cli.llm.retries import RetryPolicy, retry_call
from cli.llm.streaming import (
    events_from_model_response,
)
from cli.llm.types import (
    AssistantTextBlock,
    AssistantToolUseBlock,
    ModelResponse,
    TurnMessage,
)


SdkFactory = Callable[[str], Any]


def _default_sdk_factory(api_key: str) -> Any:
    import openai  # type: ignore[import-not-found]

    return openai.OpenAI(api_key=api_key)


@dataclass
class OpenAIClient:
    """OpenAI chat-completions client translating to/from tool blocks."""

    model: str = "gpt-4o"
    api_key: str | None = None
    max_output_tokens: int = 4096
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    sdk_factory: SdkFactory = field(default=_default_sdk_factory)
    request_options: dict[str, Any] = field(default_factory=dict)

    _client: Any = field(default=None, init=False, repr=False)

    # ------------------------------------------------------------------ API

    def complete(
        self,
        *,
        system_prompt: str,
        messages: list[TurnMessage],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        """One-shot chat completion.

        Returns a :class:`ModelResponse` with tool_use blocks in the same
        shape the orchestrator uses for Anthropic, so downstream code
        needs no per-provider branching."""
        client = self._ensure_client()

        def _call():
            return client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_output_tokens,
                messages=self._translate_messages(system_prompt, messages),
                tools=[_translate_tool_schema(schema) for schema in tools],
                **self.request_options,
            )

        response = retry_call(
            _call,
            should_retry=self._is_retryable_error,
            policy=self.retry_policy,
        )
        return self._translate_response(response)

    def stream(
        self,
        *,
        system_prompt: str,
        messages: list[TurnMessage],
        tools: list[dict[str, Any]],
    ) -> Iterator[Any]:
        """Synthesise a stream from the non-streaming response.

        Not truly incremental but keeps the orchestrator's renderer
        contract uniform; token-by-token streaming can land later by
        mapping OpenAI's streaming deltas."""
        response = self.complete(
            system_prompt=system_prompt,
            messages=messages,
            tools=tools,
        )
        yield from events_from_model_response(response)

    # ------------------------------------------------------------------ translation

    def _ensure_client(self) -> Any:
        if self._client is None:
            key = self.api_key or os.environ.get("OPENAI_API_KEY") or ""
            if not key:
                raise RuntimeError(
                    "OPENAI_API_KEY not set; pass api_key= or export the env var."
                )
            self._client = self.sdk_factory(key)
        return self._client

    @staticmethod
    def _translate_messages(
        system_prompt: str,
        messages: list[TurnMessage],
    ) -> list[dict[str, Any]]:
        """Convert our shape to OpenAI chat-completions messages.

        Tool results are flattened into ``tool``-role messages keyed by
        ``tool_call_id`` so OpenAI can match them with the originating
        tool_use in the assistant turn before. Assistant tool_use blocks
        become ``tool_calls`` entries on the assistant message."""
        translated: list[dict[str, Any]] = []
        if system_prompt:
            translated.append({"role": "system", "content": system_prompt})

        for message in messages:
            if isinstance(message.content, str):
                translated.append({"role": message.role, "content": message.content})
                continue
            # Block-shaped content.
            if message.role == "assistant":
                text_parts: list[str] = []
                tool_calls: list[dict[str, Any]] = []
                for block in message.content:
                    if isinstance(block, AssistantTextBlock):
                        text_parts.append(block.text)
                    elif isinstance(block, AssistantToolUseBlock):
                        tool_calls.append(_openai_tool_call(block))
                entry: dict[str, Any] = {"role": "assistant"}
                if text_parts:
                    entry["content"] = "".join(text_parts)
                if tool_calls:
                    entry["tool_calls"] = tool_calls
                translated.append(entry)
                continue
            if message.role == "user":
                # Tool-result list or text list — flatten into OpenAI's
                # ``tool`` messages plus residual text.
                text_parts = []
                tool_messages: list[dict[str, Any]] = []
                for block in message.content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        tool_messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": block.get("tool_use_id", ""),
                                "content": str(block.get("content", "")),
                            }
                        )
                    else:
                        text_parts.append(_stringify_block(block))
                if text_parts:
                    translated.append({"role": "user", "content": "\n".join(text_parts)})
                translated.extend(tool_messages)
        return translated

    def _translate_response(self, response: Any) -> ModelResponse:
        """Build a :class:`ModelResponse` from an OpenAI SDK return."""
        choices = getattr(response, "choices", None) or []
        if not choices:
            return ModelResponse(blocks=[], stop_reason="end_turn")
        choice = choices[0]
        message = getattr(choice, "message", None)
        finish_reason = getattr(choice, "finish_reason", None) or "end_turn"
        blocks: list[Any] = []

        content = getattr(message, "content", None) or ""
        if content:
            blocks.append(AssistantTextBlock(text=str(content)))

        for call in getattr(message, "tool_calls", []) or []:
            function = getattr(call, "function", None)
            arguments_raw = getattr(function, "arguments", "") if function else ""
            name = getattr(function, "name", "") if function else ""
            blocks.append(
                AssistantToolUseBlock(
                    id=getattr(call, "id", "") or "",
                    name=name,
                    input=_parse_arguments(arguments_raw),
                )
            )

        stop_reason = "tool_use" if finish_reason == "tool_calls" else finish_reason

        usage = getattr(response, "usage", None)
        usage_dict: dict[str, int] = {}
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = getattr(usage, key, None) if usage is not None else None
            if value is None:
                continue
            try:
                usage_dict[key] = int(value)
            except (TypeError, ValueError):
                continue

        return ModelResponse(blocks=blocks, stop_reason=stop_reason, usage=usage_dict)

    @staticmethod
    def _is_retryable_error(exc: BaseException) -> bool:
        status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
        if isinstance(status, int) and status in {408, 409, 425, 429, 500, 502, 503, 504}:
            return True
        name = type(exc).__name__.lower()
        return any(token in name for token in ("ratelimit", "timeout", "apistatus"))


def _translate_tool_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Translate an Anthropic-shape tool schema into an OpenAI tool spec.

    Anthropic packs the schema flat (``name``, ``description``,
    ``input_schema``); OpenAI wraps it under ``function``. We produce
    the OpenAI shape so the orchestrator can pass the same registry
    schema to either client."""
    return {
        "type": "function",
        "function": {
            "name": schema.get("name", ""),
            "description": schema.get("description", ""),
            "parameters": schema.get("input_schema", {"type": "object"}),
        },
    }


def _openai_tool_call(block: AssistantToolUseBlock) -> dict[str, Any]:
    import json as _json

    return {
        "id": block.id,
        "type": "function",
        "function": {
            "name": block.name,
            "arguments": _json.dumps(block.input or {}),
        },
    }


def _stringify_block(block: Any) -> str:
    if isinstance(block, dict):
        if block.get("type") == "text":
            return str(block.get("text", ""))
        return str(block)
    return str(block)


def _parse_arguments(raw: str) -> dict[str, Any]:
    import json as _json

    if not raw or not raw.strip():
        return {}
    try:
        parsed = _json.loads(raw)
    except _json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


__all__ = ["OpenAIClient"]
