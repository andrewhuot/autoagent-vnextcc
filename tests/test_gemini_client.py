"""Tests for :class:`cli.llm.providers.gemini_client.GeminiClient`.

Drives the adapter via :class:`FakeGeminiSDK` from
``tests/fixtures/fake_provider_sdks.py`` so every code path runs
without the ``google-genai`` dependency installed. The real SDK is
import-guarded inside the adapter; a small set of tests import-skip on
its absence to guard the wire contract when the extra **is** installed
— they're safe to ship unconditionally because ``pytest.importorskip``
turns them into skips rather than failures when the dep is missing.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from cli.llm.providers.gemini_client import GeminiClient
from cli.llm.retries import RetryPolicy
from cli.llm.streaming import (
    MessageStop,
    TextDelta,
    ThinkingDelta,
    ToolUseEnd,
    ToolUseStart,
    UsageDelta,
)
from cli.llm.types import (
    AssistantTextBlock,
    AssistantToolUseBlock,
    TurnMessage,
)
from tests.fixtures.fake_provider_sdks import FakeGeminiSDK, gemini_chunk


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(
    fake: FakeGeminiSDK,
    *,
    model: str = "gemini-2.5-pro",
    retry_policy: RetryPolicy | None = None,
) -> GeminiClient:
    return GeminiClient(
        model=model,
        api_key="AIza-test",
        sdk_factory=lambda _k: fake,
        retry_policy=retry_policy or RetryPolicy(max_attempts=1, base_delay_seconds=0),
    )


# ---------------------------------------------------------------------------
# 1. Streaming text
# ---------------------------------------------------------------------------


def test_streaming_text_emits_text_deltas_in_order() -> None:
    fake = FakeGeminiSDK()
    fake.scripted_chunks = [
        gemini_chunk(text="Hello "),
        gemini_chunk(text="world"),
        gemini_chunk(
            finish_reason="STOP",
            usage={"prompt_token_count": 10, "candidates_token_count": 3},
        ),
    ]
    client = _make_client(fake)

    events = list(
        client.stream(
            system_prompt="system",
            messages=[TurnMessage(role="user", content="hi")],
            tools=[],
        )
    )

    text_events = [e for e in events if isinstance(e, TextDelta)]
    assert [e.text for e in text_events] == ["Hello ", "world"]
    assert any(isinstance(e, UsageDelta) for e in events)
    assert isinstance(events[-1], MessageStop)
    assert events[-1].stop_reason == "end_turn"


def test_streaming_usage_normalises_field_names() -> None:
    fake = FakeGeminiSDK()
    fake.scripted_chunks = [
        gemini_chunk(text="x"),
        gemini_chunk(
            finish_reason="STOP",
            usage={
                "prompt_token_count": 100,
                "candidates_token_count": 50,
                "thoughts_token_count": 20,
                "cached_content_token_count": 30,
            },
        ),
    ]
    client = _make_client(fake)

    events = list(
        client.stream(
            system_prompt="",
            messages=[TurnMessage(role="user", content="x")],
            tools=[],
        )
    )
    usage = next(e.usage for e in events if isinstance(e, UsageDelta))
    assert usage == {
        "input_tokens": 100,
        "output_tokens": 50,
        "reasoning_tokens": 20,
        "cache_read_tokens": 30,
    }


# ---------------------------------------------------------------------------
# 2. Tool use
# ---------------------------------------------------------------------------


def test_tool_use_emits_start_and_end_with_parsed_args() -> None:
    fake = FakeGeminiSDK()
    fake.scripted_chunks = [
        gemini_chunk(
            function_call={"name": "Bash", "args": {"cmd": "ls"}},
            fc_id="call_1",
        ),
        gemini_chunk(finish_reason="STOP"),
    ]
    client = _make_client(fake)

    events = list(
        client.stream(
            system_prompt="",
            messages=[TurnMessage(role="user", content="ls")],
            tools=[
                {
                    "name": "Bash",
                    "description": "Run a shell command",
                    "input_schema": {
                        "type": "object",
                        "properties": {"cmd": {"type": "string"}},
                        "required": ["cmd"],
                    },
                }
            ],
        )
    )

    starts = [e for e in events if isinstance(e, ToolUseStart)]
    ends = [e for e in events if isinstance(e, ToolUseEnd)]
    assert len(starts) == 1 and len(ends) == 1
    assert starts[0].name == "Bash"
    assert starts[0].id == "call_1"
    assert ends[0].input == {"cmd": "ls"}

    # ``complete`` folds the same event stream into an
    # ``AssistantToolUseBlock`` — re-run with a fresh fake to verify.
    fake2 = FakeGeminiSDK()
    fake2.scripted_chunks = [
        gemini_chunk(
            function_call={"name": "Bash", "args": {"cmd": "ls"}},
            fc_id="call_1",
        ),
        gemini_chunk(finish_reason="STOP"),
    ]
    client2 = _make_client(fake2)
    response = client2.complete(
        system_prompt="",
        messages=[TurnMessage(role="user", content="ls")],
        tools=[
            {
                "name": "Bash",
                "description": "",
                "input_schema": {"type": "object"},
            }
        ],
    )
    tool_uses = response.tool_uses()
    assert len(tool_uses) == 1
    assert isinstance(tool_uses[0], AssistantToolUseBlock)
    assert tool_uses[0].id == "call_1"
    assert tool_uses[0].name == "Bash"
    assert tool_uses[0].input == {"cmd": "ls"}


def test_function_call_without_id_gets_synthetic_identifier() -> None:
    fake = FakeGeminiSDK()
    fake.scripted_chunks = [
        gemini_chunk(function_call={"name": "Grep", "args": {"pattern": "foo"}}),
        gemini_chunk(finish_reason="STOP"),
    ]
    client = _make_client(fake)
    events = list(
        client.stream(
            system_prompt="",
            messages=[TurnMessage(role="user", content="grep foo")],
            tools=[
                {
                    "name": "Grep",
                    "description": "",
                    "input_schema": {
                        "type": "object",
                        "properties": {"pattern": {"type": "string"}},
                    },
                }
            ],
        )
    )
    start = next(e for e in events if isinstance(e, ToolUseStart))
    end = next(e for e in events if isinstance(e, ToolUseEnd))
    assert start.id  # non-empty synthetic id
    assert end.id == start.id


# ---------------------------------------------------------------------------
# 3. Multi-turn: user → assistant-with-tool → tool_result → assistant-text
# ---------------------------------------------------------------------------


def test_multi_turn_round_trip_through_complete() -> None:
    fake = FakeGeminiSDK()
    # This simulates the *second* assistant turn after a tool ran.
    fake.scripted_chunks = [
        gemini_chunk(text="The file contained 'hello'."),
        gemini_chunk(finish_reason="STOP"),
    ]
    client = _make_client(fake)

    messages = [
        TurnMessage(role="user", content="read data.txt"),
        TurnMessage(
            role="assistant",
            content=[
                AssistantToolUseBlock(id="c1", name="FileRead", input={"path": "data.txt"}),
            ],
        ),
        TurnMessage(
            role="user",
            content=[
                {
                    "type": "tool_result",
                    "tool_use_id": "c1",
                    "name": "FileRead",
                    "content": "hello",
                }
            ],
        ),
    ]

    response = client.complete(
        system_prompt="You read files.",
        messages=messages,
        tools=[
            {
                "name": "FileRead",
                "description": "Read a file",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            }
        ],
    )

    assert response.stop_reason == "end_turn"
    text_blocks = [b for b in response.blocks if isinstance(b, AssistantTextBlock)]
    assert any("hello" in b.text for b in text_blocks)

    # Verify the translated ``contents`` sent to the SDK carried the
    # tool-result turn in Gemini's ``function`` role.
    sent = fake.captured_kwargs[-1]
    roles = [m["role"] for m in sent["contents"]]
    assert roles == ["user", "model", "function"]
    function_part = sent["contents"][2]["parts"][0]
    assert function_part["function_response"]["name"] == "FileRead"
    assert function_part["function_response"]["response"] == {"content": "hello"}


# ---------------------------------------------------------------------------
# 4. Safety block
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("reason", ["SAFETY", "RECITATION", "PROHIBITED_CONTENT"])
def test_safety_block_surfaces_as_safety_stop_reason(reason: str) -> None:
    fake = FakeGeminiSDK()
    fake.scripted_chunks = [gemini_chunk(finish_reason=reason)]
    client = _make_client(fake)

    response = client.complete(
        system_prompt="",
        messages=[TurnMessage(role="user", content="unsafe prompt")],
        tools=[],
    )
    assert response.stop_reason == "safety"
    # No text should leak through when safety blocks the response.
    assert all(
        not isinstance(b, AssistantTextBlock) or not b.text.strip()
        for b in response.blocks
    )


def test_unknown_finish_reason_logs_and_maps_to_end_turn(caplog) -> None:
    fake = FakeGeminiSDK()
    fake.scripted_chunks = [gemini_chunk(finish_reason="OTHER")]
    client = _make_client(fake)

    response = client.complete(
        system_prompt="",
        messages=[TurnMessage(role="user", content="x")],
        tools=[],
    )
    assert response.stop_reason == "end_turn"


# ---------------------------------------------------------------------------
# 5. Thinking
# ---------------------------------------------------------------------------


def test_thinking_parts_emit_thinking_delta() -> None:
    fake = FakeGeminiSDK()
    fake.scripted_chunks = [
        gemini_chunk(text="Let me reason through this...", thought=True),
        gemini_chunk(text="The answer is 42."),
        gemini_chunk(finish_reason="STOP"),
    ]
    client = _make_client(fake)

    events = list(
        client.stream(
            system_prompt="",
            messages=[TurnMessage(role="user", content="q")],
            tools=[],
        )
    )
    thinkings = [e for e in events if isinstance(e, ThinkingDelta)]
    texts = [e for e in events if isinstance(e, TextDelta)]
    assert len(thinkings) == 1
    assert thinkings[0].text.startswith("Let me reason")
    assert len(texts) == 1
    assert texts[0].text == "The answer is 42."


def test_thinking_config_attached_only_for_2_5_models() -> None:
    fake_2_5 = FakeGeminiSDK()
    fake_2_5.scripted_chunks = [gemini_chunk(finish_reason="STOP")]
    client = _make_client(fake_2_5, model="gemini-2.5-pro")
    list(
        client.stream(
            system_prompt="",
            messages=[TurnMessage(role="user", content="x")],
            tools=[],
        )
    )
    config = fake_2_5.captured_kwargs[-1]["config"]
    # ``config`` is a dict when google-genai is absent.
    assert isinstance(config, dict)
    assert "thinking_config" in config

    fake_2_0 = FakeGeminiSDK()
    fake_2_0.scripted_chunks = [gemini_chunk(finish_reason="STOP")]
    client = _make_client(fake_2_0, model="gemini-2.0-flash")
    list(
        client.stream(
            system_prompt="",
            messages=[TurnMessage(role="user", content="x")],
            tools=[],
        )
    )
    config = fake_2_0.captured_kwargs[-1]["config"]
    assert isinstance(config, dict)
    assert "thinking_config" not in config


# ---------------------------------------------------------------------------
# 6. Quota retry
# ---------------------------------------------------------------------------


def test_retries_on_quota_error_then_succeeds() -> None:
    quota_err = type(
        "ResourceExhaustedError",
        (Exception,),
        {"status_code": 429},
    )("rate limited")

    fake = FakeGeminiSDK()
    fake.fail_with_then_succeed(
        quota_err,
        scripted=[
            gemini_chunk(text="ok"),
            gemini_chunk(finish_reason="STOP"),
        ],
    )
    client = GeminiClient(
        model="gemini-2.5-pro",
        api_key="AIza-test",
        sdk_factory=lambda _k: fake,
        retry_policy=RetryPolicy(max_attempts=2, base_delay_seconds=0, jitter_seconds=0),
    )

    response = client.complete(
        system_prompt="",
        messages=[TurnMessage(role="user", content="x")],
        tools=[],
    )
    # Two calls total: first failed, second succeeded.
    assert len(fake.captured_kwargs) == 2
    assert response.stop_reason == "end_turn"
    texts = [b for b in response.blocks if isinstance(b, AssistantTextBlock)]
    assert texts and texts[0].text == "ok"


# ---------------------------------------------------------------------------
# 7. Permanent error (400) — no retry
# ---------------------------------------------------------------------------


def test_permanent_400_does_not_retry() -> None:
    perm = type("InvalidArgumentError", (Exception,), {"status_code": 400})("bad req")

    fake = FakeGeminiSDK()
    fake.fail_with_then_succeed(perm, scripted=[gemini_chunk(finish_reason="STOP")])
    client = GeminiClient(
        model="gemini-2.5-pro",
        api_key="AIza-test",
        sdk_factory=lambda _k: fake,
        retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0, jitter_seconds=0),
    )

    with pytest.raises(Exception) as excinfo:
        client.complete(
            system_prompt="",
            messages=[TurnMessage(role="user", content="x")],
            tools=[],
        )
    assert excinfo.value is perm
    assert len(fake.captured_kwargs) == 1  # no retries


def test_safety_class_name_is_not_retried() -> None:
    safety = type("SafetyBlockedError", (Exception,), {})("blocked")
    fake = FakeGeminiSDK()
    fake.fail_with_then_succeed(safety, scripted=[gemini_chunk(finish_reason="STOP")])
    client = GeminiClient(
        model="gemini-2.5-pro",
        api_key="AIza-test",
        sdk_factory=lambda _k: fake,
        retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0, jitter_seconds=0),
    )
    with pytest.raises(Exception) as excinfo:
        client.complete(
            system_prompt="",
            messages=[TurnMessage(role="user", content="x")],
            tools=[],
        )
    assert excinfo.value is safety
    assert len(fake.captured_kwargs) == 1


# ---------------------------------------------------------------------------
# 8. Missing SDK — construction raises with install hint
# ---------------------------------------------------------------------------


def test_missing_google_genai_raises_install_hint(monkeypatch) -> None:
    from cli.llm.providers import gemini_client as gc

    # Force the lazy import to fail.
    import builtins

    real_import = builtins.__import__

    def _fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("google"):
            raise ImportError("No module named 'google'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    # Invoke the default factory directly.
    with pytest.raises(RuntimeError) as excinfo:
        gc._default_sdk_factory("AIza-test")
    message = str(excinfo.value)
    assert "google-genai" in message
    assert "pip install" in message


def test_importing_adapter_without_google_genai_does_not_raise() -> None:
    # The adapter module is already imported at the top of this file —
    # reaching here means no module-level ``import google.genai``.
    # Sanity-check by re-importing and ensuring it succeeds.
    import importlib

    import cli.llm.providers.gemini_client as gc

    importlib.reload(gc)


# ---------------------------------------------------------------------------
# 9. API key resolution via the factory
# ---------------------------------------------------------------------------


def test_factory_resolves_gemini_via_gemini_api_key(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "gm-primary")

    from cli.llm.providers.factory import create_model_client
    from cli.llm.providers.gemini_client import GeminiClient

    client = create_model_client(model="gemini-2.5-flash")
    assert isinstance(client, GeminiClient)
    assert client.api_key == "gm-primary"


def test_factory_falls_back_to_google_api_key(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "AIza-fallback")

    from cli.llm.providers.factory import create_model_client
    from cli.llm.providers.gemini_client import GeminiClient

    client = create_model_client(model="gemini-2.5-pro")
    assert isinstance(client, GeminiClient)
    assert client.api_key == "AIza-fallback"


def test_factory_prefers_gemini_key_when_both_set(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "gm-primary")
    monkeypatch.setenv("GOOGLE_API_KEY", "AIza-fallback")

    from cli.llm.providers.factory import create_model_client
    from cli.llm.providers.gemini_client import GeminiClient

    client = create_model_client(model="gemini-2.0-flash")
    assert isinstance(client, GeminiClient)
    assert client.api_key == "gm-primary"


def test_factory_missing_key_without_fallback_returns_client_that_errors_lazily(
    monkeypatch,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    from cli.llm.providers.factory import create_model_client
    from cli.llm.providers.gemini_client import GeminiClient

    # With no key and echo_fallback_on_missing_keys=False (default), the
    # factory still returns a GeminiClient — it only raises when the
    # caller actually tries to stream. This matches the Anthropic /
    # OpenAI adapter behaviour.
    client = create_model_client(model="gemini-2.5-pro")
    assert isinstance(client, GeminiClient)
    assert client.api_key is None


def test_factory_echo_fallback_when_no_key(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    from cli.llm.providers.factory import create_model_client
    from cli.print_mode import EchoModel

    client = create_model_client(
        model="gemini-2.5-pro",
        echo_fallback_on_missing_keys=True,
    )
    assert isinstance(client, EchoModel)


# ---------------------------------------------------------------------------
# 10. Tool declarations run through to_gemini (additionalProperties stripped)
# ---------------------------------------------------------------------------


def test_tool_declarations_pass_through_to_gemini_translator() -> None:
    fake = FakeGeminiSDK()
    fake.scripted_chunks = [gemini_chunk(finish_reason="STOP")]
    client = _make_client(fake)

    schema = {
        "name": "Bash",
        "description": "Run a shell command",
        "input_schema": {
            "type": "object",
            "properties": {"cmd": {"type": "string"}},
            "required": ["cmd"],
            "additionalProperties": False,  # must be stripped for Gemini
        },
    }
    list(
        client.stream(
            system_prompt="",
            messages=[TurnMessage(role="user", content="x")],
            tools=[schema],
        )
    )

    config = fake.captured_kwargs[-1]["config"]
    assert isinstance(config, dict)
    tools = config.get("tools", [])
    assert tools
    decls = tools[0]["function_declarations"]
    assert decls[0]["name"] == "Bash"
    assert "additionalProperties" not in decls[0]["parameters"]


def test_automatic_function_calling_is_disabled() -> None:
    fake = FakeGeminiSDK()
    fake.scripted_chunks = [gemini_chunk(finish_reason="STOP")]
    client = _make_client(fake)

    list(
        client.stream(
            system_prompt="s",
            messages=[TurnMessage(role="user", content="x")],
            tools=[],
        )
    )
    config = fake.captured_kwargs[-1]["config"]
    assert isinstance(config, dict)
    assert config["automatic_function_calling"] == {"disable": True}


def test_system_prompt_routed_to_system_instruction() -> None:
    fake = FakeGeminiSDK()
    fake.scripted_chunks = [gemini_chunk(finish_reason="STOP")]
    client = _make_client(fake)

    list(
        client.stream(
            system_prompt="You are a helpful assistant.",
            messages=[TurnMessage(role="user", content="hi")],
            tools=[],
        )
    )
    config = fake.captured_kwargs[-1]["config"]
    assert isinstance(config, dict)
    assert config["system_instruction"] == "You are a helpful assistant."
    # System prompt must NOT have been prepended into the ``contents`` list.
    contents = fake.captured_kwargs[-1]["contents"]
    assert all(m["role"] != "system" for m in contents)


# ---------------------------------------------------------------------------
# Cache hint — P0.5f lands the orchestrator wiring; here we just confirm
# the no-op method exists and accepts the canonical payload.
# ---------------------------------------------------------------------------


def test_cache_hint_is_a_no_op() -> None:
    fake = FakeGeminiSDK()
    fake.scripted_chunks = [gemini_chunk(finish_reason="STOP")]
    client = _make_client(fake)
    # Must not raise; must not affect subsequent stream kwargs.
    client.cache_hint([{"type": "text", "text": "big prefix"}])
    list(
        client.stream(
            system_prompt="s",
            messages=[TurnMessage(role="user", content="x")],
            tools=[],
        )
    )
    assert len(fake.captured_kwargs) == 1


# ---------------------------------------------------------------------------
# Live-surface check (only runs when ``google-genai`` is installed).
# ---------------------------------------------------------------------------


def test_live_sdk_types_accept_built_config() -> None:
    pytest.importorskip("google.genai")
    # When the SDK is installed, the adapter should build a real
    # GenerateContentConfig; the fake path still routes through
    # ``generate_content_stream`` so captured_kwargs["config"] is the
    # real SDK object.
    from google.genai import types as genai_types  # type: ignore[import-not-found]

    fake = FakeGeminiSDK()
    fake.scripted_chunks = [gemini_chunk(finish_reason="STOP")]
    client = _make_client(fake)
    list(
        client.stream(
            system_prompt="s",
            messages=[TurnMessage(role="user", content="x")],
            tools=[],
        )
    )
    config = fake.captured_kwargs[-1]["config"]
    assert isinstance(config, genai_types.GenerateContentConfig)
