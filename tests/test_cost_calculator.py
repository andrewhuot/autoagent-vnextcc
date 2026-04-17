"""Tests for :mod:`cli.workbench_app.cost_calculator`.

The conversation loop ticks up :attr:`WorkbenchSession.cost_ticker_usd`
after every turn. The calculator must:

- Compute USD cost from token counts × per-1M pricing.
- Accept Anthropic-style (``input_tokens`` / ``output_tokens``) and
  OpenAI-style (``prompt_tokens`` / ``completion_tokens``) keys.
- Never raise — unknown model, missing pricing, empty usage, weird
  inputs all yield ``0.0`` so cost reporting can't break a turn.
"""

from __future__ import annotations

import pytest

from cli.workbench_app.cost_calculator import compute_turn_cost


SONNET = "claude-sonnet-4-5"  # input 3.0 / output 15.0 per 1M


def test_known_model_computes_cost() -> None:
    # 1000 / 1e6 * 3.0 + 500 / 1e6 * 15.0 = 0.003 + 0.0075 = 0.0105
    cost = compute_turn_cost({"input_tokens": 1000, "output_tokens": 500}, SONNET)
    assert cost == pytest.approx(0.0105)


def test_unknown_model_returns_zero() -> None:
    assert compute_turn_cost({"input_tokens": 1000, "output_tokens": 500}, "nonexistent-model") == 0.0


def test_empty_usage_returns_zero() -> None:
    assert compute_turn_cost({}, SONNET) == 0.0


def test_none_usage_returns_zero() -> None:
    assert compute_turn_cost(None, SONNET) == 0.0


def test_none_model_returns_zero() -> None:
    assert compute_turn_cost({"input_tokens": 1000, "output_tokens": 500}, None) == 0.0


def test_empty_model_returns_zero() -> None:
    assert compute_turn_cost({"input_tokens": 1000, "output_tokens": 500}, "") == 0.0


def test_handles_openai_key_aliases() -> None:
    cost = compute_turn_cost({"prompt_tokens": 1000, "completion_tokens": 500}, SONNET)
    assert cost == pytest.approx(0.0105)


def test_handles_anthropic_key_aliases() -> None:
    cost = compute_turn_cost({"input_tokens": 1000, "output_tokens": 500}, SONNET)
    assert cost == pytest.approx(0.0105)


def test_zero_tokens_returns_zero() -> None:
    assert compute_turn_cost({"input_tokens": 0, "output_tokens": 0}, SONNET) == 0.0


def test_only_input_tokens_works() -> None:
    # 1000 / 1e6 * 3.0 = 0.003
    cost = compute_turn_cost({"input_tokens": 1000}, SONNET)
    assert cost == pytest.approx(0.003)


def test_only_output_tokens_works() -> None:
    # 500 / 1e6 * 15.0 = 0.0075
    cost = compute_turn_cost({"output_tokens": 500}, SONNET)
    assert cost == pytest.approx(0.0075)


def test_negative_tokens_treated_as_zero() -> None:
    # Negative token counts must never produce a refund.
    assert compute_turn_cost({"input_tokens": -100}, SONNET) == 0.0


def test_result_rounded_to_six_decimals() -> None:
    # 1 / 1e6 * 3.0 = 3e-6 — verifies the round preserves micro-costs.
    cost = compute_turn_cost({"input_tokens": 1}, SONNET)
    assert cost == 3e-6
