"""Fake provider SDKs for adapter tests — shared fixture.

Skeleton landed in P0.5a; P0.5c fills in ``FakeGeminiSDK`` behaviour and
the cross-provider ``scripted_turn_events`` helper, and P0.5d wires
``FakeOpenAISDK`` into the streaming adapter tests. The shapes here are
duck-typed to match just enough of each SDK surface that the adapter's
translator code paths run without the real library installed.

Every fake:

* Records the kwargs passed into the SDK entry point on
  ``captured_kwargs`` so the tests can assert (e.g.) that
  ``stream_options={"include_usage": True}`` was forwarded.
* Accepts scripted events / chunks / responses so one turn's worth of
  translation can run end-to-end without network.
* Exposes an ``inject(adapter_cls)`` style hook via the adapter's
  ``sdk_factory=`` constructor kwarg — tests do
  ``adapter_cls(..., sdk_factory=lambda _key: fake)``.

The helpers intentionally don't import the real SDKs; they return
``SimpleNamespace`` objects shaped like the SDK's response records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------


@dataclass
class FakeAnthropicSDK:
    """Records ``messages.stream`` kwargs and yields scripted events.

    Usage (in a test)::

        fake = FakeAnthropicSDK()
        fake.scripted_events = [...]
        client = AnthropicClient(
            model="claude-sonnet-4-5",
            api_key="k",
            sdk_factory=lambda _k: fake,
        )
        list(client.stream(system_prompt="", messages=[...], tools=[]))
        assert fake.captured_kwargs[-1]["model"] == "claude-sonnet-4-5"
    """

    scripted_events: list[Any] = field(default_factory=list)
    captured_kwargs: list[dict[str, Any]] = field(default_factory=list)

    @property
    def messages(self) -> "_FakeAnthropicMessages":
        return _FakeAnthropicMessages(self)


@dataclass
class _FakeAnthropicMessages:
    parent: FakeAnthropicSDK

    def stream(self, **kwargs: Any) -> "_FakeAnthropicStreamContext":
        self.parent.captured_kwargs.append(kwargs)
        return _FakeAnthropicStreamContext(events=list(self.parent.scripted_events))


@dataclass
class _FakeAnthropicStreamContext:
    events: list[Any]

    def __enter__(self) -> list[Any]:
        return self.events

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None


# ---------------------------------------------------------------------------
# OpenAI (skeleton — filled in by P0.5d)
# ---------------------------------------------------------------------------


@dataclass
class FakeOpenAISDK:
    """Duck-typed fake of ``openai.OpenAI``.

    Exposes a ``.chat.completions.create(**kwargs)`` entry point the
    adapter calls. When the caller passes ``stream=True`` the fake
    returns an iterator over ``scripted_chunks``; otherwise it returns
    ``scripted_response`` (a single ``ChatCompletion``-shaped object).

    ``pending_exceptions`` lets a test script transient failures followed
    by recovery so retry behaviour round-trips end-to-end without
    wallclock sleeps.

    Usage::

        fake = FakeOpenAISDK()
        fake.scripted_chunks = [
            oai_chunk(delta_content="Hello "),
            oai_chunk(finish_reason="stop", usage={"prompt_tokens": 4}),
        ]
        client = OpenAIClient(
            model="gpt-4o",
            api_key="k",
            sdk_factory=lambda _k: fake,
        )
        events = list(client.stream(system_prompt="", messages=[...], tools=[]))
        assert fake.captured_kwargs[-1]["stream"] is True
    """

    scripted_chunks: list[Any] = field(default_factory=list)
    scripted_response: Any = None
    captured_kwargs: list[dict[str, Any]] = field(default_factory=list)
    pending_exceptions: list[BaseException] = field(default_factory=list)

    def fail_with_then_succeed(
        self,
        exception: BaseException,
        *,
        scripted: list[Any] | None = None,
    ) -> None:
        """Queue ``exception`` to raise on the next call, then succeed."""
        self.pending_exceptions.append(exception)
        if scripted is not None:
            self.scripted_chunks = list(scripted)

    @property
    def chat(self) -> "_FakeOpenAIChat":
        return _FakeOpenAIChat(self)


@dataclass
class _FakeOpenAIChat:
    parent: FakeOpenAISDK

    @property
    def completions(self) -> "_FakeOpenAICompletions":
        return _FakeOpenAICompletions(self.parent)


@dataclass
class _FakeOpenAICompletions:
    parent: FakeOpenAISDK

    def create(self, **kwargs: Any) -> Any:
        self.parent.captured_kwargs.append(kwargs)
        if self.parent.pending_exceptions:
            raise self.parent.pending_exceptions.pop(0)
        if kwargs.get("stream"):
            return iter(list(self.parent.scripted_chunks))
        return self.parent.scripted_response


def oai_chunk(
    *,
    delta_content: str | None = None,
    delta_reasoning: str | None = None,
    tool_call: tuple[int, str | None, str | None, str | None] | None = None,
    tool_calls: list[tuple[int, str | None, str | None, str | None]] | None = None,
    finish_reason: str | None = None,
    usage: dict[str, Any] | None = None,
) -> Any:
    """Build a ``ChatCompletionChunk``-shaped ``SimpleNamespace``.

    Parameters mirror the shape a test actually needs. ``tool_call`` is
    a ``(index, id, name, arguments)`` tuple — ``id`` and ``name`` are
    only populated on the first fragment for a given call; subsequent
    fragments carry only ``index`` and ``arguments``. Use ``tool_calls``
    for multi-call interleaved chunks.
    """
    tool_call_payloads: list[Any] = []
    combined: list[tuple[int, str | None, str | None, str | None]] = []
    if tool_call is not None:
        combined.append(tool_call)
    if tool_calls:
        combined.extend(tool_calls)
    for index, tc_id, tc_name, tc_args in combined:
        function_ns = SimpleNamespace(
            name=tc_name if tc_name is not None else None,
            arguments=tc_args if tc_args is not None else None,
        )
        tool_call_payloads.append(
            SimpleNamespace(
                index=index,
                id=tc_id,
                type="function",
                function=function_ns,
            )
        )

    delta = SimpleNamespace(
        content=delta_content,
        reasoning_content=delta_reasoning,
        tool_calls=tool_call_payloads or None,
    )
    choice = SimpleNamespace(
        index=0,
        delta=delta,
        finish_reason=finish_reason,
    )

    usage_obj: Any = None
    if usage is not None:
        # Shape the dict into SimpleNamespace so attribute access works
        # the same way the real SDK's pydantic model behaves.
        completion_details = None
        if "completion_tokens_details" in usage:
            completion_details = SimpleNamespace(
                **usage["completion_tokens_details"]
            )
        prompt_details = None
        if "prompt_tokens_details" in usage:
            prompt_details = SimpleNamespace(**usage["prompt_tokens_details"])
        usage_obj = SimpleNamespace(
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            completion_tokens_details=completion_details,
            prompt_tokens_details=prompt_details,
        )

    return SimpleNamespace(choices=[choice], usage=usage_obj)


# ---------------------------------------------------------------------------
# Gemini (skeleton — filled in by P0.5c)
# ---------------------------------------------------------------------------


@dataclass
class FakeGeminiSDK:
    """Duck-typed fake of ``google.genai.Client``.

    Exposes a ``.models.generate_content_stream(**kwargs)`` entry point
    the adapter calls. Scripted chunks are yielded on success;
    ``pending_exceptions`` lets a test script transient failures
    followed by recovery so retry behaviour round-trips end-to-end.

    Usage::

        fake = FakeGeminiSDK()
        fake.scripted_chunks = [
            gemini_chunk(text="Hello"),
            gemini_chunk(finish_reason="STOP"),
        ]
        client = GeminiClient(
            model="gemini-2.5-pro",
            api_key="k",
            sdk_factory=lambda _k: fake,
        )
        list(client.stream(system_prompt="", messages=[...], tools=[]))
        assert fake.captured_kwargs[-1]["model"] == "gemini-2.5-pro"
    """

    scripted_chunks: list[Any] = field(default_factory=list)
    captured_kwargs: list[dict[str, Any]] = field(default_factory=list)
    pending_exceptions: list[BaseException] = field(default_factory=list)
    """Exceptions to raise on the first ``len(...)`` calls into
    ``generate_content_stream`` — drained one per attempt. When empty
    the fake returns ``scripted_chunks`` normally."""

    def fail_with_then_succeed(
        self,
        exception: BaseException,
        *,
        scripted: list[Any] | None = None,
    ) -> None:
        """Queue ``exception`` to raise on the next call, then succeed
        with ``scripted`` (or the existing ``scripted_chunks``)."""
        self.pending_exceptions.append(exception)
        if scripted is not None:
            self.scripted_chunks = list(scripted)

    @property
    def models(self) -> "_FakeGeminiModels":
        return _FakeGeminiModels(self)


@dataclass
class _FakeGeminiModels:
    parent: FakeGeminiSDK

    def generate_content_stream(self, **kwargs: Any) -> Any:
        self.parent.captured_kwargs.append(kwargs)
        if self.parent.pending_exceptions:
            raise self.parent.pending_exceptions.pop(0)
        return iter(list(self.parent.scripted_chunks))


def gemini_chunk(
    *,
    text: str | None = None,
    thought: bool = False,
    function_call: dict[str, Any] | None = None,
    fc_id: str | None = None,
    finish_reason: str | None = None,
    usage: dict[str, int] | None = None,
) -> Any:
    """Build a ``GenerateContentResponse``-shaped ``SimpleNamespace``.

    Populates only the fields the adapter's translator reads so a test
    can specify exactly the chunk it needs without re-declaring the
    entire SDK record layout. One chunk typically carries one semantic
    event (text delta, thought, function call, finish, usage).
    """
    parts: list[Any] = []
    if text is not None:
        parts.append(SimpleNamespace(text=text, thought=thought, function_call=None))
    if function_call is not None:
        fc = SimpleNamespace(
            name=function_call.get("name", ""),
            args=dict(function_call.get("args", {})),
            id=fc_id,
        )
        parts.append(
            SimpleNamespace(
                text=None,
                thought=False,
                function_call=fc,
                function_call_id=fc_id,
            )
        )

    candidate = SimpleNamespace(
        content=SimpleNamespace(parts=parts),
        finish_reason=finish_reason,
    )

    usage_obj: Any = None
    if usage is not None:
        usage_obj = SimpleNamespace(
            prompt_token_count=usage.get("prompt_token_count"),
            candidates_token_count=usage.get("candidates_token_count"),
            thoughts_token_count=usage.get("thoughts_token_count"),
            cached_content_token_count=usage.get("cached_content_token_count"),
        )

    return SimpleNamespace(candidates=[candidate], usage_metadata=usage_obj)


# ---------------------------------------------------------------------------
# Cross-provider scripted-turn helper (P0.5c)
# ---------------------------------------------------------------------------


def scripted_turn_events(
    *,
    provider: str,
    tool_calls: list[tuple[str, dict[str, Any]]],
) -> list[Any]:
    """Return the canonical "tool-use then end_turn" event sequence
    shaped for the given provider's SDK surface.

    P0.5c fills in Gemini; P0.5d fills in OpenAI. Anthropic shape still
    uses the helpers in ``tests/test_llm_providers.py``.
    """
    if provider == "gemini":
        chunks: list[Any] = []
        for name, args in tool_calls:
            chunks.append(
                gemini_chunk(function_call={"name": name, "args": args})
            )
        chunks.append(gemini_chunk(finish_reason="STOP"))
        return chunks
    if provider == "openai":
        # OpenAI streams each tool call across multiple chunks: the first
        # fragment declares ``id`` + ``name`` + an empty ``arguments``
        # prefix, subsequent fragments concatenate the JSON blob. We
        # collapse every call into two chunks here (start + full args)
        # for the common-case "one tool, one turn" shape; tests that
        # need interleaved parallel calls build their own chunk list.
        import json as _json

        chunks: list[Any] = []
        for i, (name, args) in enumerate(tool_calls):
            call_id = f"call_{i}"
            chunks.append(oai_chunk(tool_call=(i, call_id, name, "")))
            chunks.append(
                oai_chunk(tool_call=(i, None, None, _json.dumps(args)))
            )
        chunks.append(oai_chunk(finish_reason="tool_calls" if tool_calls else "stop"))
        return chunks
    raise NotImplementedError(
        f"scripted_turn_events({provider!r}) not implemented yet — "
        "Anthropic uses test_llm_providers helpers."
    )


__all__ = [
    "FakeAnthropicSDK",
    "FakeGeminiSDK",
    "FakeOpenAISDK",
    "gemini_chunk",
    "oai_chunk",
    "scripted_turn_events",
]
