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
    """Skeleton for the Gemini streaming fake.

    P0.5c populates ``scripted_chunks`` with
    ``GenerateContentResponse``-shaped records and wires
    ``models.generate_content_stream`` to yield them.
    """

    scripted_chunks: list[Any] = field(default_factory=list)
    captured_kwargs: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Cross-provider scripted-turn helper (P0.5c)
# ---------------------------------------------------------------------------


def scripted_turn_events(
    *,
    provider: str,
    tool_calls: list[tuple[str, dict[str, Any]]],
) -> list[Any]:
    """Return the canonical "three tools, one fails, end_turn" event
    sequence shaped for the given provider's SDK surface.

    Skeleton — concrete shapes land in P0.5c (Gemini) and P0.5d
    (OpenAI). The Anthropic path uses the existing test helpers in
    ``tests/test_llm_providers.py``. Raising here rather than silently
    returning ``[]`` makes it obvious to a downstream task that the
    helper still needs a body.
    """
    raise NotImplementedError(
        f"scripted_turn_events({provider!r}) not implemented yet — "
        "P0.5c fills in Gemini, P0.5d fills in OpenAI."
    )


__all__ = [
    "FakeAnthropicSDK",
    "FakeGeminiSDK",
    "FakeOpenAISDK",
    "scripted_turn_events",
]
