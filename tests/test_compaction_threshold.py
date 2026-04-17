"""Tests for ``cli/llm/compaction.py`` — budget + threshold helpers.

Pure-module tests: no orchestrator wiring, no SDK imports, no I/O.
Every test injects an exact ``token_counter`` so results are
tokenizer-independent.
"""

from __future__ import annotations

import logging

import pytest
from dataclasses import FrozenInstanceError

from cli.llm.compaction import (
    CompactionBudget,
    _default_counter,
    cheap_model_for,
    choose_compact_range,
    should_compact,
)
from cli.llm.types import TurnMessage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _exact_counter(text: str) -> int:
    """Count every character as one token — deterministic for tests."""
    return len(text)


def _make_transcript(n_turns: int, per_turn_tokens: int) -> list[TurnMessage]:
    """Synthesise ``n_turns`` alternating user/assistant messages whose
    ``_exact_counter`` size is ``per_turn_tokens`` each."""
    content = "x" * per_turn_tokens
    out: list[TurnMessage] = []
    for i in range(n_turns):
        role = "user" if i % 2 == 0 else "assistant"
        out.append(TurnMessage(role=role, content=content))
    return out


# ---------------------------------------------------------------------------
# should_compact
# ---------------------------------------------------------------------------


def test_empty_transcript_returns_false():
    budget = CompactionBudget(max_context_tokens=1000)
    assert should_compact([], budget, token_counter=_exact_counter) is False


def test_below_threshold_returns_false():
    # threshold = 0.8 * 1000 = 800; transcript total = 500 → False
    budget = CompactionBudget(max_context_tokens=1000, threshold_ratio=0.8)
    transcript = _make_transcript(n_turns=10, per_turn_tokens=50)  # 500 total
    assert should_compact(transcript, budget, token_counter=_exact_counter) is False


def test_at_exact_threshold_returns_false():
    # Strict greater-than: at threshold should NOT compact.
    budget = CompactionBudget(max_context_tokens=1000, threshold_ratio=0.8)
    transcript = _make_transcript(n_turns=10, per_turn_tokens=80)  # 800 total
    assert should_compact(transcript, budget, token_counter=_exact_counter) is False


def test_over_threshold_returns_true():
    # 10 turns × 100 tokens = 1000 > 800 threshold and > min_retained_turns.
    budget = CompactionBudget(max_context_tokens=1000, threshold_ratio=0.8)
    transcript = _make_transcript(n_turns=10, per_turn_tokens=100)
    assert should_compact(transcript, budget, token_counter=_exact_counter) is True


def test_over_threshold_but_too_few_turns_returns_false():
    # Only 4 turns, which equals min_retained_turns → nothing to compact.
    budget = CompactionBudget(
        max_context_tokens=1000, threshold_ratio=0.8, min_retained_turns=4
    )
    transcript = _make_transcript(n_turns=4, per_turn_tokens=500)  # 2000 total
    assert should_compact(transcript, budget, token_counter=_exact_counter) is False


def test_over_threshold_exactly_min_plus_one_returns_true():
    # One turn more than min_retained_turns → compactable (range = [0, 1)).
    budget = CompactionBudget(
        max_context_tokens=1000, threshold_ratio=0.8, min_retained_turns=4
    )
    transcript = _make_transcript(n_turns=5, per_turn_tokens=500)
    assert should_compact(transcript, budget, token_counter=_exact_counter) is True


# ---------------------------------------------------------------------------
# choose_compact_range
# ---------------------------------------------------------------------------


def test_choose_range_empty_returns_none():
    budget = CompactionBudget(max_context_tokens=1000)
    assert choose_compact_range([], budget, token_counter=_exact_counter) is None


def test_choose_range_below_threshold_returns_none():
    budget = CompactionBudget(max_context_tokens=1000, threshold_ratio=0.8)
    transcript = _make_transcript(n_turns=10, per_turn_tokens=50)  # 500 total
    assert (
        choose_compact_range(transcript, budget, token_counter=_exact_counter) is None
    )


def test_choose_range_over_threshold_preserves_min_retained():
    # 10 turns, min_retained=4 → compact range is [0, 6).
    budget = CompactionBudget(
        max_context_tokens=1000, threshold_ratio=0.8, min_retained_turns=4
    )
    transcript = _make_transcript(n_turns=10, per_turn_tokens=100)
    result = choose_compact_range(transcript, budget, token_counter=_exact_counter)
    assert result == (0, 6)


