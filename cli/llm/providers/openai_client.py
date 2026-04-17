"""OpenAI :class:`~cli.llm.types.ModelClient` implementation.

Streams ``chat.completions.create(stream=True)`` chunks and translates
them into the provider-agnostic :mod:`cli.llm.streaming` event shape.
The adapter shape mirrors :mod:`cli.llm.providers.anthropic_client` —
lazy SDK import, injectable ``sdk_factory`` for tests, retries around
the initial connection via :class:`cli.llm.retries.RetryPolicy`.

Key translation rules:

* ``choices[0].delta.content`` → :class:`TextDelta`.
* ``choices[0].delta.reasoning_content`` → :class:`ThinkingDelta`
  (``o1`` / ``o3`` / ``o4`` reasoning models).
* ``choices[0].delta.tool_calls`` — per-call accumulator keyed by ``id``
  (falling back to ``index`` when ``id`` is absent on a non-first
  fragment). ``function.arguments`` is a JSON string streamed in
  fragments; we accumulate and ``json.loads`` **once** at
  :class:`ToolUseEnd` — partial JSON is never parsed.
* ``finish_reason`` normalises to our stop-reason vocabulary:
  ``stop``→``end_turn``, ``length``→``max_tokens``,
  ``tool_calls``→``tool_use``, ``content_filter``→``safety``. Unknown
  values log a warning and degrade to ``end_turn``.
* Streaming usage requires ``stream_options={"include_usage": True}`` —
  always passed; the final chunk carries ``usage.prompt_tokens``,
  ``usage.completion_tokens``, ``completion_tokens_details.reasoning_tokens``
  (reasoning models), and ``prompt_tokens_details.cached_tokens``
  (server-side prefix cache).

``complete()`` keeps the non-streaming code path — it's used by legacy
callers that want a single :class:`ModelResponse` without the streaming
machinery (print-mode checks, EchoModel parity tests). New callers go
through :meth:`stream`.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

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
)
from cli.llm.tool_schema_translator import to_openai
from cli.llm.types import (
    AssistantTextBlock,
    AssistantToolUseBlock,
    ModelResponse,
    TurnMessage,
)


logger = logging.getLogger(__name__)


SdkFactory = Callable[[str], Any]


def _default_sdk_factory(api_key: str) -> Any:
    import openai  # type: ignore[import-not-found]

    return openai.OpenAI(api_key=api_key)


# Reasoning-model prefixes that expose ``reasoning_content`` deltas and
# therefore light up :class:`ThinkingDelta` emission + the ``thinking``
# capability bit. Kept as a module-level tuple so both the capability
# property and the stream translator read the same list.
_REASONING_MODEL_PREFIXES: tuple[str, ...] = ("o1", "o3", "o4")


def _is_reasoning_model(model: str) -> bool:
    """Return True for OpenAI reasoning models (``o1``/``o3``/``o4`` families).

    Matches on the ``-`` suffix boundary so ``gpt-4o`` (starts with
    ``o`` if you squint, but has a ``gpt-`` prefix) doesn't misclassify."""
    lower = model.lower()
    return any(
        lower == prefix or lower.startswith(prefix + "-") or lower.startswith(prefix + "_")
        for prefix in _REASONING_MODEL_PREFIXES
    )


# Mapping from OpenAI's ``finish_reason`` to our canonical ``stop_reason``
# vocabulary. Any unknown value degrades to ``end_turn`` with a warning —
# never a crash.
_FINISH_REASON_MAP: dict[str, str] = {
    "stop": "end_turn",
    "length": "max_tokens",
    "tool_calls": "tool_use",
    "content_filter": "safety",
    "function_call": "tool_use",  # legacy single-function call — treat as tool_use.
}


def _map_finish_reason(raw: Any) -> str:
    if raw is None:
        return "end_turn"
    key = str(raw)
    mapped = _FINISH_REASON_MAP.get(key)
    if mapped is None:
        logger.warning(
            "openai_client: unknown finish_reason %r, treating as end_turn", raw
        )
        return "end_turn"
    return mapped


