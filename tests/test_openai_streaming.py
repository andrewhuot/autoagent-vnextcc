"""Streaming tests for :class:`OpenAIClient` (P0.5d).

Exercise the real-time chunk-translation path through the
:class:`FakeOpenAISDK` fixture. The fake's
``chat.completions.create(stream=True)`` returns an iterator over
scripted ``ChatCompletionChunk``-shaped ``SimpleNamespace`` objects so
the adapter's :meth:`_translate_events` runs without network.

Assertions cover:

* Plain text deltas → :class:`TextDelta` events + ``end_turn`` stop reason.
* Tool-call fragments accumulating across chunks → one
  :class:`ToolUseStart`, N :class:`ToolUseDelta`, one :class:`ToolUseEnd`
  with the full JSON dict parsed once.
* Parallel tool calls interleaved by ``index`` — each fragment finds its
  accumulator via the ``id`` (or the ``index→id`` fallback for
  continuation fragments).
* ``reasoning_content`` deltas on ``o3``/``o1``/``o4`` models → emit
  :class:`ThinkingDelta`.
* Usage block on the final chunk → :class:`UsageDelta` with
  provider-neutral field names.
* ``finish_reason`` mapping: ``stop``/``length``/``tool_calls``/
  ``content_filter``.
* Retry on 429 — the adapter retries the initial SDK call through
  :class:`RetryPolicy`; events emit on the successful attempt.
* Permanent 400 — no retry.
* Partial JSON is never parsed — adversarial split that would crash
  ``json.loads`` on any intermediate fragment.
"""

from __future__ import annotations

from typing import Any

import pytest

from cli.llm.providers.openai_client import OpenAIClient
from cli.llm.retries import RetryPolicy
from cli.llm.streaming import (
    MessageStop,
    TextDelta,
    ThinkingDelta,
    ToolUseDelta,
    ToolUseEnd,
    ToolUseStart,
    UsageDelta,
)
from cli.llm.types import TurnMessage
from tests.fixtures.fake_provider_sdks import FakeOpenAISDK, oai_chunk


def _make_client(
    sdk: FakeOpenAISDK,
    *,
    model: str = "gpt-4o",
    retry_policy: RetryPolicy | None = None,
) -> OpenAIClient:
    """Construct a client backed by ``sdk``.

    Disables retry sleeps by default so tests stay fast; individual
    tests override ``retry_policy`` when they want to assert on back-off
    behaviour."""
    return OpenAIClient(
        model=model,
        api_key="sk-test",
        sdk_factory=lambda _k: sdk,
        retry_policy=retry_policy
        or RetryPolicy(max_attempts=1, base_delay_seconds=0.0),
    )


# ---------------------------------------------------------------------------
# Streaming text
# ---------------------------------------------------------------------------


def test_stream_text_deltas_emit_text_delta_events() -> None:
    sdk = FakeOpenAISDK()
    sdk.scripted_chunks = [
        oai_chunk(delta_content="Hello "),
        oai_chunk(delta_content="world"),
        oai_chunk(finish_reason="stop"),
    ]
    client = _make_client(sdk)

    events = list(
        client.stream(
            system_prompt="s",
            messages=[TurnMessage(role="user", content="hi")],
            tools=[],
        )
    )

    text_events = [e for e in events if isinstance(e, TextDelta)]
    assert [e.text for e in text_events] == ["Hello ", "world"]
    assert isinstance(events[-1], MessageStop)
    assert events[-1].stop_reason == "end_turn"


def test_stream_forwards_include_usage_option() -> None:
    sdk = FakeOpenAISDK()
    sdk.scripted_chunks = [oai_chunk(finish_reason="stop")]
    client = _make_client(sdk)

    list(
        client.stream(
            system_prompt="",
            messages=[TurnMessage(role="user", content="x")],
            tools=[],
        )
    )

    kwargs = sdk.captured_kwargs[-1]
    assert kwargs["stream"] is True
    assert kwargs["stream_options"] == {"include_usage": True}
    assert kwargs["model"] == "gpt-4o"


# ---------------------------------------------------------------------------
# Tool use — single call, arguments split across chunks
# ---------------------------------------------------------------------------