def test_choose_range_never_touches_last_min_retained_turns():
    # Explicit: indices end..len(transcript) must NOT be in the range.
    budget = CompactionBudget(
        max_context_tokens=1000, threshold_ratio=0.8, min_retained_turns=4
    )
    transcript = _make_transcript(n_turns=12, per_turn_tokens=100)
    result = choose_compact_range(transcript, budget, token_counter=_exact_counter)
    assert result is not None
    start, end = result
    retained_start = len(transcript) - 4
    assert end <= retained_start, (
        f"Compact range {result} would overlap the last 4 retained turns "
        f"(retained_start={retained_start})."
    )


def test_choose_range_respects_custom_min_retained_override():
    budget = CompactionBudget(
        max_context_tokens=1000, threshold_ratio=0.8, min_retained_turns=2
    )
    transcript = _make_transcript(n_turns=10, per_turn_tokens=100)
    result = choose_compact_range(transcript, budget, token_counter=_exact_counter)
    # With min_retained=2, we can compact up to index 8 (exclusive).
    assert result == (0, 8)


def test_choose_range_idempotent_on_trimmed_suffix():
    # Simulate "already compacted": only the retained tail remains.
    budget = CompactionBudget(
        max_context_tokens=1000, threshold_ratio=0.8, min_retained_turns=4
    )
    transcript = _make_transcript(n_turns=10, per_turn_tokens=100)
    first = choose_compact_range(transcript, budget, token_counter=_exact_counter)
    assert first is not None
    start, end = first
    # Keep the retained suffix only — re-running should report nothing.
    remaining = list(transcript[end:])
    assert choose_compact_range(
        remaining, budget, token_counter=_exact_counter
    ) is None


# ---------------------------------------------------------------------------
# CompactionBudget immutability
# ---------------------------------------------------------------------------


def test_compaction_budget_is_frozen():
    budget = CompactionBudget(max_context_tokens=1000)
    with pytest.raises(FrozenInstanceError):
        budget.max_context_tokens = 2000  # type: ignore[misc]


# ---------------------------------------------------------------------------
# _default_counter warn-once behaviour
# ---------------------------------------------------------------------------


def test_default_counter_warns_once_per_process(caplog):
    # Reset the warn-once flag so repeated suite runs are deterministic.
    import cli.llm.compaction as compaction_module

    compaction_module._default_counter_warned = False
    caplog.set_level(logging.WARNING, logger="cli.llm.compaction")
    for _ in range(5):
        _default_counter("some text")
    warnings = [
        rec for rec in caplog.records
        if rec.levelno == logging.WARNING and "fallback" in rec.getMessage().lower()
    ]
    assert len(warnings) == 1


def test_default_counter_returns_chars_div_four():
    import cli.llm.compaction as compaction_module

    compaction_module._default_counter_warned = True  # skip warn in this test
    assert _default_counter("x" * 40) == 10
    assert _default_counter("") == 0


# ---------------------------------------------------------------------------
# Defensive handling of non-string content
# ---------------------------------------------------------------------------


def test_non_string_message_content_uses_str_repr():
    # A dict content (e.g. tool_result block) must not crash the counter.
    budget = CompactionBudget(max_context_tokens=100, threshold_ratio=0.8)
    transcript = [
        TurnMessage(role="user", content={"type": "tool_result", "content": "x" * 50}),
        TurnMessage(role="assistant", content="y" * 50),
        TurnMessage(role="user", content="z" * 50),
        TurnMessage(role="assistant", content="q" * 50),
        TurnMessage(role="user", content="r" * 50),
    ]
    # Should not raise — non-string content runs through str(msg).
    should_compact(transcript, budget, token_counter=_exact_counter)


# ---------------------------------------------------------------------------
# cheap_model_for
# ---------------------------------------------------------------------------


def test_cheap_model_for_anthropic():
    assert cheap_model_for("anthropic") == "claude-haiku-4"


def test_cheap_model_for_openai():
    assert cheap_model_for("openai") == "gpt-4o-mini"


def test_cheap_model_for_gemini():
    assert cheap_model_for("gemini") == "gemini-2.5-flash"


def test_cheap_model_for_unknown_raises_keyerror():
    with pytest.raises(KeyError):
        cheap_model_for("unknown-provider")
