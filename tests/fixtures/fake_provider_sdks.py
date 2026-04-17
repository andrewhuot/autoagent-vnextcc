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
    """Skeleton for the OpenAI streaming fake.

    P0.5d populates ``scripted_chunks`` (``ChatCompletionChunk``-shaped
    ``SimpleNamespace`` objects) and wires ``chat.completions.create``
    to return them when ``stream=True``. For P0.5a we land only the
    shape so imports don't break when subsequent tasks add test files
    that reference it.
    """

    scripted_chunks: list[Any] = field(default_factory=list)
    scripted_response: Any = None
    captured_kwargs: list[dict[str, Any]] = field(default_factory=list)


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
    raise NotImplementedError(
        f"scripted_turn_events({provider!r}) not implemented yet — "
        "P0.5d fills in OpenAI; Anthropic uses test_llm_providers helpers."
    )


__all__ = [
    "FakeAnthropicSDK",
    "FakeGeminiSDK",
    "FakeOpenAISDK",
    "gemini_chunk",
    "scripted_turn_events",
]
