"""Tests for :mod:`cli.llm.pricing`.

The pricing module is the single source of truth for per-token costs.
We exercise:

* Known-pair lookup.
* Override merge (partial and full).
* Unknown-pair fallback and one-shot logging.
* Frozen-dataclass invariant.
* ``compute_cost`` math for every billed token category.

``_reset_warned_pairs_for_tests`` is called on the logging tests so
earlier fixtures don't swallow a pair we care about.
"""

from __future__ import annotations

import dataclasses
import logging

import pytest

from cli.llm import pricing
from cli.llm.pricing import (
    DEFAULT_PRICE,
    PRICING,
    TokenPrice,
    compute_cost,
    resolve,
)


@pytest.fixture(autouse=True)
def _clean_warning_cache() -> None:
    """Every test sees a fresh "already warned" set so log-once assertions
    don't depend on test ordering."""
    pricing._reset_warned_pairs_for_tests()
    yield
    pricing._reset_warned_pairs_for_tests()


def test_resolve_known_anthropic_pair_returns_table_entry() -> None:
    price = resolve("anthropic", "claude-sonnet-4-6")
    assert price.input_per_m == 3.0
    assert price.output_per_m == 15.0
    assert price.cache_read_per_m == 0.30
    assert price.cache_write_per_m == 3.75


def test_resolve_known_openai_pair_returns_table_entry() -> None:
    price = resolve("openai", "gpt-4o")
    assert price.input_per_m == 2.50
    assert price.output_per_m == 10.0
    assert price.cache_read_per_m == 1.25


def test_resolve_unknown_pair_returns_default_price() -> None:
    price = resolve("openai", "gpt-9000-ultra-plus")
    assert price == DEFAULT_PRICE


def test_resolve_unknown_pair_logs_exactly_once(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="cli.llm.pricing")
    for _ in range(5):
        resolve("foo", "bar")
    warnings = [r for r in caplog.records if "pricing fallback" in r.getMessage()]
    assert len(warnings) == 1


def test_resolve_different_unknown_pairs_each_log_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="cli.llm.pricing")
    resolve("foo", "bar")
    resolve("foo", "bar")
    resolve("baz", "qux")
    warnings = [r for r in caplog.records if "pricing fallback" in r.getMessage()]
    assert len(warnings) == 2


def test_resolve_partial_override_merges_onto_base() -> None:
    overrides = {
        "anthropic:claude-sonnet-4-6": {"input_per_m": 99.0},
    }
    price = resolve("anthropic", "claude-sonnet-4-6", overrides=overrides)
    assert price.input_per_m == 99.0
    # Non-overridden fields keep their base values.
    assert price.output_per_m == 15.0
    assert price.cache_read_per_m == 0.30
    assert price.cache_write_per_m == 3.75


def test_resolve_full_override_replaces_all_fields() -> None:
    overrides = {
        "anthropic:claude-sonnet-4-6": {
            "input_per_m": 1.0,
            "output_per_m": 2.0,
            "cache_read_per_m": 0.1,
            "cache_write_per_m": 1.25,
            "thinking_per_m": 2.0,
        },
    }
    price = resolve("anthropic", "claude-sonnet-4-6", overrides=overrides)
    assert price.input_per_m == 1.0
    assert price.output_per_m == 2.0
    assert price.cache_read_per_m == 0.1
    assert price.cache_write_per_m == 1.25
    assert price.thinking_per_m == 2.0


def test_resolve_override_for_unknown_model_never_hits_fallback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="cli.llm.pricing")
    overrides = {"foo:bar": {"input_per_m": 1.0, "output_per_m": 2.0}}
    price = resolve("foo", "bar", overrides=overrides)
    # Override applied on top of DEFAULT_PRICE foundation; our overridden
    # fields stick, the rest inherit from DEFAULT_PRICE.
    assert price.input_per_m == 1.0
    assert price.output_per_m == 2.0
    # No fallback warning because we had an override.
    warnings = [r for r in caplog.records if "pricing fallback" in r.getMessage()]
    assert warnings == []


def test_resolve_override_with_unknown_key_is_ignored() -> None:
    # A typo in settings must not blow up the cost pipeline.
    overrides = {"anthropic:claude-sonnet-4-6": {"inputy_per_m": 99.0}}
    price = resolve("anthropic", "claude-sonnet-4-6", overrides=overrides)
    # Unknown key silently dropped → base price returned unchanged.
    assert price.input_per_m == 3.0


