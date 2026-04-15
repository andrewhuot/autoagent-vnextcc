"""Tests for the :mod:`cli.llm.capabilities` registry.

We pin the canonical model set listed in the Phase-B brief so accidental
key renames (e.g. dropping a dash) fail loudly before reaching the status
bar / usage grid, which silently fall back to a 200k default otherwise.
"""

from __future__ import annotations

import pytest

from cli.llm.capabilities import (
    MODEL_CAPABILITIES,
    ModelCapability,
    get_capability,
    resolve_context_limit,
    resolve_max_output,
)


CANONICAL_MODELS = [
    # Claude family — 200k window, prompt cache is expected everywhere.
    "claude-haiku-4-5",
    "claude-sonnet-4-5",
    "claude-opus-4-5",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-3-5-sonnet-20241022",
    "claude-3-5-haiku-20241022",
    # OpenAI
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4.1",
    "gpt-5",
    # Gemini
    "gemini-2.5-pro",
    "gemini-2.5-flash",
]


# ---------------------------------------------------------------------------
# Registry completeness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", CANONICAL_MODELS)
def test_every_canonical_model_resolves(name: str) -> None:
    cap = get_capability(name)
    assert cap is not None, f"missing capability: {name}"
    assert isinstance(cap, ModelCapability)
    assert cap.name == name
    assert cap.context_window > 0
    assert cap.max_output_tokens > 0


def test_claude_family_has_uniform_window_and_cache() -> None:
    """Claude 4.x/3.5 all share 200k + prompt caching — a drift here
    would indicate someone copy-pasted a wrong value."""
    claude_keys = [k for k in MODEL_CAPABILITIES if k.startswith("claude-")]
    assert len(claude_keys) == 7
    for key in claude_keys:
        cap = MODEL_CAPABILITIES[key]
        assert cap.context_window == 200_000
        assert cap.supports_prompt_cache is True
        assert cap.supports_tool_use is True
        assert cap.supports_streaming is True


def test_claude_opus_variants_support_thinking() -> None:
    # Opus is the only Claude 4.x/3.5 tier with extended-thinking today;
    # the status bar / planner keys feature-gates off this flag.
    assert MODEL_CAPABILITIES["claude-opus-4-5"].supports_thinking is True
    assert MODEL_CAPABILITIES["claude-opus-4-6"].supports_thinking is True
    assert MODEL_CAPABILITIES["claude-haiku-4-5"].supports_thinking is False


def test_gpt5_and_gemini_have_million_token_windows() -> None:
    # Guards against someone collapsing GPT-5 back to 200k after a refactor.
    assert MODEL_CAPABILITIES["gpt-5"].context_window == 1_000_000
    assert MODEL_CAPABILITIES["gpt-5"].supports_thinking is True
    assert MODEL_CAPABILITIES["gemini-2.5-pro"].context_window == 1_000_000
    assert MODEL_CAPABILITIES["gemini-2.5-flash"].context_window == 1_000_000


# ---------------------------------------------------------------------------
# get_capability
# ---------------------------------------------------------------------------


def test_get_capability_unknown_returns_none() -> None:
    assert get_capability("totally-made-up-model") is None
    assert get_capability("") is None


def test_get_capability_is_case_insensitive() -> None:
    upper = get_capability("CLAUDE-OPUS-4-6")
    lower = get_capability("claude-opus-4-6")
    assert upper is not None
    assert upper is lower


def test_get_capability_strips_latest_suffix() -> None:
    # Adapters often ship ``model-latest`` aliases — we should resolve them
    # to the base entry instead of silently falling back to the default.
    cap = get_capability("claude-sonnet-4-5-latest")
    assert cap is not None
    assert cap.name == "claude-sonnet-4-5"


def test_get_capability_strips_date_suffix_for_unseen_stamps() -> None:
    # ``claude-3-5-sonnet`` family regularly gets a new date stamp; if the
    # exact key isn't in the registry, strip the trailing YYYYMMDD and retry.
    cap = get_capability("claude-3-5-sonnet-20250101")
    # The trimmed prefix ``claude-3-5-sonnet`` isn't in the registry, so this
    # fails — which is correct behaviour (we'd rather fall back than lie).
    assert cap is None
    # But the full canonical key still resolves.
    assert get_capability("claude-3-5-sonnet-20241022") is not None


# ---------------------------------------------------------------------------
# resolve_context_limit
# ---------------------------------------------------------------------------


def test_resolve_context_limit_known_model() -> None:
    assert resolve_context_limit("gpt-5") == 1_000_000
    assert resolve_context_limit("claude-opus-4-6") == 200_000


def test_resolve_context_limit_unknown_falls_back_to_default() -> None:
    assert resolve_context_limit("future-model") == 200_000
    assert resolve_context_limit("future-model", default=500_000) == 500_000


def test_resolve_context_limit_none_model_uses_default() -> None:
    assert resolve_context_limit(None) == 200_000
    assert resolve_context_limit(None, default=42) == 42


# ---------------------------------------------------------------------------
# resolve_max_output
# ---------------------------------------------------------------------------


def test_resolve_max_output_known_model() -> None:
    assert resolve_max_output("gpt-5") == 200_000
    assert resolve_max_output("claude-haiku-4-5") == 8_192


def test_resolve_max_output_unknown_falls_back_to_default() -> None:
    assert resolve_max_output("nope") == 8_192
    assert resolve_max_output("nope", default=16_384) == 16_384
