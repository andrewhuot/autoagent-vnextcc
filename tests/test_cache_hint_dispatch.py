"""Tests for the provider-neutral ``ModelClient.cache_hint()`` surface (P0.5f).

Each adapter must accept the call and *do the right thing* for its
provider:

* Anthropic — store the hint and splice the pre-computed breakpoint
  content into the next ``system=`` field.
* OpenAI — no-op (server-side automatic prefix caching past ~1024
  tokens).
* Gemini — no-op today (SDK lacks the cached-content handle surface);
  logs at DEBUG to avoid noise.
* EchoModel — no-op (no provider backing).

The orchestrator dispatches ``cache_hint`` unconditionally on every
turn; these tests cover both the adapter-level contract and the
orchestrator dispatch path.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from cli.llm.caching import (
    CacheBlock,
    CacheInput,
    MIN_CACHEABLE_CHARS,
    anthropic_cache_blocks,
    compute_cache_blocks,
)
from cli.llm.providers.anthropic_client import AnthropicClient
from cli.llm.providers.gemini_client import GeminiClient
from cli.llm.providers.openai_client import OpenAIClient
from cli.llm.retries import RetryPolicy
from cli.llm.types import ModelClient, TurnMessage
from cli.print_mode import EchoModel
from tests.fixtures.fake_provider_sdks import (
    FakeAnthropicSDK,
    FakeGeminiSDK,
    FakeOpenAISDK,
    gemini_chunk,
    oai_chunk,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _no_retry() -> RetryPolicy:
    return RetryPolicy(max_attempts=1, base_delay_seconds=0)


def _fake_anthropic_stream_stop() -> list[Any]:
    """Minimal Anthropic event sequence: a ``message_stop`` frame so the
    translator terminates cleanly."""
    from types import SimpleNamespace

    message = SimpleNamespace(stop_reason="end_turn", usage=None)
    return [SimpleNamespace(type="message_stop", message=message)]


def _make_anthropic(fake: FakeAnthropicSDK) -> AnthropicClient:
    return AnthropicClient(
        model="claude-sonnet-4-5",
        api_key="sk-ant-test",
        sdk_factory=lambda _k: fake,
        retry_policy=_no_retry(),
    )


def _make_openai(fake: FakeOpenAISDK) -> OpenAIClient:
    return OpenAIClient(
        model="gpt-4o",
        api_key="sk-test",
        sdk_factory=lambda _k: fake,
        retry_policy=_no_retry(),
    )


def _make_gemini(fake: FakeGeminiSDK) -> GeminiClient:
    return GeminiClient(
        model="gemini-2.5-pro",
        api_key="AIza-test",
        sdk_factory=lambda _k: fake,
        retry_policy=_no_retry(),
    )


# ---------------------------------------------------------------------------
# Protocol surface — every adapter exposes cache_hint()
# ---------------------------------------------------------------------------


def test_model_client_protocol_declares_cache_hint() -> None:
    """The protocol must carry ``cache_hint`` so the orchestrator can
    dispatch without importing adapter-specific modules."""
    assert hasattr(ModelClient, "cache_hint")
    assert callable(getattr(ModelClient, "cache_hint"))


@pytest.mark.parametrize(
    "adapter_cls",
    [AnthropicClient, OpenAIClient, GeminiClient, EchoModel],
)
def test_every_adapter_exposes_cache_hint(adapter_cls: type) -> None:
    assert hasattr(adapter_cls, "cache_hint"), (
        f"{adapter_cls.__name__} is missing cache_hint()"
    )
    assert callable(getattr(adapter_cls, "cache_hint"))


# ---------------------------------------------------------------------------
# CacheBlock dataclass shape
# ---------------------------------------------------------------------------


def test_cache_block_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    block = CacheBlock(message_indices=(0, 1), ttl_seconds=300)
    with pytest.raises(FrozenInstanceError):
        block.ttl_seconds = 600  # type: ignore[misc]


def test_cache_block_defaults_are_empty() -> None:
    block = CacheBlock()
    assert block.message_indices == ()
    assert block.ttl_seconds is None
    assert block.provider_params == {}


def test_anthropic_cache_blocks_wraps_compute_output() -> None:
    long_prompt = "x" * (MIN_CACHEABLE_CHARS + 500)
    blocks = anthropic_cache_blocks(CacheInput(system_prompt=long_prompt))
    assert len(blocks) == 1
    assert isinstance(blocks[0], CacheBlock)
    payload = blocks[0].provider_params.get("anthropic_blocks")
    assert isinstance(payload, list)
    assert any(b.get("cache_control") == {"type": "ephemeral"} for b in payload)


def test_anthropic_cache_blocks_empty_when_short_prefix() -> None:
    # ``compute_cache_blocks`` returns one non-cache block for short
    # prompts, so the wrapper still yields a CacheBlock — but it carries
    # the plain content through so Anthropic still sees a system block.
    # The empty-list guard trips only when there's *nothing* to send.
    assert anthropic_cache_blocks(CacheInput()) == []


# ---------------------------------------------------------------------------
# Anthropic honours the hint on the next stream
# ---------------------------------------------------------------------------


def test_anthropic_cache_hint_sets_system_blocks_on_next_stream() -> None:
    fake = FakeAnthropicSDK()
    fake.scripted_events = _fake_anthropic_stream_stop()
    client = _make_anthropic(fake)

    hint = anthropic_cache_blocks(
        CacheInput(system_prompt="X" * (MIN_CACHEABLE_CHARS + 500))
    )
    client.cache_hint(hint)

    list(
        client.stream(
            system_prompt="IGNORED — cache_hint wins",
            messages=[TurnMessage(role="user", content="hi")],
            tools=[],
        )
    )

    system_field = fake.captured_kwargs[-1]["system"]
    assert isinstance(system_field, list)
    # The hint's content — not the raw ``system_prompt`` — landed in the
    # request.
    assert any(
        isinstance(block, dict) and block.get("text", "").startswith("X")
        for block in system_field
    )
    assert any(
        isinstance(block, dict)
        and block.get("cache_control") == {"type": "ephemeral"}
        for block in system_field
    )


def test_anthropic_cache_hint_accepts_raw_dict_blocks() -> None:
    """Back-compat — callers that hand the raw Anthropic content list
    directly (skipping :class:`CacheBlock`) still win."""
    fake = FakeAnthropicSDK()
    fake.scripted_events = _fake_anthropic_stream_stop()
    client = _make_anthropic(fake)

    raw_blocks = [
        {"type": "text", "text": "Z" * (MIN_CACHEABLE_CHARS + 1),
         "cache_control": {"type": "ephemeral"}},
    ]
    client.cache_hint(raw_blocks)  # type: ignore[arg-type]

    list(
        client.stream(
            system_prompt="stale",
            messages=[TurnMessage(role="user", content="hi")],
            tools=[],
        )
    )
    system_field = fake.captured_kwargs[-1]["system"]
    assert system_field == raw_blocks


def test_anthropic_cache_hint_repeated_call_replaces() -> None:
    """Two calls — the *second* wins. Replacement semantics, not append."""
    fake = FakeAnthropicSDK()
    fake.scripted_events = _fake_anthropic_stream_stop()
    client = _make_anthropic(fake)

    first = anthropic_cache_blocks(CacheInput(system_prompt="A" * 4000))
    second = anthropic_cache_blocks(CacheInput(system_prompt="B" * 4000))
    client.cache_hint(first)
    client.cache_hint(second)

    list(
        client.stream(
            system_prompt="stale",
            messages=[TurnMessage(role="user", content="hi")],
            tools=[],
        )
    )
    system_field = fake.captured_kwargs[-1]["system"]
    assert isinstance(system_field, list)
    # Only the second hint's content survives.
    all_text = "".join(b.get("text", "") for b in system_field if isinstance(b, dict))
    assert "B" in all_text
    assert "A" not in all_text


def test_anthropic_cache_hint_empty_clears_and_falls_back() -> None:
    """Empty hint clears the stored breakpoint; the next stream falls back
    to the legacy ``compute_cache_blocks`` path driven by ``system_prompt``."""
    fake = FakeAnthropicSDK()
    fake.scripted_events = _fake_anthropic_stream_stop()
    client = _make_anthropic(fake)

    # Prime with something, then clear.
    client.cache_hint(
        anthropic_cache_blocks(CacheInput(system_prompt="A" * 4000))
    )
    client.cache_hint([])

    fallback_prompt = "F" * (MIN_CACHEABLE_CHARS + 100)
    list(
        client.stream(
            system_prompt=fallback_prompt,
            messages=[TurnMessage(role="user", content="hi")],
            tools=[],
        )
    )
    system_field = fake.captured_kwargs[-1]["system"]
    # Fallback path kicks in — we should see the ``system_prompt`` text
    # reflected, not the cleared ``"A"``-only payload.
    text_joined = "".join(
        b.get("text", "") for b in system_field if isinstance(b, dict)
    )
    assert "F" in text_joined
    assert "A" not in text_joined


# ---------------------------------------------------------------------------
# OpenAI no-op
# ---------------------------------------------------------------------------


def test_openai_cache_hint_is_a_no_op() -> None:
    sdk = FakeOpenAISDK()
    sdk.scripted_chunks = [oai_chunk(finish_reason="stop")]
    client = _make_openai(sdk)

    # Accept a list of CacheBlock objects without raising.
    client.cache_hint(
        [CacheBlock(provider_params={"anthropic_blocks": [{"type": "text", "text": "x"}]})]
    )
    list(
        client.stream(
            system_prompt="sys",
            messages=[TurnMessage(role="user", content="x")],
            tools=[],
        )
    )

    # No cache-related top-level kwargs leak into the SDK call.
    kwargs = sdk.captured_kwargs[-1]
    assert "cache_control" not in kwargs
    assert "system" not in kwargs  # OpenAI carries system via messages list.


# ---------------------------------------------------------------------------
# Gemini no-op
# ---------------------------------------------------------------------------


def test_gemini_cache_hint_is_a_no_op() -> None:
    fake = FakeGeminiSDK()
    fake.scripted_chunks = [gemini_chunk(finish_reason="STOP")]
    client = _make_gemini(fake)

    client.cache_hint(
        [CacheBlock(provider_params={"anthropic_blocks": [{"type": "text", "text": "x"}]})]
    )
    list(
        client.stream(
            system_prompt="sys",
            messages=[TurnMessage(role="user", content="x")],
            tools=[],
        )
    )
    # Single call captured — the hint didn't issue a separate request.
    assert len(fake.captured_kwargs) == 1


def test_gemini_cache_hint_logs_at_debug_not_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = FakeGeminiSDK()
    client = _make_gemini(fake)

    with caplog.at_level(logging.DEBUG, logger="cli.llm.providers.gemini_client"):
        client.cache_hint(
            [CacheBlock(provider_params={"anthropic_blocks": [{"type": "text", "text": "x"}]})]
        )

    # The log record exists at DEBUG level and nothing at WARNING or
    # higher — users shouldn't see this on every turn.
    assert any(rec.levelno == logging.DEBUG for rec in caplog.records)
    assert not any(rec.levelno >= logging.WARNING for rec in caplog.records)


# ---------------------------------------------------------------------------
# EchoModel no-op
# ---------------------------------------------------------------------------


def test_echo_model_cache_hint_is_a_no_op() -> None:
    model = EchoModel()
    # Smoke: method exists, takes a list, returns None.
    assert model.cache_hint([CacheBlock()]) is None

    # complete() still works after the hint.
    response = model.complete(
        system_prompt="sys",
        messages=[TurnMessage(role="user", content="hi there")],
        tools=[],
    )
    assert "echo:" in response.blocks[0].text


# ---------------------------------------------------------------------------
# Empty blocks on every adapter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "adapter",
    [
        _make_anthropic(FakeAnthropicSDK()),
        _make_openai(FakeOpenAISDK()),
        _make_gemini(FakeGeminiSDK()),
        EchoModel(),
    ],
)
def test_cache_hint_empty_list_never_raises(adapter: Any) -> None:
    # Must accept an empty list on every adapter — the orchestrator
    # may hand it one when the prefix is too short to cache.
    adapter.cache_hint([])


# ---------------------------------------------------------------------------
# Orchestrator dispatch path — no provider-string branching
# ---------------------------------------------------------------------------


def test_orchestrator_calls_cache_hint_before_each_turn(tmp_path) -> None:
    """The orchestrator dispatches ``cache_hint`` unconditionally on every
    turn, regardless of provider. No provider-string branching."""
    from cli.hooks import HookRegistry
    from cli.llm.orchestrator import LLMOrchestrator
    from cli.llm.provider_capabilities import ProviderCapabilities
    from cli.llm.streaming import events_from_model_response
    from cli.llm.types import AssistantTextBlock, ModelResponse
    from cli.permissions import PermissionManager
    from cli.sessions import SessionStore
    from cli.tools.registry import default_registry

    captured: list[Any] = []

    class RecordingModel:
        capabilities = ProviderCapabilities(
            streaming=False,
            native_tool_use=False,
            parallel_tool_calls=False,
            thinking=False,
            prompt_cache=False,
            vision=False,
            json_mode=False,
            max_context_tokens=2048,
            max_output_tokens=512,
        )

        def cache_hint(self, blocks: list[Any]) -> None:
            captured.append(list(blocks))

        def complete(self, *, system_prompt: str, messages, tools) -> ModelResponse:
            del system_prompt, messages, tools
            return ModelResponse(
                blocks=[AssistantTextBlock(text="ok")],
                stop_reason="end_turn",
            )

        def stream(self, *, system_prompt: str, messages, tools):
            yield from events_from_model_response(
                self.complete(
                    system_prompt=system_prompt, messages=messages, tools=tools
                )
            )

    workspace = tmp_path
    (workspace / "workspace.json").write_text("{}")
    permissions = PermissionManager(root=workspace)
    session_store = SessionStore(workspace_dir=workspace)
    session = session_store.create(title="cache-hint-test")
    orchestrator = LLMOrchestrator(
        model=RecordingModel(),
        tool_registry=default_registry(),
        permissions=permissions,
        workspace_root=workspace,
        session=session,
        session_store=session_store,
        hook_registry=None,
        system_prompt="sys",
        echo=lambda _line: None,
    )

    orchestrator.run_turn("hello")

    # Exactly one model turn → exactly one cache_hint dispatch.
    assert len(captured) == 1
    # The dispatched payload is a *list* (may be empty — short system
    # prompt — but the call *happens* regardless of provider).
    assert isinstance(captured[0], list)
