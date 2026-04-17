"""Cross-provider pricing table keyed by ``(provider, model)``.

The conversation loop's cost ticker used to hard-code Claude rates through
:mod:`cli.llm.capabilities`, which quietly under- or over-charged every
OpenAI and Gemini call. This module owns the canonical rate card so the
workbench cost ticker, ``/cost`` renderers, and the doctor surface all pull
from one source and respect per-project overrides cascaded from settings.

Effective date of quoted rates: **2026-04-17**. Verify current values at
``anthropic.com/pricing``, ``openai.com/api/pricing``, and
``cloud.google.com/vertex-ai/generative-ai/pricing`` before relying on
these for production billing; the module has no automatic refresh.

Design notes:

* :class:`TokenPrice` is a frozen dataclass so no one accidentally mutates
  the global table — overrides produce a **new** price object instead.
* Optional fields (``cache_read_per_m``, ``cache_write_per_m``,
  ``thinking_per_m``) are ``None`` when a provider doesn't bill that
  token category separately. The calculator treats ``None`` as "no
  discount, no surcharge" — cache-read tokens at ``None`` bill at the
  normal input rate, thinking tokens at ``None`` bill at the output rate.
* :func:`resolve` emits exactly one ``logging.warning`` per unknown
  ``(provider, model)`` pair per process. Cost is never a hot path but
  the ticker runs after every turn — we do not want a noisy log stream.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Mapping, Optional


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TokenPrice:
    """Per-million-token pricing for one ``(provider, model)``.

    ``None`` on an optional field means "this token category does not
    have a distinct rate for this model" — the calculator falls back to
    the input rate for cache-read tokens and the output rate for
    thinking/reasoning tokens. Separate ``0.0`` values mean "this token
    category is free" (e.g. Gemini cached-content discount going to
    zero); callers must respect the difference.
    """

    input_per_m: float
    output_per_m: float
    cache_read_per_m: Optional[float] = None
    cache_write_per_m: Optional[float] = None  # Anthropic ephemeral; OpenAI/Gemini are None.
    thinking_per_m: Optional[float] = None     # Reasoning-token surcharge where it differs.


# ---------------------------------------------------------------------------
# Canonical rate card
# ---------------------------------------------------------------------------
#
# Values verified against public pricing pages on 2026-04-17. Anthropic
# cache-write rates use the 5-minute ephemeral tier (the one the client
# uses by default). OpenAI cache-read rates match the standard 50%
# discount tier except for o1/o3/o5 which publish explicit numbers.
# Gemini 2.5 cache-read rates use the context-cache discount column.
PRICING: dict[tuple[str, str], TokenPrice] = {
    # --- Anthropic Claude ---------------------------------------------------
    # claude-sonnet-4-6 ships at the same $3/$15 tier as 4-5; keep both in
    # the table so either model id resolves cleanly.
    ("anthropic", "claude-sonnet-4-6"): TokenPrice(
        input_per_m=3.0,
        output_per_m=15.0,
        cache_read_per_m=0.30,
        cache_write_per_m=3.75,
    ),
    ("anthropic", "claude-sonnet-4-5"): TokenPrice(
        input_per_m=3.0,
        output_per_m=15.0,
        cache_read_per_m=0.30,
        cache_write_per_m=3.75,
    ),
    ("anthropic", "claude-opus-4-6"): TokenPrice(
        input_per_m=15.0,
        output_per_m=75.0,
        cache_read_per_m=1.50,
        cache_write_per_m=18.75,
    ),
    ("anthropic", "claude-opus-4-5"): TokenPrice(
        input_per_m=15.0,
        output_per_m=75.0,
        cache_read_per_m=1.50,
        cache_write_per_m=18.75,
    ),
    ("anthropic", "claude-haiku-4-5"): TokenPrice(
        input_per_m=1.0,
        output_per_m=5.0,
        cache_read_per_m=0.10,
        cache_write_per_m=1.25,
    ),
    ("anthropic", "claude-haiku-4"): TokenPrice(
        input_per_m=0.80,
        output_per_m=4.0,
        cache_read_per_m=0.08,
        cache_write_per_m=1.0,
    ),

    # --- OpenAI -------------------------------------------------------------
    ("openai", "gpt-4o"): TokenPrice(
        input_per_m=2.50,
        output_per_m=10.0,
        cache_read_per_m=1.25,
    ),
    ("openai", "gpt-4o-mini"): TokenPrice(
        input_per_m=0.15,
        output_per_m=0.60,
        cache_read_per_m=0.075,
    ),
    ("openai", "gpt-4.1"): TokenPrice(
        input_per_m=2.0,
        output_per_m=8.0,
        cache_read_per_m=0.50,
    ),
    ("openai", "gpt-5"): TokenPrice(
        input_per_m=10.0,
        output_per_m=40.0,
        cache_read_per_m=5.0,
        thinking_per_m=40.0,
    ),
    ("openai", "o1"): TokenPrice(
        input_per_m=15.0,
        output_per_m=60.0,
        cache_read_per_m=7.50,
        thinking_per_m=60.0,
    ),
    ("openai", "o3"): TokenPrice(
        input_per_m=15.0,
        output_per_m=60.0,
        cache_read_per_m=7.50,
        thinking_per_m=60.0,
    ),
    ("openai", "o3-mini"): TokenPrice(
        input_per_m=1.10,
        output_per_m=4.40,
        cache_read_per_m=0.55,
        thinking_per_m=4.40,
    ),
    ("openai", "o4-mini"): TokenPrice(
        input_per_m=1.10,
        output_per_m=4.40,
        cache_read_per_m=0.55,
        thinking_per_m=4.40,
    ),

    # --- Google Gemini ------------------------------------------------------
    ("gemini", "gemini-2.5-pro"): TokenPrice(
        input_per_m=1.25,
        output_per_m=10.0,
        cache_read_per_m=0.3125,
    ),
    ("gemini", "gemini-2.5-flash"): TokenPrice(
        input_per_m=0.30,
        output_per_m=2.50,
        cache_read_per_m=0.075,
    ),
    ("gemini", "gemini-2.0-flash"): TokenPrice(
        input_per_m=0.10,
        output_per_m=0.40,
        cache_read_per_m=0.025,
    ),
}


# Conservative fallback applied when ``(provider, model)`` isn't in PRICING
# and the caller didn't supply an override. Pitched between Sonnet and Opus
# so unknown models cost money on the ticker (so you notice) but do not
# crash the cost pipeline.
DEFAULT_PRICE = TokenPrice(
    input_per_m=5.0,
    output_per_m=20.0,
    cache_read_per_m=0.50,
)


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


# Module-level set so each unknown ``(provider, model)`` pair logs **exactly
# once** per process. The cost ticker fires after every turn; without this
# guard a mis-typed model would spam the warnings channel.
_WARNED_PAIRS: set[tuple[str, str]] = set()


def _override_key(provider: str, model: str) -> str:
    """Canonical settings-override key: ``"<provider>:<model>"``."""
    return f"{provider}:{model}"


def resolve(
    provider: str,
    model: str,
    overrides: Mapping[str, Mapping[str, float]] | None = None,
) -> TokenPrice:
    """Resolve pricing for ``(provider, model)`` with optional overrides.

    Precedence:

    1. ``overrides[f"{provider}:{model}"]`` — a partial dict layers on top
       of the base price; keys not in the dict keep the base value. A
       **full** override (all five fields) produces a standalone price
       with no lookup into :data:`PRICING` needed.
    2. :data:`PRICING[(provider, model)]` when no override applies.
    3. :data:`DEFAULT_PRICE` as a final safety net. Emits one
       ``logging.warning`` per unseen pair so operators can spot a missing
       entry without being flooded every turn.
    """
    key = (provider or "", model or "")

    override_entry: Mapping[str, float] | None = None
    if overrides:
        raw = overrides.get(_override_key(provider or "", model or ""))
        if isinstance(raw, Mapping):
            override_entry = raw

    base: TokenPrice | None = PRICING.get(key)

    if override_entry is not None:
        # Layer the override on top of whichever base exists, or on top of
        # DEFAULT_PRICE when the model is unknown. The overrides dict is
        # intentionally flat — we filter unknown keys so a typo in
        # settings.json can't blow up the cost pipeline.
        foundation = base if base is not None else DEFAULT_PRICE
        patch = {
            field: float(value)
            for field, value in override_entry.items()
            if field in {
                "input_per_m",
                "output_per_m",
                "cache_read_per_m",
                "cache_write_per_m",
                "thinking_per_m",
            }
        }
        return replace(foundation, **patch) if patch else foundation

    if base is not None:
        return base

    # Unknown pair — warn exactly once per process and return DEFAULT_PRICE.
    if key not in _WARNED_PAIRS:
        _WARNED_PAIRS.add(key)
        logger.warning(
            "pricing fallback for %s/%s — using DEFAULT_PRICE (input=%s/M, output=%s/M)",
            provider or "?",
            model or "?",
            DEFAULT_PRICE.input_per_m,
            DEFAULT_PRICE.output_per_m,
        )
    return DEFAULT_PRICE


def compute_cost(price: TokenPrice, usage: Mapping[str, object]) -> float:
    """Apply ``price`` to ``usage`` and return USD cost, rounded to 6 dp.

    Recognized usage keys (all optional):

    * ``input_tokens`` or ``prompt_tokens`` — fresh input.
    * ``output_tokens`` or ``completion_tokens`` — generated text.
    * ``cache_read_tokens`` — billed at ``cache_read_per_m`` when set;
      otherwise billed at the input rate.
    * ``cache_creation_input_tokens`` — Anthropic cache-write. Billed at
      ``cache_write_per_m`` when set; otherwise at the input rate.
    * ``reasoning_tokens`` or ``thinking_tokens`` — billed at
      ``thinking_per_m`` when set; otherwise at the output rate.

    Never raises — malformed numbers coerce to zero. Callers that need
    provider/model resolution should use
    :func:`cli.workbench_app.cost_calculator.compute_turn_cost` instead.
    """
    if not usage:
        return 0.0

    def _nat(value: object) -> int:
        if value is None:
            return 0
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0

    input_tokens = _nat(usage.get("input_tokens") or usage.get("prompt_tokens"))
    output_tokens = _nat(usage.get("output_tokens") or usage.get("completion_tokens"))
    cache_read = _nat(usage.get("cache_read_tokens"))
    cache_write = _nat(usage.get("cache_creation_input_tokens"))
    thinking = _nat(usage.get("reasoning_tokens") or usage.get("thinking_tokens"))

    # Resolve effective per-token rates in dollars.
    input_rate = float(price.input_per_m) / 1_000_000.0
    output_rate = float(price.output_per_m) / 1_000_000.0
    cache_read_rate = (
        float(price.cache_read_per_m) / 1_000_000.0
        if price.cache_read_per_m is not None
        else input_rate
    )
    cache_write_rate = (
        float(price.cache_write_per_m) / 1_000_000.0
        if price.cache_write_per_m is not None
        else input_rate
    )
    thinking_rate = (
        float(price.thinking_per_m) / 1_000_000.0
        if price.thinking_per_m is not None
        else output_rate
    )

    cost = (
        input_tokens * input_rate
        + output_tokens * output_rate
        + cache_read * cache_read_rate
        + cache_write * cache_write_rate
        + thinking * thinking_rate
    )
    return round(cost, 6)


def _reset_warned_pairs_for_tests() -> None:
    """Clear the unknown-pair warning cache. Tests only — production code
    should never need to reset this."""
    _WARNED_PAIRS.clear()


__all__ = [
    "DEFAULT_PRICE",
    "PRICING",
    "TokenPrice",
    "compute_cost",
    "resolve",
]