def test_stream_accumulates_tool_arguments_across_three_chunks() -> None:
    sdk = FakeOpenAISDK()
    sdk.scripted_chunks = [
        oai_chunk(tool_call=(0, "call_a", "Bash", "")),
        oai_chunk(tool_call=(0, None, None, '{"cmd":')),
        oai_chunk(tool_call=(0, None, None, ' "ls"}')),
        oai_chunk(finish_reason="tool_calls"),
    ]
    client = _make_client(sdk)

    events = list(
        client.stream(
            system_prompt="",
            messages=[TurnMessage(role="user", content="x")],
            tools=[
                {
                    "name": "Bash",
                    "description": "",
                    "input_schema": {"type": "object"},
                }
            ],
        )
    )

    starts = [e for e in events if isinstance(e, ToolUseStart)]
    deltas = [e for e in events if isinstance(e, ToolUseDelta)]
    ends = [e for e in events if isinstance(e, ToolUseEnd)]

    assert len(starts) == 1
    assert starts[0].id == "call_a"
    assert starts[0].name == "Bash"
    # Two meaningful argument deltas arrived (the empty "" fragment on
    # the first chunk is skipped to avoid a no-op event).
    assert len(deltas) == 2
    assert [d.input_json for d in deltas] == ['{"cmd":', ' "ls"}']
    assert len(ends) == 1
    assert ends[0].id == "call_a"
    assert ends[0].name == "Bash"
    assert ends[0].input == {"cmd": "ls"}
    assert events[-1].stop_reason == "tool_use"


# ---------------------------------------------------------------------------
# Tool use — parallel calls keyed by id, not index
# ---------------------------------------------------------------------------


def test_stream_handles_parallel_tool_calls_by_id() -> None:
    """Two parallel calls whose argument deltas interleave across chunks.

    The adapter keys accumulators by ``id`` (with ``index→id`` fallback
    for continuation fragments). A lazy implementation that keyed by
    ``index`` alone would smear the two calls together."""
    sdk = FakeOpenAISDK()
    sdk.scripted_chunks = [
        oai_chunk(tool_call=(0, "call_a", "Bash", '{"cmd":')),
        oai_chunk(tool_call=(1, "call_b", "FileRead", '{"path":')),
        oai_chunk(tool_call=(0, None, None, ' "ls"}')),
        oai_chunk(tool_call=(1, None, None, ' "/tmp"}')),
        oai_chunk(finish_reason="tool_calls"),
    ]
    client = _make_client(sdk)

    events = list(
        client.stream(
            system_prompt="",
            messages=[TurnMessage(role="user", content="x")],
            tools=[
                {"name": "Bash", "description": "", "input_schema": {"type": "object"}},
                {"name": "FileRead", "description": "", "input_schema": {"type": "object"}},
            ],
        )
    )

    starts = [e for e in events if isinstance(e, ToolUseStart)]
    ends = [e for e in events if isinstance(e, ToolUseEnd)]
    ids = {e.id for e in starts}

    assert ids == {"call_a", "call_b"}
    assert {(e.id, e.name) for e in starts} == {
        ("call_a", "Bash"),
        ("call_b", "FileRead"),
    }
    by_id = {e.id: e.input for e in ends}
    assert by_id["call_a"] == {"cmd": "ls"}
    assert by_id["call_b"] == {"path": "/tmp"}


# ---------------------------------------------------------------------------
# Reasoning content on reasoning models
# ---------------------------------------------------------------------------


def test_stream_reasoning_content_emits_thinking_delta() -> None:
    sdk = FakeOpenAISDK()
    sdk.scripted_chunks = [
        oai_chunk(delta_reasoning="Let me think..."),
        oai_chunk(delta_reasoning=" hmm"),
        oai_chunk(delta_content="Answer"),
        oai_chunk(finish_reason="stop"),
    ]
    client = _make_client(sdk, model="o3-mini")

    events = list(
        client.stream(
            system_prompt="",
            messages=[TurnMessage(role="user", content="q")],
            tools=[],
        )
    )

    thinking = [e for e in events if isinstance(e, ThinkingDelta)]
    text = [e for e in events if isinstance(e, TextDelta)]

    assert [e.text for e in thinking] == ["Let me think...", " hmm"]
    assert [e.text for e in text] == ["Answer"]
    assert events[-1].stop_reason == "end_turn"


# ---------------------------------------------------------------------------
# Usage translation
# ---------------------------------------------------------------------------


