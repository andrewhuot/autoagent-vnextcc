"""Tests for :class:`ProviderCapabilities` and its declaration on adapters.

The descriptor pins *what each adapter does today* — not what we want it
to do in the future. A silent flip on, e.g., OpenAI streaming before the
P0.5d implementation lands would be a honesty drift; these tests fail
until the matrix below is updated with intent."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from cli.llm.provider_capabilities import ProviderCapabilities
from cli.llm.providers.anthropic_client import AnthropicClient
from cli.llm.providers.openai_client import OpenAIClient
from cli.llm.types import ModelClient
from cli.print_mode import EchoModel


# ---------------------------------------------------------------------------
# Dataclass shape
# ---------------------------------------------------------------------------


def test_provider_capabilities_is_frozen():
    caps = ProviderCapabilities(
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
    with pytest.raises(FrozenInstanceError):
        caps.streaming = False  # type: ignore[misc]


def test_provider_capabilities_requires_all_fields():
    # Ensures no silent defaults — every adapter must declare every bit.
    with pytest.raises(TypeError):
        ProviderCapabilities(streaming=True)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Per-adapter declared matrix
# ---------------------------------------------------------------------------


ANTHROPIC_EXPECTED = {
    "streaming": True,
    "native_tool_use": True,
    "parallel_tool_calls": True,
    "thinking": True,
    "prompt_cache": True,
    "vision": True,
    "json_mode": True,
    "max_context_tokens": 200_000,
    "max_output_tokens": 8192,
}

# Declared for today's non-streaming OpenAI adapter. P0.5d flips
# ``streaming`` to True. If that flip lands silently, this test tells
# the reviewer.
OPENAI_EXPECTED = {
    "streaming": False,
    "native_tool_use": True,
    "parallel_tool_calls": True,
    "thinking": False,
    "prompt_cache": True,
    "vision": True,
    "json_mode": True,
    "max_context_tokens": 128_000,
    "max_output_tokens": 16_384,
}

ECHO_EXPECTED = {
    "streaming": False,
    "native_tool_use": False,
    "parallel_tool_calls": False,
    "thinking": False,
    "prompt_cache": False,
    "vision": False,
    "json_mode": False,
    "max_context_tokens": 2048,
    "max_output_tokens": 512,
}

# Gemini adapter landed in P0.5c. ``parallel_tool_calls=True`` reflects
# the 2.5 family's multi-tool-per-turn behaviour; ``prompt_cache=False``
# because the SDK lacks the content-handle API today (follow-up task).
GEMINI_EXPECTED = {
    "streaming": True,
    "native_tool_use": True,
    "parallel_tool_calls": True,
    "thinking": True,
    "prompt_cache": False,
    "vision": True,
    "json_mode": True,
    "max_context_tokens": 1_048_576,
    "max_output_tokens": 8192,
}


def _caps_to_dict(caps: ProviderCapabilities) -> dict:
    return {
        "streaming": caps.streaming,
        "native_tool_use": caps.native_tool_use,
        "parallel_tool_calls": caps.parallel_tool_calls,
        "thinking": caps.thinking,
        "prompt_cache": caps.prompt_cache,
        "vision": caps.vision,
        "json_mode": caps.json_mode,
        "max_context_tokens": caps.max_context_tokens,
        "max_output_tokens": caps.max_output_tokens,
    }


def test_anthropic_adapter_declares_expected_capabilities():
    client = AnthropicClient(model="claude-sonnet-4-5", api_key="sk-ant-test")
    caps = client.capabilities
    assert isinstance(caps, ProviderCapabilities)
    assert _caps_to_dict(caps) == ANTHROPIC_EXPECTED


def test_openai_adapter_declares_current_non_streaming_reality():
    client = OpenAIClient(model="gpt-4o", api_key="sk-test")
    caps = client.capabilities
    assert isinstance(caps, ProviderCapabilities)
    assert _caps_to_dict(caps) == OPENAI_EXPECTED


def test_gemini_adapter_declares_expected_capabilities():
    from cli.llm.providers.gemini_client import GeminiClient

    client = GeminiClient(
        model="gemini-2.5-pro",
        api_key="sk-test",
        sdk_factory=lambda _k: object(),
    )
    caps = client.capabilities
    assert isinstance(caps, ProviderCapabilities)
    assert _caps_to_dict(caps) == GEMINI_EXPECTED


def test_echo_model_declares_zero_capabilities():
    caps = EchoModel().capabilities
    assert isinstance(caps, ProviderCapabilities)
    assert _caps_to_dict(caps) == ECHO_EXPECTED
    # Sanity: never zero context so downstream budget math never divides by
    # zero even on the fake.
    assert caps.max_context_tokens > 0
    assert caps.max_output_tokens > 0


# ---------------------------------------------------------------------------
# Class-attribute access (orchestrator reads from class without an instance)
# ---------------------------------------------------------------------------


def test_capabilities_available_as_class_attribute():
    from cli.llm.providers.gemini_client import GeminiClient

    assert isinstance(AnthropicClient.capabilities, ProviderCapabilities)
    assert isinstance(OpenAIClient.capabilities, ProviderCapabilities)
    assert isinstance(EchoModel.capabilities, ProviderCapabilities)
    assert isinstance(GeminiClient.capabilities, ProviderCapabilities)


# ---------------------------------------------------------------------------
# Protocol surface
# ---------------------------------------------------------------------------


def test_model_client_protocol_declares_stream_and_capabilities():
    # Structural check — every adapter class exposes stream() and
    # capabilities.
    for adapter in (AnthropicClient, OpenAIClient, EchoModel):
        assert hasattr(adapter, "capabilities"), f"{adapter.__name__} missing capabilities"
        assert callable(getattr(adapter, "stream", None)), (
            f"{adapter.__name__} missing stream()"
        )


def test_model_client_protocol_still_declares_complete():
    # Back-compat: existing callers depend on complete() staying on the
    # protocol.
    assert hasattr(ModelClient, "complete")


def test_model_client_protocol_annotates_stream():
    # The Protocol body carries a stream() declaration — introspectable
    # via __annotations__ on the function or just attribute presence.
    assert hasattr(ModelClient, "stream")
    assert callable(getattr(ModelClient, "stream"))