def test_token_price_is_frozen() -> None:
    price = TokenPrice(input_per_m=1.0, output_per_m=2.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        price.input_per_m = 99.0  # type: ignore[misc]


def test_token_price_optional_fields_default_to_none() -> None:
    price = TokenPrice(input_per_m=1.0, output_per_m=2.0)
    assert price.cache_read_per_m is None
    assert price.cache_write_per_m is None
    assert price.thinking_per_m is None


def test_compute_cost_basic_input_output() -> None:
    price = TokenPrice(input_per_m=3.0, output_per_m=15.0)
    cost = compute_cost(price, {"input_tokens": 1000, "output_tokens": 500})
    assert cost == pytest.approx(0.003 + 0.0075)


def test_compute_cost_cache_read_uses_discount_rate() -> None:
    price = TokenPrice(input_per_m=3.0, output_per_m=15.0, cache_read_per_m=0.3)
    usage = {
        "input_tokens": 500_000,
        "output_tokens": 500_000,
        "cache_read_tokens": 500_000,
    }
    # 500k input @ $3/M = $1.5, 500k output @ $15/M = $7.5, 500k cache
    # read @ $0.3/M = $0.15 → $9.15
    assert compute_cost(price, usage) == pytest.approx(9.15)


def test_compute_cost_cache_read_none_bills_at_input_rate() -> None:
    price = TokenPrice(input_per_m=3.0, output_per_m=15.0, cache_read_per_m=None)
    usage = {"cache_read_tokens": 1_000_000}
    # No discount rate declared → cache-read tokens bill at input.
    assert compute_cost(price, usage) == pytest.approx(3.0)


def test_compute_cost_thinking_tokens_billed_at_thinking_rate() -> None:
    price = TokenPrice(input_per_m=5.0, output_per_m=20.0, thinking_per_m=40.0)
    usage = {
        "input_tokens": 100_000,
        "output_tokens": 10_000,
        "reasoning_tokens": 40_000,
    }
    # 100k * 5/M + 10k * 20/M + 40k * 40/M = 0.5 + 0.2 + 1.6 = 2.3
    assert compute_cost(price, usage) == pytest.approx(2.3)


def test_compute_cost_thinking_none_bills_at_output_rate() -> None:
    price = TokenPrice(input_per_m=5.0, output_per_m=20.0, thinking_per_m=None)
    usage = {"reasoning_tokens": 1_000_000}
    assert compute_cost(price, usage) == pytest.approx(20.0)


def test_compute_cost_cache_write_uses_write_rate() -> None:
    price = TokenPrice(
        input_per_m=3.0,
        output_per_m=15.0,
        cache_write_per_m=3.75,
    )
    usage = {"cache_creation_input_tokens": 1_000_000}
    assert compute_cost(price, usage) == pytest.approx(3.75)


def test_compute_cost_empty_usage_returns_zero() -> None:
    price = TokenPrice(input_per_m=3.0, output_per_m=15.0)
    assert compute_cost(price, {}) == 0.0


def test_compute_cost_malformed_values_coerce_to_zero() -> None:
    price = TokenPrice(input_per_m=3.0, output_per_m=15.0)
    # Non-int values get squashed to zero instead of raising.
    cost = compute_cost(price, {"input_tokens": "oops", "output_tokens": None})
    assert cost == 0.0


def test_compute_cost_openai_key_aliases_recognized() -> None:
    price = TokenPrice(input_per_m=3.0, output_per_m=15.0)
    cost = compute_cost(price, {"prompt_tokens": 1000, "completion_tokens": 500})
    assert cost == pytest.approx(0.003 + 0.0075)


def test_pricing_table_contains_expected_anchors() -> None:
    # Guard against accidental deletions — if someone removes one of
    # these rows the ticker silently falls back to DEFAULT_PRICE.
    for key in [
        ("anthropic", "claude-sonnet-4-6"),
        ("anthropic", "claude-opus-4-6"),
        ("openai", "gpt-4o"),
        ("openai", "gpt-5"),
        ("gemini", "gemini-2.5-pro"),
    ]:
        assert key in PRICING, f"missing expected pricing row: {key!r}"