def test_stream_usage_delta_includes_reasoning_and_cache_tokens() -> None:
    sdk = FakeOpenAISDK()
    sdk.scripted_chunks = [
        oai_chunk(delta_content="x"),
        oai_chunk(
            finish_reason="stop",
            usage={
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "completion_tokens_details": {"reasoning_tokens": 3},
                "prompt_tokens_details": {"cached_tokens": 4},
            },
        ),
    ]
    client = _make_client(sdk, model="o3-mini")

    events = list(
        client.stream(
            system_prompt="",
            messages=[TurnMessage(role="user", content="x")],
            tools=[],
        )
    )

    usage_events = [e for e in events if isinstance(e, UsageDelta)]
    assert len(usage_events) == 1
    assert usage_events[0].usage == {
        "input_tokens": 10,
        "output_tokens": 5,
        "reasoning_tokens": 3,
        "cache_read_tokens": 4,
    }


# ---------------------------------------------------------------------------
# finish_reason mapping
# ---------------------------------------------------------------------------


def test_stream_content_filter_maps_to_safety_stop_reason() -> None:
    sdk = FakeOpenAISDK()
    sdk.scripted_chunks = [
        oai_chunk(delta_content="partial"),
        oai_chunk(finish_reason="content_filter"),
    ]
    client = _make_client(sdk)

    events = list(
        client.stream(
            system_prompt="",
            messages=[TurnMessage(role="user", content="x")],
            tools=[],
        )
    )
    assert events[-1].stop_reason == "safety"


def test_stream_length_truncation_maps_to_max_tokens() -> None:
    sdk = FakeOpenAISDK()
    sdk.scripted_chunks = [
        oai_chunk(delta_content="very long answer"),
        oai_chunk(finish_reason="length"),
    ]
    client = _make_client(sdk)

    events = list(
        client.stream(
            system_prompt="",
            messages=[TurnMessage(role="user", content="x")],
            tools=[],
        )
    )
    assert events[-1].stop_reason == "max_tokens"


