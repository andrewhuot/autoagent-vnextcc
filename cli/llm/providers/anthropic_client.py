"""Anthropic :class:`~cli.llm.types.ModelClient` implementation.

Lazy import of the ``anthropic`` SDK means the module loads on systems
without the dependency — users who never call Anthropic never see the
import error. Tests drive the streaming path through a fake SDK object
injected via the constructor, so full coverage lands without network.

Responsibilities kept inside this module:

* Translate :class:`~cli.llm.types.TurnMessage` into Anthropic's
  ``messages`` wire format (string content stays a string; list content
  pre-shaped by the orchestrator passes through as-is).
* Translate tool schemas from our Anthropic-shape records.
* Convert SDK streaming events into :mod:`cli.llm.streaming` events.
* Apply :mod:`cli.llm.retries` for rate-limit / transient errors.
* Attach prompt-cache breakpoints via :mod:`cli.llm.caching`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, Iterator

from cli.llm.caching import CacheInput, compute_cache_blocks
from cli.llm.provider_capabilities import ProviderCapabilities
from cli.llm.retries import RetryPolicy, retry_call
from cli.llm.streaming import (
    MessageStop,
    TextDelta,
    ThinkingDelta,
    ToolUseDelta,
    ToolUseEnd,
    ToolUseStart,
    UsageDelta,
    collect_stream,
)
from cli.llm.types import ModelResponse, TurnMessage


DEFAULT_MAX_OUTPUT_TOKENS = 8192
"""Leaves room for long tool chains without blowing the per-request
budget. Callers override via :class:`AnthropicClient(max_output_tokens=...)`."""


SdkFactory = Callable[[str], Any]
"""Signature of a callable that returns a configured Anthropic client
given an API key. The production default imports ``anthropic`` lazily;
tests inject a fake that records the args received."""


def _default_sdk_factory(api_key: str) -> Any:
    """Return a real ``anthropic.Anthropic`` client.

    Imported here so modules that never construct an Anthropic client
    don't need the SDK installed. Any adapter-wide SDK tweaks (custom
    base URL, timeout) plug in here so the provider-specific concern
    stays in one place."""
    import anthropic  # type: ignore[import-not-found]

    return anthropic.Anthropic(api_key=api_key)


@dataclass
class AnthropicClient:
    """Streaming Anthropic client implementing both
    :meth:`~cli.llm.types.ModelClient.complete` and
    :meth:`~cli.llm.streaming.StreamingModelClient.stream`.

    Construction accepts either a real SDK factory (default) or an
    injected fake for tests. The fake must implement
    ``messages.stream(**kwargs)`` returning a context-manager that
    yields SDK event objects with ``.type`` and event-specific fields."""

    capabilities: ClassVar[ProviderCapabilities] = ProviderCapabilities(
        streaming=True,
        native_tool_use=True,
        parallel_tool_calls=True,
        thinking=True,
        prompt_cache=True,
        vision=True,
        json_mode=True,
        max_context_tokens=200_000,
        max_output_tokens=8192,
    )
    """Declared runtime surface. Claude 4.x family: streaming + tool use
    + thinking + prompt cache + vision + JSON mode; 200k context, 8k
    default output ceiling (callers override via ``max_output_tokens``)."""

    model: str = "claude-sonnet-4-5"
    api_key: str | None = None
    """Falls back to ``ANTHROPIC_API_KEY`` env var. Kept as a field so
    tests can pass explicit keys without environment mutation."""

    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    sdk_factory: SdkFactory = field(default=_default_sdk_factory)
    """Factory hook — tests override with a fake SDK."""

    request_options: dict[str, Any] = field(default_factory=dict)
    """Extra kwargs forwarded to the SDK's ``messages.stream`` call —
    e.g. ``{"beta_headers": {"anthropic-beta": "prompt-caching-2024-07-31"}}``
    when the caller wants a specific beta opt-in."""

    _client: Any = field(default=None, init=False, repr=False)

    # ------------------------------------------------------------------ API

    def complete(
        self,
        *,
        system_prompt: str,
        messages: list[TurnMessage],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        """Non-streaming entry point. Delegates to :meth:`stream` and
        folds the events back into a :class:`ModelResponse` so both
        entry points share one code path."""
        return collect_stream(
            self.stream(
                system_prompt=system_prompt,
                messages=messages,
                tools=tools,
            )
        )

    def stream(
        self,
        *,
        system_prompt: str,
        messages: list[TurnMessage],
        tools: list[dict[str, Any]],
    ) -> Iterator[Any]:
        """Run a streaming request and yield :mod:`cli.llm.streaming`
        events.

        The retry loop wraps the initial connection only; partial streams
        that drop midway are not retried automatically because the model
        has already produced some content and restarting would double
        the output."""

        def _call():
            return self._open_stream(
                system_prompt=system_prompt,
                messages=messages,
                tools=tools,
            )

        stream_context = retry_call(
            _call,
            should_retry=self._is_retryable_error,
            policy=self.retry_policy,
        )

        with stream_context as sdk_stream:
            yield from self._translate_events(sdk_stream)

    # ------------------------------------------------------------------ internal

    def _ensure_client(self) -> Any:
        if self._client is None:
            key = self.api_key or os.environ.get("ANTHROPIC_API_KEY") or ""
            if not key:
                raise RuntimeError(
                    "ANTHROPIC_API_KEY not set; pass api_key= or export the env var."
                )
            self._client = self.sdk_factory(key)
        return self._client

    def _open_stream(
        self,
        *,
        system_prompt: str,
        messages: list[TurnMessage],
        tools: list[dict[str, Any]],
    ) -> Any:
        client = self._ensure_client()
        request_kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_output_tokens,
            "messages": [self._translate_message(m) for m in messages],
            "tools": tools,
            **self.request_options,
        }
        cache_blocks = compute_cache_blocks(
            CacheInput(
                system_prompt=system_prompt,
                tool_schema_text=_compact_json(tools),
            )
        )
        if cache_blocks:
            request_kwargs["system"] = cache_blocks
        elif system_prompt:
            request_kwargs["system"] = system_prompt

        return client.messages.stream(**request_kwargs)

    @staticmethod
    def _translate_message(message: TurnMessage) -> dict[str, Any]:
        """Translate a :class:`TurnMessage` into the SDK's expected shape.

        List content passes through as-is because the orchestrator
        already constructs Anthropic-shape tool_use / tool_result
        blocks. String content becomes ``[{type: text, text: ...}]``
        which the SDK accepts in both forms but the list form avoids a
        silent coercion."""
        if isinstance(message.content, list):
            return {"role": message.role, "content": message.content}
        return {
            "role": message.role,
            "content": [{"type": "text", "text": str(message.content)}],
        }

    @staticmethod
    def _translate_events(sdk_stream: Any) -> Iterator[Any]:
        """Convert SDK events into :mod:`cli.llm.streaming` events.

        We duck-type rather than importing SDK symbols so the translator
        stays valid across SDK versions that rename internal classes."""
        active_tool_uses: dict[str, str] = {}
        for event in sdk_stream:
            event_type = getattr(event, "type", None)
            if event_type == "content_block_start":
                block = getattr(event, "content_block", None)
                block_type = getattr(block, "type", None)
                if block_type == "tool_use":
                    tool_id = getattr(block, "id", "")
                    name = getattr(block, "name", "")
                    active_tool_uses[tool_id] = name
                    yield ToolUseStart(id=tool_id, name=name)
            elif event_type == "content_block_delta":
                delta = getattr(event, "delta", None)
                delta_type = getattr(delta, "type", None)
                if delta_type == "text_delta":
                    yield TextDelta(text=getattr(delta, "text", ""))
                elif delta_type == "thinking_delta":
                    yield ThinkingDelta(text=getattr(delta, "thinking", ""))
                elif delta_type == "input_json_delta":
                    # Claude streams tool input as partial JSON strings.
                    tool_index = getattr(event, "index", None)
                    # Fall back to the most-recent tool id when the SDK
                    # doesn't carry one on the delta.
                    tool_id = _tool_id_for_index(active_tool_uses, tool_index)
                    yield ToolUseDelta(
                        id=tool_id,
                        input_json=getattr(delta, "partial_json", ""),
                    )
            elif event_type == "content_block_stop":
                block = getattr(event, "content_block", None)
                if getattr(block, "type", None) == "tool_use":
                    tool_id = getattr(block, "id", "")
                    yield ToolUseEnd(
                        id=tool_id,
                        name=active_tool_uses.get(tool_id, ""),
                        input=getattr(block, "input", None) or {},
                    )
            elif event_type == "message_delta":
                usage = getattr(event, "usage", None)
                usage_dict = _coerce_usage(usage)
                if usage_dict:
                    yield UsageDelta(usage=usage_dict)
            elif event_type == "message_stop":
                message = getattr(event, "message", None)
                stop_reason = getattr(message, "stop_reason", None) or "end_turn"
                usage = getattr(message, "usage", None)
                final_usage = _coerce_usage(usage)
                if final_usage:
                    yield UsageDelta(usage=final_usage)
                yield MessageStop(stop_reason=stop_reason)

    @staticmethod
    def _is_retryable_error(exc: BaseException) -> bool:
        """Identify retryable errors without importing the SDK.

        We match on class name + HTTP status when the SDK exposes one.
        Keeping the match string-based means a one-line change here
        handles a new SDK error subclass without touching the rest of
        the adapter."""
        status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
        if isinstance(status, int) and status in {408, 409, 425, 429, 500, 502, 503, 504}:
            return True
        name = type(exc).__name__.lower()
        return any(token in name for token in ("ratelimit", "timeout", "apistatus"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tool_id_for_index(active: dict[str, str], index: Any) -> str:
    """Best-effort resolution of a tool id when only a block index is known.

    Anthropic's streaming API currently emits tool-use deltas keyed by a
    block ``index`` rather than the tool id. We assume the most recently
    seen tool id is the right target when the SDK doesn't carry an
    explicit id on the delta event — correct for the common
    single-tool-at-a-time case."""
    if index is not None and isinstance(index, int) and active:
        keys = list(active.keys())
        if 0 <= index < len(keys):
            return keys[index]
    if active:
        return next(reversed(active))
    return ""


def _coerce_usage(usage: Any) -> dict[str, int]:
    """Turn an SDK usage record into a plain dict of ints."""
    if usage is None:
        return {}
    result: dict[str, int] = {}
    for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens",
                "cache_read_input_tokens"):
        value = getattr(usage, key, None)
        if value is None:
            continue
        try:
            result[key] = int(value)
        except (TypeError, ValueError):
            continue
    return result


def _compact_json(tools: list[dict[str, Any]]) -> str:
    """Stable JSON serialisation for cache-content fingerprinting.

    We don't round-trip this — it's only used to size the cache
    breakpoint. Sorted keys keep hashable equality stable across
    identical tool lists that happen to arrive in different iteration
    orders."""
    import json as _json

    return _json.dumps(tools, sort_keys=True, separators=(",", ":"))


__all__ = ["AnthropicClient", "DEFAULT_MAX_OUTPUT_TOKENS", "SdkFactory"]