@dataclass
class OpenAIClient:
    """Streaming OpenAI chat-completions client."""

    model: str = "gpt-4o"
    api_key: str | None = None
    max_output_tokens: int = 4096
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    sdk_factory: SdkFactory = field(default=_default_sdk_factory)
    request_options: dict[str, Any] = field(default_factory=dict)

    _client: Any = field(default=None, init=False, repr=False)

    # ------------------------------------------------------------------ capabilities

    # Declared at class level so ``OpenAIClient.capabilities`` resolves
    # without an instance (orchestrator introspection). Instances route
    # through :class:`_CapabilitiesDescriptor` below to pick a per-model
    # row (reasoning models flip ``thinking=True``; gpt-4.1/gpt-5 raise
    # the context window). ``capabilities`` is not a dataclass field —
    # it's attached below the class definition.

    # ------------------------------------------------------------------ API

    def complete(
        self,
        *,
        system_prompt: str,
        messages: list[TurnMessage],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        """Non-streaming one-shot completion.

        Kept as a first-class code path rather than folding into
        ``collect_stream(self.stream(...))`` so pre-streaming tests and
        print-mode callers that expect a single response-object round trip
        don't accidentally exercise the streaming translator. The
        streaming path is still the primary entry point — see
        :meth:`stream`."""
        client = self._ensure_client()

        def _call() -> Any:
            return client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_output_tokens,
                messages=self._translate_messages(system_prompt, messages),
                tools=[to_openai(schema) for schema in tools],
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
        """Stream OpenAI chat-completions chunks as :mod:`cli.llm.streaming`
        events.

        Calls ``chat.completions.create(stream=True, stream_options=
        {"include_usage": True})`` and translates each chunk's delta into
        :class:`TextDelta` / :class:`ThinkingDelta` / tool-use events in
        real time. The retry loop wraps only the initial connection —
        mid-stream failures are not retried automatically because the
        model has already produced content."""

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
        """Prompt-cache hint dispatched by the orchestrator. No-op — OpenAI
        applies server-side automatic prefix caching past 1024 tokens, so
        the adapter has nothing to do. Kept on the class for provider-
        agnostic orchestrator code (see P0.5f)."""
        del blocks

    # ------------------------------------------------------------------ internal

    def _ensure_client(self) -> Any:
        if self._client is None:
            key = self.api_key or os.environ.get("OPENAI_API_KEY") or ""
            if not key:
                raise RuntimeError(
                    "OPENAI_API_KEY not set; pass api_key= or export the env var."
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
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_output_tokens,
            "messages": self._translate_messages(system_prompt, messages),
            "tools": [to_openai(schema) for schema in tools],
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        # Caller-provided request_options win over our defaults so they
        # can toggle (e.g.) a beta header or swap ``max_tokens`` for
        # ``max_completion_tokens`` on reasoning models.
        for key, value in self.request_options.items():
            kwargs[key] = value
        if not kwargs["tools"]:
            # OpenAI rejects ``tools=[]`` with some SDK versions; drop the
            # key when empty rather than sending an empty list.
            kwargs.pop("tools", None)
        return client.chat.completions.create(**kwargs)

    @staticmethod
    def _translate_messages(
        system_prompt: str,
        messages: list[TurnMessage],
    ) -> list[dict[str, Any]]:
        """Convert our shape to OpenAI chat-completions messages."""
        translated: list[dict[str, Any]] = []
        if system_prompt:
            translated.append({"role": "system", "content": system_prompt})

        for message in messages:
            if isinstance(message.content, str):
                translated.append({"role": message.role, "content": message.content})
                continue
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

    @staticmethod
    def _translate_events(sdk_stream: Any) -> Iterator[Any]:
        """Translate SDK streaming chunks into :mod:`cli.llm.streaming` events.

        Per-tool-call state lives in three dicts keyed by the tool-call
        ``id`` (fallback: ``index``):

        * ``names[id]`` — the tool name (only fragment 1 carries it).
        * ``buffers[id]`` — concatenated ``function.arguments`` JSON
          fragments. **Never parsed until the call closes** — partial
          JSON is invalid by construction.
        * ``index_to_id[index]`` — reverse map so continuation fragments
          that carry only ``index`` find the right accumulator.
        """
        names: dict[str, str] = {}
        buffers: dict[str, list[str]] = {}
        index_to_id: dict[int, str] = {}
        order: list[str] = []  # tool-call close order for parallel calls
        finish_reason: Any = None
        final_usage: dict[str, int] = {}

        def _close_tool(tool_id: str) -> Iterator[Any]:
            """Emit :class:`ToolUseEnd` with parsed arguments for ``tool_id``."""
            raw = "".join(buffers.get(tool_id, []))
            try:
                parsed = json.loads(raw) if raw.strip() else {}
            except json.JSONDecodeError:
                # Orchestrator's existing behaviour — never raise on a
                # malformed blob; the tool runner reports a clearer error.
                parsed = {}
            if not isinstance(parsed, dict):
                parsed = {}
            yield ToolUseEnd(
                id=tool_id,
                name=names.get(tool_id, ""),
                input=parsed,
            )

        for chunk in sdk_stream:
            choices = getattr(chunk, "choices", None) or []
            for choice in choices:
                delta = getattr(choice, "delta", None)
                if delta is not None:
                    text = getattr(delta, "content", None)
                    if text:
                        yield TextDelta(text=str(text))

                    reasoning = getattr(delta, "reasoning_content", None)
                    if reasoning:
                        yield ThinkingDelta(text=str(reasoning))
                    # Future-proof: some SDK variants surface thought via
                    # ``thought`` on the delta. Translate it the same way.
                    thought = getattr(delta, "thought", None)
                    if thought:
                        yield ThinkingDelta(text=str(thought))

                    raw_tool_calls = getattr(delta, "tool_calls", None) or []
                    for tool_call in raw_tool_calls:
                        tc_id = getattr(tool_call, "id", None)
                        tc_index = getattr(tool_call, "index", None)
                        # Resolve the accumulator key: prefer id when
                        # present, fall back to index→id lookup.
                        if tc_id:
                            if isinstance(tc_index, int):
                                index_to_id[tc_index] = tc_id
                            if tc_id not in buffers:
                                buffers[tc_id] = []
                                order.append(tc_id)
                        else:
                            if isinstance(tc_index, int) and tc_index in index_to_id:
                                tc_id = index_to_id[tc_index]
                            else:
                                # Pathological: no id, no resolvable index.
                                # Synthesise a stable key so the fragment
                                # isn't silently dropped.
                                tc_id = f"__unknown_{tc_index}"
                                if tc_id not in buffers:
                                    buffers[tc_id] = []
                                    order.append(tc_id)

                        function = getattr(tool_call, "function", None)
                        name = getattr(function, "name", None) if function else None
                        arguments = getattr(function, "arguments", None) if function else None

                        if name and tc_id not in names:
                            names[tc_id] = str(name)
                            yield ToolUseStart(id=tc_id, name=str(name))
                        elif tc_id not in names:
                            # First fragment lacked a name — emit Start
                            # with empty name so the event stream stays
                            # well-formed; downstream code fills it in
                            # when the name later arrives.
                            names[tc_id] = ""
                            yield ToolUseStart(id=tc_id, name="")

                        if arguments:
                            # Accumulate — never parse partial JSON.
                            buffers.setdefault(tc_id, []).append(str(arguments))
                            yield ToolUseDelta(
                                id=tc_id,
                                input_json=str(arguments),
                            )

                raw_finish = getattr(choice, "finish_reason", None)
                if raw_finish is not None:
                    finish_reason = raw_finish

            # Usage lives at the top level and usually arrives on the
            # last chunk when ``stream_options.include_usage`` is set.
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                coerced = _coerce_usage(usage)
                if coerced:
                    final_usage = coerced

        # Stream ended — close any still-open tool calls in the order
        # they were opened, emit accumulated usage, then MessageStop.
        for tool_id in order:
            yield from _close_tool(tool_id)

        if final_usage:
            yield UsageDelta(usage=final_usage)

        yield MessageStop(stop_reason=_map_finish_reason(finish_reason))

    def _translate_response(self, response: Any) -> ModelResponse:
        """Build a :class:`ModelResponse` from the non-streaming SDK return.

        Kept as-is from the pre-streaming adapter so the existing
        ``complete()`` test matrix stays green. New stop-reason mapping
        lives on the streaming path (:meth:`_translate_events`); this one
        keeps the legacy passthrough contract (``"stop"``→``"stop"``)
        because its callers assert on the raw string."""
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
        """Identify retryable errors without importing the SDK.

        Retries on 408/409/425/429/500/502/503/504 and class-name tokens
        (rate limit, timeout, APIStatus). Permanent auth / bad-request /
        content-filter errors are *not* retried."""
        status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
        if isinstance(status, int):
            if status in {408, 409, 425, 429, 500, 502, 503, 504}:
                return True
            if status in {400, 401, 403, 404, 422}:
                return False
        name = type(exc).__name__.lower()
        if any(token in name for token in ("contentfilter", "badrequest", "permission", "auth")):
            return False
        return any(token in name for token in ("ratelimit", "timeout", "apistatus"))


# ---------------------------------------------------------------------------
# Capability resolution
# ---------------------------------------------------------------------------


def _capabilities_for_model(model: str) -> ProviderCapabilities:
    """Resolve the :class:`ProviderCapabilities` row for ``model``.

    Reasoning models (``o1`` / ``o3`` / ``o4`` families) declare
    ``thinking=True``; everyone else declares ``thinking=False``. The 1M-
    context ``gpt-4.1`` family gets its own row so orchestrator budget
    math doesn't misreport. Unknown models fall back to the
    4o-compatible defaults — honest about what we know."""
    lower = model.lower()
    if _is_reasoning_model(lower):
        return ProviderCapabilities(
            streaming=True,
            native_tool_use=True,
            parallel_tool_calls=True,
            thinking=True,
            prompt_cache=True,
            vision=False,  # o1/o3-mini are text-only today.
            json_mode=True,
            max_context_tokens=200_000,
            max_output_tokens=100_000,
        )
    if lower.startswith("gpt-4.1") or lower.startswith("gpt-5"):
        return ProviderCapabilities(
            streaming=True,
            native_tool_use=True,
            parallel_tool_calls=True,
            thinking=False,
            prompt_cache=True,
            vision=True,
            json_mode=True,
            max_context_tokens=1_000_000,
            max_output_tokens=32_768,
        )
    # Default: ``gpt-4o`` family and unknown models.
    return ProviderCapabilities(
        streaming=True,
        native_tool_use=True,
        parallel_tool_calls=True,
        thinking=False,
        prompt_cache=True,
        vision=True,
        json_mode=True,
        max_context_tokens=128_000,
        max_output_tokens=16_384,
    )


class _CapabilitiesDescriptor:
    """Return a per-model :class:`ProviderCapabilities` on instance access,
    and the ``gpt-4o`` defaults when accessed on the class itself.

    We want per-instance branching (so ``OpenAIClient(model="o3")``
    declares ``thinking=True``) AND class-level introspection (so
    ``OpenAIClient.capabilities`` works from the orchestrator without
    constructing a client). A descriptor threads that needle — a plain
    ``@property`` would return the property object on class access.
    """

    _default: ProviderCapabilities = _capabilities_for_model("gpt-4o")

    def __get__(
        self,
        instance: Any,
        owner: type | None = None,
    ) -> ProviderCapabilities:
        if instance is None:
            return self._default
        return _capabilities_for_model(getattr(instance, "model", "gpt-4o"))


OpenAIClient.capabilities = _CapabilitiesDescriptor()  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _openai_tool_call(block: AssistantToolUseBlock) -> dict[str, Any]:
    return {
        "id": block.id,
        "type": "function",
        "function": {
            "name": block.name,
            "arguments": json.dumps(block.input or {}),
        },
    }


def _stringify_block(block: Any) -> str:
    if isinstance(block, dict):
        if block.get("type") == "text":
            return str(block.get("text", ""))
        return str(block)
    return str(block)


def _parse_arguments(raw: str) -> dict[str, Any]:
    if not raw or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _coerce_usage(usage: Any) -> dict[str, int]:
    """Shape OpenAI's streaming ``usage`` block into our canonical dict.

    Maps provider names onto the orchestrator's vocabulary:

    * ``prompt_tokens`` → ``input_tokens``.
    * ``completion_tokens`` → ``output_tokens``.
    * ``completion_tokens_details.reasoning_tokens`` → ``reasoning_tokens``.
    * ``prompt_tokens_details.cached_tokens`` → ``cache_read_tokens``.
    """
    if usage is None:
        return {}
    out: dict[str, int] = {}
    for src, dst in (("prompt_tokens", "input_tokens"),
                     ("completion_tokens", "output_tokens")):
        value = _get_any(usage, src)
        if value is None:
            continue
        try:
            out[dst] = int(value)
        except (TypeError, ValueError):
            continue

    completion_details = _get_any(usage, "completion_tokens_details")
    if completion_details is not None:
        reasoning = _get_any(completion_details, "reasoning_tokens")
        if reasoning is not None:
            try:
                out["reasoning_tokens"] = int(reasoning)
            except (TypeError, ValueError):
                pass

    prompt_details = _get_any(usage, "prompt_tokens_details")
    if prompt_details is not None:
        cached = _get_any(prompt_details, "cached_tokens")
        if cached is not None:
            try:
                out["cache_read_tokens"] = int(cached)
            except (TypeError, ValueError):
                pass

    return out


def _get_any(obj: Any, key: str) -> Any:
    """Attribute-or-key access — fake chunks use ``SimpleNamespace``
    while the real SDK exposes pydantic models; both shapes land here."""
    if obj is None:
        return None
    value = getattr(obj, key, None)
    if value is not None:
        return value
    if isinstance(obj, dict):
        return obj.get(key)
    return None


__all__ = ["OpenAIClient", "SdkFactory"]