def test_stream_unknown_finish_reason_degrades_to_end_turn(caplog: pytest.LogCaptureFixture) -> None:
    sdk = FakeOpenAISDK()
    sdk.scripted_chunks = [
        oai_chunk(delta_content="x"),
        oai_chunk(finish_reason="hypothetical_new_reason"),
    ]
    client = _make_client(sdk)

    with caplog.at_level("WARNING"):
        events = list(
            client.stream(
                system_prompt="",
                messages=[TurnMessage(role="user", content="x")],
                tools=[],
            )
        )
    assert events[-1].stop_reason == "end_turn"
    assert any("unknown finish_reason" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------


def test_stream_retries_on_429_then_succeeds() -> None:
    """429 on the initial connection triggers one retry; events emit on
    the recovered attempt."""
    sdk = FakeOpenAISDK()
    rate_limit = type("RateLimitError", (Exception,), {"status_code": 429})()
    sdk.fail_with_then_succeed(
        rate_limit,
        scripted=[
            oai_chunk(delta_content="hello"),
            oai_chunk(finish_reason="stop"),
        ],
    )
    policy = RetryPolicy(max_attempts=3, base_delay_seconds=0.0, jitter_seconds=0.0)
    client = _make_client(sdk, retry_policy=policy)

    events = list(
        client.stream(
            system_prompt="",
            messages=[TurnMessage(role="user", content="x")],
            tools=[],
        )
    )

    # Two create() calls — the first raised, the second returned the
    # scripted iterator. Events only arrive on the successful attempt.
    assert len(sdk.captured_kwargs) == 2
    assert [e.text for e in events if isinstance(e, TextDelta)] == ["hello"]
    assert events[-1].stop_reason == "end_turn"


def test_stream_does_not_retry_on_400_bad_request() -> None:
    """Permanent errors (bad request, auth, content-filter) are not
    retried — they surface straight through to the caller."""
    sdk = FakeOpenAISDK()
    bad_request = type("BadRequestError", (Exception,), {"status_code": 400})()
    sdk.pending_exceptions.append(bad_request)
    policy = RetryPolicy(max_attempts=5, base_delay_seconds=0.0, jitter_seconds=0.0)
    client = _make_client(sdk, retry_policy=policy)

    with pytest.raises(Exception) as exc_info:
        list(
            client.stream(
                system_prompt="",
                messages=[TurnMessage(role="user", content="x")],
                tools=[],
            )
        )

    assert type(exc_info.value).__name__ == "BadRequestError"
    # Only one create() call — no retry attempts.
    assert len(sdk.captured_kwargs) == 1


# ---------------------------------------------------------------------------
# Partial-JSON adversarial test — must never parse intermediate buffers
# ---------------------------------------------------------------------------


def test_stream_never_parses_partial_json_mid_stream() -> None:
    """Five chunks split the arguments inside a JSON string literal.

    Any intermediate ``json.loads`` would raise :class:`JSONDecodeError`
    because the accumulated buffer is not valid JSON until the final
    fragment lands. The adapter must accumulate all fragments and parse
    exactly once, at :class:`ToolUseEnd`."""
    sdk = FakeOpenAISDK()
    sdk.scripted_chunks = [
        oai_chunk(tool_call=(0, "c1", "FileRead", '{"path": "')),
        oai_chunk(tool_call=(0, None, None, "/tmp/f")),
        oai_chunk(tool_call=(0, None, None, 'oo.py"')),
        oai_chunk(tool_call=(0, None, None, ', "mode":')),
        oai_chunk(tool_call=(0, None, None, ' "r"}')),
        oai_chunk(finish_reason="tool_calls"),
    ]
    client = _make_client(sdk)

    events = list(
        client.stream(
            system_prompt="",
            messages=[TurnMessage(role="user", content="x")],
            tools=[
                {
                    "name": "FileRead",
                    "description": "",
                    "input_schema": {"type": "object"},
                }
            ],
        )
    )

    ends = [e for e in events if isinstance(e, ToolUseEnd)]
    # Only one ToolUseEnd — no intermediate attempts to close the call.
    assert len(ends) == 1
    assert ends[0].input == {"path": "/tmp/foo.py", "mode": "r"}

    # Every fragment emitted a ToolUseDelta — none of them was skipped
    # because of a parse attempt.
    deltas = [e for e in events if isinstance(e, ToolUseDelta)]
    assert len(deltas) == 5


# ---------------------------------------------------------------------------
# complete() back-compat: non-streaming callers still get a ModelResponse.
# ---------------------------------------------------------------------------


def test_complete_still_returns_model_response_via_non_streaming_path() -> None:
    """``complete()`` uses the non-streaming SDK entry point so legacy
    callers (print-mode checks, EchoModel parity tests) keep working
    without going through the streaming translator."""
    from types import SimpleNamespace

    message = SimpleNamespace(content="hi", tool_calls=None)
    choice = SimpleNamespace(message=message, finish_reason="stop")
    usage = SimpleNamespace(prompt_tokens=5, completion_tokens=3, total_tokens=8)
    non_stream_response = SimpleNamespace(choices=[choice], usage=usage)

    sdk = FakeOpenAISDK()
    sdk.scripted_response = non_stream_response
    client = _make_client(sdk)

    response = client.complete(
        system_prompt="",
        messages=[TurnMessage(role="user", content="hey")],
        tools=[],
    )

    assert response.blocks[0].text == "hi"
    assert response.usage["prompt_tokens"] == 5
    # The non-streaming path keeps its pre-P0.5d stop_reason passthrough —
    # callers of ``complete()`` directly asserted on the raw SDK string,
    # and the streaming path owns the normalised mapping.
    assert response.stop_reason == "stop"


# ---------------------------------------------------------------------------
# cache_hint is a no-op
# ---------------------------------------------------------------------------


def test_cache_hint_is_a_no_op() -> None:
    sdk = FakeOpenAISDK()
    sdk.scripted_chunks = [oai_chunk(finish_reason="stop")]
    client = _make_client(sdk)

    # Never raises, never mutates the kwargs forwarded on the next stream.
    client.cache_hint([{"type": "text", "text": "big prefix"}])
    list(
        client.stream(
            system_prompt="sys",
            messages=[TurnMessage(role="user", content="x")],
            tools=[],
        )
    )

    kwargs = sdk.captured_kwargs[-1]
    # System prompt still arrives via the messages list, unchanged.
    assert kwargs["messages"][0]["role"] == "system"
    assert kwargs["messages"][0]["content"] == "sys"
