"""Gemini :class:`~cli.llm.types.ModelClient` implementation.

Follows the same shape as :mod:`cli.llm.providers.anthropic_client`:
lazy SDK import, injectable ``sdk_factory`` for tests, ``complete()``
delegates to ``collect_stream(self.stream(...))``, duck-typed event
translation so the translator stays valid across SDK version changes.

The ``google-genai`` SDK is an **optional** extra. Importing this module
must not raise when the SDK is absent; the install hint surfaces only at
:class:`GeminiClient` construction time via the default sdk_factory.

Key translation concerns (from the P0.5c task spec):

* System prompt maps to ``config=GenerateContentConfig(system_instruction=...)``
  rather than a message.
* Messages become a Gemini ``Content`` list — user/assistant roles map
  directly, and tool results round-trip through
  ``Part.from_function_response``.
* Tool schemas are translated via
  :func:`cli.llm.tool_schema_translator.to_gemini` and wrapped in
  ``types.Tool(function_declarations=[...])``.
* Streaming yields chunks whose ``candidates[0].content.parts[]`` carry
  text, thought text (``thought=True``), or function-call parts.
* ``finish_reason`` on the final chunk maps to a normalised
  :attr:`ModelResponse.stop_reason` — ``STOP``→``end_turn``,
  ``MAX_TOKENS``→``max_tokens``, ``SAFETY`` / ``RECITATION`` /
  ``PROHIBITED_CONTENT`` all surface as ``"safety"``.
* Manual function calling only — we pin
  ``automatic_function_calling=AutomaticFunctionCallingConfig(disable=True)``
  because the orchestrator owns dispatch and permissioning.
* Thinking config is enabled for 2.5 models so the adapter can emit
  :class:`ThinkingDelta` events.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, Iterator

from cli.llm.provider_capabilities import ProviderCapabilities
from cli.llm.retries import RetryPolicy, retry_call
from cli.llm.streaming import (
    MessageStop,
    TextDelta,
    ThinkingDelta,
    ToolUseEnd,
    ToolUseStart,
    UsageDelta,
    collect_stream,
)
from cli.llm.tool_schema_translator import to_gemini
from cli.llm.types import (
    AssistantTextBlock,
    AssistantToolUseBlock,
    ModelResponse,
    TurnMessage,
)


DEFAULT_MAX_OUTPUT_TOKENS = 8192
"""Default output ceiling for Gemini 2.5 / 2.0 Flash. Callers override
via :class:`GeminiClient(max_output_tokens=...)`."""


SdkFactory = Callable[[str], Any]
"""Callable that returns a configured ``google.genai.Client`` given an
API key. Production default imports ``google.genai`` lazily; tests
inject a :class:`FakeGeminiSDK` via the constructor."""


_INSTALL_HINT = (
    "google-genai is not installed. Install with: "
    "`pip install 'agentlab[gemini]'` or `pip install 'google-genai>=1.15,<1.16'`."
)


def _default_sdk_factory(api_key: str) -> Any:
    """Return a real ``google.genai.Client`` — lazy import.

    Raises :class:`RuntimeError` with a clear install hint when the
    optional dependency is missing, rather than letting
    ``ModuleNotFoundError`` propagate unannotated."""
    try:
        from google import genai  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(_INSTALL_HINT) from exc
    return genai.Client(api_key=api_key)


@dataclass
class GeminiClient:
    """Streaming Gemini client implementing both
    :meth:`~cli.llm.types.ModelClient.complete` and
    :meth:`~cli.llm.streaming.StreamingModelClient.stream`.

    Construction accepts either a real SDK factory (default) or an
    injected fake for tests. The fake must implement
    ``models.generate_content_stream(**kwargs)`` returning an iterable
    of chunk objects duck-typed to
    ``candidates[0].content.parts``, ``candidates[0].finish_reason``,
    and ``usage_metadata``."""

    capabilities: ClassVar[ProviderCapabilities] = ProviderCapabilities(
        streaming=True,
        native_tool_use=True,
        parallel_tool_calls=True,
        thinking=True,
        prompt_cache=False,
        vision=True,
        json_mode=True,
        max_context_tokens=1_048_576,
        max_output_tokens=8192,
    )
    """Declared runtime surface. Gemini 2.5 Pro family: streaming + tool
    use + thinking + vision + JSON mode. ``prompt_cache=False`` because
    the SDK lacks the content-handle API today — follow-up task."""

    model: str = "gemini-2.5-pro"
    api_key: str | None = None
    """Falls back to ``GEMINI_API_KEY`` then ``GOOGLE_API_KEY`` env
    vars. Kept as a field so tests can pass explicit keys without
    environment mutation."""

    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    sdk_factory: SdkFactory = field(default=_default_sdk_factory)
    """Factory hook — tests override with a fake SDK."""

    request_options: dict[str, Any] = field(default_factory=dict)
    """Extra kwargs forwarded to the SDK's ``generate_content_stream``
    call. Keys matching the SDK's ``config=`` fields are merged into the
    GenerateContentConfig we build; unknown keys pass through at the
    top level so the adapter doesn't lock out future SDK options."""

    _client: Any = field(default=None, init=False, repr=False)

    # ------------------------------------------------------------------ API

    def complete(
        self,
        *,
        system_prompt: str,
        messages: list[TurnMessage],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        """Non-streaming entry point — folds the streaming events into
        one :class:`ModelResponse` so both entry points share a code path."""
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
        events. Retries only the initial connection — mid-stream drops
        are not replayed because the model has already produced
        content."""

        def _call() -> Any:
            return self._open_stream(
                system_prompt=system_prompt,
                messages=messages,
                tools=tools,
            )

        sdk_stream = retry_call(
            _call,
            should_retry=self._is_retryable_error,
            policy=self.retry_policy,
        )
        yield from self._translate_events(sdk_stream)

    def cache_hint(self, blocks: list[Any]) -> None:
        """Prompt-cache hint dispatched by the orchestrator. No-op today;
        the Gemini SDK currently lacks the content-handle API we'd need
        to honour explicit breakpoints — follow-up task will wire the
        cached-content handle surface. Kept on the class so orchestrator
        code stays provider-agnostic (see P0.5f). Logs at DEBUG so users
        don't see noise on every turn."""
        if blocks:
            import logging

            logging.getLogger(__name__).debug(
                "gemini_client.cache_hint: received %d block(s); ignoring — "
                "SDK lacks cached-content handle API (follow-up).",
                len(blocks),
            )

    # ------------------------------------------------------------------ internal

    def _ensure_client(self) -> Any:
        if self._client is None:
            key = (
                self.api_key
                or os.environ.get("GEMINI_API_KEY")
                or os.environ.get("GOOGLE_API_KEY")
                or ""
            )
            if not key:
                raise RuntimeError(
                    "Gemini API key not set; pass api_key= or export "
                    "GEMINI_API_KEY / GOOGLE_API_KEY."
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
        contents = [self._translate_message(m) for m in messages]
        config = self._build_config(system_prompt=system_prompt, tools=tools)

        request_kwargs: dict[str, Any] = {
            "model": self.model,
            "contents": contents,
            "config": config,
            **{k: v for k, v in self.request_options.items() if k not in {"config"}},
        }
        return client.models.generate_content_stream(**request_kwargs)

    def _build_config(
        self,
        *,
        system_prompt: str,
        tools: list[dict[str, Any]],
    ) -> Any:
        """Construct a ``GenerateContentConfig`` duck-typed against the
        real SDK so both fake and real SDKs accept it.

        Falls back to a plain dict when the SDK isn't available (tests
        using ``FakeGeminiSDK`` inspect ``captured_kwargs`` rather than
        calling into the SDK, so either shape works for them — the
        adapter's job is to *always* emit the same structure)."""
        extras = dict(self.request_options.get("config", {}) or {})

        tool_declarations = [to_gemini(t) for t in tools]

        try:
            from google.genai import types as genai_types  # type: ignore[import-not-found]
        except ImportError:
            genai_types = None

        if genai_types is not None:
            tool_obj = None
            if tool_declarations:
                tool_obj = genai_types.Tool(
                    function_declarations=[
                        genai_types.FunctionDeclaration(**decl)
                        for decl in tool_declarations
                    ]
                )
            config_kwargs: dict[str, Any] = {
                "max_output_tokens": self.max_output_tokens,
                "automatic_function_calling": (
                    genai_types.AutomaticFunctionCallingConfig(disable=True)
                ),
            }
            if system_prompt:
                config_kwargs["system_instruction"] = system_prompt
            if tool_obj is not None:
                config_kwargs["tools"] = [tool_obj]
            if self._is_thinking_model():
                config_kwargs["thinking_config"] = genai_types.ThinkingConfig(
                    include_thoughts=True
                )
            config_kwargs.update(extras)
            return genai_types.GenerateContentConfig(**config_kwargs)

        # SDK unavailable — build a plain dict so the fake can introspect it.
        fake_tools: list[dict[str, Any]] = []
        if tool_declarations:
            fake_tools.append({"function_declarations": tool_declarations})
        config_kwargs = {
            "max_output_tokens": self.max_output_tokens,
            "automatic_function_calling": {"disable": True},
        }
        if system_prompt:
            config_kwargs["system_instruction"] = system_prompt
        if fake_tools:
            config_kwargs["tools"] = fake_tools
        if self._is_thinking_model():
            config_kwargs["thinking_config"] = {"include_thoughts": True}
        config_kwargs.update(extras)
        return config_kwargs

    def _is_thinking_model(self) -> bool:
        """Thinking surface only lights up for the 2.5 family today.

        Older Gemini models (1.5, 2.0) silently reject
        ``thinking_config`` so we must not attach it unconditionally."""
        return self.model.lower().startswith("gemini-2.5")

    def _translate_message(self, message: TurnMessage) -> Any:
        """Translate a :class:`TurnMessage` into Gemini's ``Content`` shape.

        We build plain dicts; the SDK accepts the dict form everywhere
        it accepts ``types.Content`` and this keeps the fake-SDK path
        identical to the real one."""
        role = "user" if message.role == "user" else "model"
        if isinstance(message.content, str):
            return {"role": role, "parts": [{"text": str(message.content)}]}

        parts: list[dict[str, Any]] = []
        for block in message.content:
            if isinstance(block, AssistantTextBlock):
                parts.append({"text": block.text})
                continue
            if isinstance(block, AssistantToolUseBlock):
                parts.append(
                    {
                        "function_call": {
                            "name": block.name,
                            "args": dict(block.input or {}),
                        }
                    }
                )
                continue
            if isinstance(block, dict):
                btype = block.get("type")
                if btype == "text":
                    parts.append({"text": str(block.get("text", ""))})
                    continue
                if btype == "tool_use":
                    parts.append(
                        {
                            "function_call": {
                                "name": block.get("name", ""),
                                "args": dict(block.get("input", {}) or {}),
                            }
                        }
                    )
                    continue
                if btype == "tool_result":
                    # Tool results flip to Gemini's ``function`` role — the
                    # SDK's convention for a reply to a prior function_call.
                    return {
                        "role": "function",
                        "parts": [
                            {
                                "function_response": {
                                    "name": block.get("name", ""),
                                    "response": _coerce_function_response(
                                        block.get("content")
                                    ),
                                }
                            }
                        ],
                    }
            # Fallback — stringify unknown blocks so we never drop content.
            parts.append({"text": str(block)})
        return {"role": role, "parts": parts}

    @staticmethod
    def _translate_events(sdk_stream: Any) -> Iterator[Any]:
        """Convert Gemini SDK chunks into :mod:`cli.llm.streaming` events.

        We duck-type every access so a chunk built by ``SimpleNamespace``
        (our fake) or a real ``GenerateContentResponse`` both translate.
        """
        final_stop_reason = "end_turn"
        final_usage: dict[str, int] = {}
        seen_function_call_ids: set[str] = set()

        for chunk in sdk_stream:
            candidates = getattr(chunk, "candidates", None) or []
            for candidate in candidates:
                content = getattr(candidate, "content", None)
                parts = getattr(content, "parts", None) or []
                for part in parts:
                    function_call = getattr(part, "function_call", None)
                    if function_call is not None:
                        name = getattr(function_call, "name", "") or ""
                        raw_args = getattr(function_call, "args", None)
                        args = _coerce_args(raw_args)
                        tool_id = (
                            getattr(function_call, "id", None)
                            or getattr(part, "function_call_id", None)
                            or _synthetic_tool_id(name, seen_function_call_ids)
                        )
                        if tool_id not in seen_function_call_ids:
                            seen_function_call_ids.add(tool_id)
                            yield ToolUseStart(id=tool_id, name=name)
                        yield ToolUseEnd(id=tool_id, name=name, input=args)
                        continue

                    text_value = getattr(part, "text", None)
                    if text_value:
                        is_thought = bool(getattr(part, "thought", False))
                        if is_thought:
                            yield ThinkingDelta(text=str(text_value))
                        else:
                            yield TextDelta(text=str(text_value))

                finish_reason = getattr(candidate, "finish_reason", None)
                if finish_reason is not None:
                    final_stop_reason = _map_finish_reason(finish_reason)

            usage = getattr(chunk, "usage_metadata", None)
            if usage is not None:
                final_usage = _coerce_usage(usage)

        if final_usage:
            yield UsageDelta(usage=final_usage)
        yield MessageStop(stop_reason=final_stop_reason)

    @staticmethod
    def _is_retryable_error(exc: BaseException) -> bool:
        """Identify retryable errors without importing the SDK.

        Matches on HTTP status + class-name tokens so a new SDK error
        subclass doesn't need a code change. Excludes 400/403 and
        safety-block errors — those are permanent."""
        status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
        if isinstance(status, int):
            if status in {408, 409, 425, 429, 500, 502, 503, 504}:
                return True
            if status in {400, 401, 403, 404, 422}:
                return False
        name = type(exc).__name__.lower()
        if any(token in name for token in ("safety", "blocked", "prohibit", "permission")):
            return False
        return any(
            token in name
            for token in (
                "ratelimit",
                "resourceexhausted",
                "timeout",
                "unavailable",
                "deadline",
                "apistatus",
                "serverovercapacity",
            )
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_FINISH_REASON_MAP = {
    "STOP": "end_turn",
    "MAX_TOKENS": "max_tokens",
    "SAFETY": "safety",
    "RECITATION": "safety",
    "PROHIBITED_CONTENT": "safety",
    "BLOCKLIST": "safety",
    "SPII": "safety",
    "LANGUAGE": "safety",
    "MALFORMED_FUNCTION_CALL": "end_turn",
    "OTHER": "end_turn",
    "UNSPECIFIED": "end_turn",
    "FINISH_REASON_UNSPECIFIED": "end_turn",
}


def _map_finish_reason(raw: Any) -> str:
    """Normalise Gemini's finish reason to our stop_reason vocabulary.

    The SDK emits either a string-valued enum or a ``FinishReason`` with
    a ``.name`` attribute; we handle both. Unknown values log through as
    ``end_turn`` rather than raising — a new enum value shouldn't crash
    the adapter."""
    import logging

    token = getattr(raw, "name", None) or str(raw)
    token = token.upper().rsplit(".", 1)[-1]
    mapped = _FINISH_REASON_MAP.get(token)
    if mapped is None:
        logging.getLogger(__name__).warning(
            "gemini_client: unknown finish_reason %r, treating as end_turn", token
        )
        return "end_turn"
    return mapped


def _coerce_args(raw: Any) -> dict[str, Any]:
    """Turn a Gemini FunctionCall.args value into a plain dict.

    Real SDK returns a ``proto.marshal.collections.maps.MapComposite``
    that implements the Mapping protocol; the fake emits plain dicts.
    JSON strings are parsed defensively so a mis-shaped fake doesn't
    break the translator."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        import json as _json

        try:
            parsed = _json.loads(raw)
        except _json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    try:
        return dict(raw)
    except (TypeError, ValueError):
        return {}


def _coerce_usage(usage: Any) -> dict[str, int]:
    """Map Gemini's ``usage_metadata`` to our usage dict shape.

    Keeps our orchestrator's vocabulary — ``input_tokens``,
    ``output_tokens``, ``reasoning_tokens``, ``cache_read_tokens`` —
    rather than re-exporting Google's field names."""
    if usage is None:
        return {}
    out: dict[str, int] = {}
    mapping = {
        "prompt_token_count": "input_tokens",
        "candidates_token_count": "output_tokens",
        "thoughts_token_count": "reasoning_tokens",
        "cached_content_token_count": "cache_read_tokens",
    }
    for src, dst in mapping.items():
        value = getattr(usage, src, None)
        if value is None and isinstance(usage, dict):
            value = usage.get(src)
        if value is None:
            continue
        try:
            out[dst] = int(value)
        except (TypeError, ValueError):
            continue
    return out


def _coerce_function_response(content: Any) -> dict[str, Any]:
    """Shape a tool_result payload for Gemini's ``function_response.response``.

    The SDK expects a mapping; string content becomes ``{"content": ...}``
    so we never hand the SDK a non-dict and trigger a validation error."""
    if isinstance(content, dict):
        return content
    if isinstance(content, list):
        texts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(str(item.get("text", "")))
            else:
                texts.append(str(item))
        return {"content": "\n".join(texts)}
    return {"content": str(content) if content is not None else ""}


def _synthetic_tool_id(name: str, already_seen: set[str]) -> str:
    """Fabricate a stable tool_use id when Gemini doesn't supply one.

    Gemini's FunctionCall doesn't always carry an id field; we need one
    so ``ToolUseStart`` / ``ToolUseEnd`` can pair and so tool_result
    blocks later can target the right call."""
    base = f"gemini-{name or 'tool'}"
    candidate = base
    counter = 1
    while candidate in already_seen:
        counter += 1
        candidate = f"{base}-{counter}"
    return candidate


__all__ = ["GeminiClient", "DEFAULT_MAX_OUTPUT_TOKENS", "SdkFactory"]
