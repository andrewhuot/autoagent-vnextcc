"""Compaction budget + threshold helpers (pure module).

When a long conversation approaches the model's context window the
orchestrator must decide two things: *should* we compact, and *where*
in the transcript do we compact to. This module answers both with pure
functions so tests can drive them without a live model, an SDK, or any
I/O. The wiring into :mod:`cli.llm.orchestrator` lives in P2 phase 2 —
nothing here imports or mutates orchestrator state.

Design notes:

* **Token counting is injected.** Callers pass ``token_counter`` so
  tests get deterministic sizes and production can hook
  ``ModelClient.count_tokens`` once it lands. The module-level
  :func:`_default_counter` is a conservative ``len(text)//4`` fallback
  that warns once per process the first time it's used — loud enough to
  notice in logs, quiet enough not to spam.

* **Strict greater-than on the threshold.** "At the threshold" is not
  over — callers who want equality-triggered compaction can pass a
  slightly smaller ratio. This avoids an off-by-one that would fire a
  compaction on a transcript sitting exactly at the budget.

* **``min_retained_turns`` is inviolable.** :func:`choose_compact_range`
  never returns a range that includes the last ``min_retained_turns``
  messages even if the transcript is enormous. The guarantee is what
  makes ``/uncompact`` safe to re-run.

* **Provider lookup lives here, not in the factory.** The cheap-model
  alias is a pure dict keyed by provider family; exposing it from
  ``factory.py`` would add a public surface that the factory doesn't
  need to own. Unknown providers raise :class:`KeyError` so callers
  handle the error explicitly rather than silently defaulting to a
  premium model.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Sequence


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompactionBudget:
    """Token budget + threshold config for deciding when to compact.

    Attributes:
        max_context_tokens: Hard ceiling from
            :class:`cli.llm.provider_capabilities.ProviderCapabilities`.
            Never zero (the caller is expected to pull the adapter's
            declared value, which is validated > 0 at construction).
        threshold_ratio: Fire compaction when transcript token count
            exceeds ``max_context_tokens * threshold_ratio``. Strict
            greater-than — equality does not trigger.
        min_retained_turns: The tail of the transcript that is never
            compacted. Keeps the most recent exchanges intact so the
            model still has the immediate context even post-compaction.
    """

    max_context_tokens: int
    threshold_ratio: float = 0.8
    min_retained_turns: int = 4


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------


TokenCounter = Callable[[str], int]


# Module-level flag: ``_default_counter`` warns the first time it's
# called in a process, then stays silent. Tests reset this via
# ``compaction._default_counter_warned = False`` so they can assert the
# warn-once behaviour deterministically.
_default_counter_warned: bool = False


def _default_counter(text: str) -> int:
    """Conservative fallback: ~4 chars per token.

    Emits a single WARNING the first time it's invoked per process so
    operators notice they're running without a real tokenizer — but
    doesn't spam on every call since the orchestrator hits this path
    once per turn at most.
    """
    global _default_counter_warned
    if not _default_counter_warned:
        logger.warning(
            "Compaction using len(text)//4 fallback token counter. "
            "Pass an exact token_counter for production accuracy."
        )
        _default_counter_warned = True
    return len(text) // 4


def _content_text(message: object) -> str:
    """Extract a string from a message for token counting.

    We're defensive: the ``content`` attribute of a
    :class:`~cli.llm.types.TurnMessage` can be a plain string *or* a
    list of content blocks (dicts). ``str(msg)`` is a reliable last
    resort — oversized by a constant factor at worst, never a crash.
    """
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if content is None:
        return str(message)
    return str(content)


def _total_tokens(
    transcript: Sequence[object], counter: TokenCounter
) -> int:
    """Sum token counts across every message in ``transcript``."""
    return sum(counter(_content_text(msg)) for msg in transcript)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def should_compact(
    transcript: Sequence[object],
    budget: CompactionBudget,
    *,
    token_counter: TokenCounter | None = None,
) -> bool:
    """Return ``True`` when the transcript is over the compaction bar.

    Two conditions must both hold:

    1. Total transcript tokens are strictly greater than
       ``budget.threshold_ratio * budget.max_context_tokens``.
    2. ``len(transcript) > budget.min_retained_turns`` — there's
       something left after preserving the protected tail.

    Empty transcripts, below-threshold transcripts, and transcripts
    whose only messages fall inside the retained tail all return False.
    """
    if not transcript:
        return False
    if len(transcript) <= budget.min_retained_turns:
        return False

    counter = token_counter if token_counter is not None else _default_counter
    threshold = budget.threshold_ratio * budget.max_context_tokens
    return _total_tokens(transcript, counter) > threshold


def choose_compact_range(
    transcript: Sequence[object],
    budget: CompactionBudget,
    *,
    token_counter: TokenCounter | None = None,
) -> tuple[int, int] | None:
    """Return the half-open ``(start, end)`` slice to compact.

    ``start`` is always ``0`` — we compact from the head because that's
    where the oldest, least-relevant context lives. ``end`` is
    ``len(transcript) - min_retained_turns`` so the protected tail is
    preserved byte-for-byte.

    Returns ``None`` when :func:`should_compact` would return False —
    empty transcripts, below-threshold transcripts, or transcripts at
    or below the retained-turn floor.
    """
    if not should_compact(transcript, budget, token_counter=token_counter):
        return None

    end = len(transcript) - budget.min_retained_turns
    # Defensive: should_compact already guaranteed end > 0 (since
    # len(transcript) > min_retained_turns), but assert the invariant
    # here so any future change to should_compact surfaces as a failed
    # test rather than a silent empty range.
    if end <= 0:
        return None
    return (0, end)


# ---------------------------------------------------------------------------
# Cheap-model lookup
# ---------------------------------------------------------------------------


_CHEAP_MODEL_BY_PROVIDER: dict[str, str] = {
    "anthropic": "claude-haiku-4",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.5-flash",
}


def cheap_model_for(provider: str) -> str:
    """Return the cheap-model alias for ``provider``.

    Used by the forked-model call path (compaction digest, memory
    extraction) so those calls don't burn premium tokens on tasks a
    small model handles fine. Raises :class:`KeyError` on an unknown
    provider so callers decide the fallback — silently defaulting would
    hide misconfiguration.
    """
    return _CHEAP_MODEL_BY_PROVIDER[provider]


__all__ = [
    "CompactionBudget",
    "TokenCounter",
    "cheap_model_for",
    "choose_compact_range",
    "should_compact",
]
