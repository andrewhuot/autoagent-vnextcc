"""Cross-provider tests for :mod:`cli.workbench_app.cost_calculator`.

These tests exercise the new ``provider=`` / ``overrides=`` keyword
path added in P0.5e. The legacy single-argument contract is covered by
``tests/test_cost_calculator.py``; here we focus on:

* Back-compat: Anthropic rates via the legacy path match the new path.
* OpenAI and Gemini rates compute correctly via the cross-provider
  table.
* Thinking / reasoning tokens add to cost for o-series models.
* ``Settings.providers.pricing_overrides`` end-to-end plumbing.
* Unknown ``(provider, model)`` falls back to DEFAULT_PRICE and logs
  exactly once.
"""

from __future__ import annotations

import logging

import pytest

from cli.llm import pricing
from cli.settings import Settings
from cli.workbench_app.cost_calculator import compute_turn_cost


@pytest.fixture(autouse=True)
def _clean_warning_cache() -> None:
    pricing._reset_warned_pairs_for_tests()
    yield
    pricing._reset_warned_pairs_for_tests()


def test_anthropic_cost_matches_legacy_hard_coded_result() -> None:
    # The legacy path returns 0.0105 for this usage (see
    # tests/test_cost_calculator.py::test_known_model_computes_cost).
    usage = {"input_tokens": 1000, "output_tokens": 500}
    legacy = compute_turn_cost(usage, "claude-sonnet-4-5")
    assert legacy == pytest.approx(0.0105)
    # And the new path with explicit provider gives the same number.
    explicit = compute_turn_cost(usage, "claude-sonnet-4-5", provider="anthropic")
    assert explicit == pytest.approx(0.0105)


def test_openai_gpt4o_cost_computed_correctly() -> None:
    # gpt-4o: $2.50/M input, $10.00/M output.
    usage = {"input_tokens": 1_000, "output_tokens": 500}
    cost = compute_turn_cost(usage, "gpt-4o", provider="openai")
    # 1000 * 2.5 / 1e6 + 500 * 10 / 1e6 = 0.0025 + 0.005 = 0.0075
    assert cost == pytest.approx(0.0075)


def test_gemini_2_5_pro_cost_computed_correctly() -> None:
    # gemini-2.5-pro: $1.25/M input, $10.00/M output.
    usage = {"input_tokens": 1_000, "output_tokens": 500}
    cost = compute_turn_cost(usage, "gemini-2.5-pro", provider="gemini")
    assert cost == pytest.approx(1_000 * 1.25 / 1e6 + 500 * 10.0 / 1e6)


def test_o3_thinking_tokens_add_to_cost() -> None:
    # o3: $15/M input, $60/M output, $60/M thinking. Reasoning tokens
    # must change the total.
    usage_base = {"input_tokens": 1000, "output_tokens": 100}
    usage_with_thinking = {**usage_base, "reasoning_tokens": 10_000}
    base_cost = compute_turn_cost(usage_base, "o3", provider="openai")
    with_thinking_cost = compute_turn_cost(
        usage_with_thinking, "o3", provider="openai"
    )
    assert with_thinking_cost > base_cost
    # Thinking delta = 10_000 / 1e6 * 60 = 0.6
    assert with_thinking_cost - base_cost == pytest.approx(0.6)


def test_openai_cache_read_uses_discount_rate() -> None:
    # gpt-4o cache-read rate is $1.25/M (half of input).
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 1_000_000}
    cost = compute_turn_cost(usage, "gpt-4o", provider="openai")
    assert cost == pytest.approx(1.25)


def test_pricing_override_flows_from_settings_end_to_end() -> None:
    # Settings object carries pricing_overrides; the workbench passes
    # the resolved dict into compute_turn_cost. Wire both sides.
    settings = Settings.model_validate(
        {
            "providers": {
                "default_provider": "openai",
                "default_model": "gpt-4o",
                "pricing_overrides": {
                    "openai:gpt-4o": {"input_per_m": 100.0, "output_per_m": 200.0},
                },
            }
        }
    )
    overrides = settings.providers.pricing_overrides
    usage = {"input_tokens": 1000, "output_tokens": 500}
    cost = compute_turn_cost(
        usage,
        "gpt-4o",
        provider="openai",
        overrides=overrides,
    )
    # 1000 * 100 / 1e6 + 500 * 200 / 1e6 = 0.1 + 0.1 = 0.2
    assert cost == pytest.approx(0.2)


def test_unknown_provider_model_uses_default_price_and_logs_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="cli.llm.pricing")
    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
    cost_1 = compute_turn_cost(usage, "mystery-model", provider="mystery")
    cost_2 = compute_turn_cost(usage, "mystery-model", provider="mystery")
    # DEFAULT_PRICE = 5.0 input + 20.0 output per M.
    assert cost_1 == pytest.approx(25.0)
    # Second call returns identical cost but must not double-log.
    assert cost_2 == pytest.approx(25.0)
    warnings = [r for r in caplog.records if "pricing fallback" in r.getMessage()]
    assert len(warnings) == 1


def test_unknown_provider_legacy_path_still_returns_zero() -> None:
    # With provider=None (legacy), unknown model → 0.0 as before.
    # This preserves the contract callers rely on to gate cost display.
    assert compute_turn_cost({"input_tokens": 1000}, "mystery-model") == 0.0


def test_overrides_without_provider_are_ignored() -> None:
    # Overrides only apply on the new path — legacy callers that happen
    # to pass overrides=... without provider=... still go through the
    # capability-table path, so their overrides silently do not apply.
    usage = {"input_tokens": 1000, "output_tokens": 500}
    cost = compute_turn_cost(
        usage,
        "claude-sonnet-4-5",
        overrides={"anthropic:claude-sonnet-4-5": {"input_per_m": 999.0}},
    )
    # Legacy Anthropic capability rates: 3.0 / 15.0 per M.
    assert cost == pytest.approx(0.0105)
