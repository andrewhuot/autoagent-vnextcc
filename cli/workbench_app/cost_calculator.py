"""Map LLM usage tokens × model pricing → USD cost.

The conversation loop calls :func:`compute_turn_cost` after every
turn to advance ``WorkbenchSession.cost_ticker_usd``. The function
**never raises** — an unknown model, missing pricing, or empty
usage returns ``0.0``. Cost reporting must never block the user.
"""

from __future__ import annotations

from typing import Mapping

from cli.llm.capabilities import get_capability


def _coerce_int(value: object) -> int:
    """Best-effort int coercion. Returns 0 on any failure.

    Some adapters report token counts as strings or floats; we squash
    them to int and clamp negatives to zero so a malformed usage dict
    can never produce a refund or raise."""
    if value is None:
        return 0
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, coerced)


def compute_turn_cost(usage: Mapping[str, int] | None, model_id: str | None) -> float:
    """Return USD cost for one turn's usage dict.

    Accepts both Anthropic-style key names (``input_tokens`` /
    ``output_tokens``) and OpenAI-style aliases (``prompt_tokens`` /
    ``completion_tokens``). Either-or is fine; a usage dict with
    only one of input/output also works.

    Returns 0.0 (not negative, never raises) when:
    - usage is None or empty
    - model_id is None or empty
    - the model is unknown to the capabilities table
    - both token counts are zero
    """
    if not usage or not model_id:
        return 0.0
    try:
        cap = get_capability(model_id)
    except Exception:  # pragma: no cover — defensive only
        return 0.0
    if cap is None:
        return 0.0
    try:
        input_tokens = _coerce_int(usage.get("input_tokens") or usage.get("prompt_tokens"))
        output_tokens = _coerce_int(usage.get("output_tokens") or usage.get("completion_tokens"))
    except Exception:  # pragma: no cover — defensive only
        return 0.0
    if input_tokens == 0 and output_tokens == 0:
        return 0.0
    try:
        cost = (
            input_tokens / 1_000_000.0 * float(cap.input_cost_per_1m)
            + output_tokens / 1_000_000.0 * float(cap.output_cost_per_1m)
        )
    except (TypeError, ValueError):  # pragma: no cover — defensive only
        return 0.0
    return round(cost, 6)


__all__ = ["compute_turn_cost"]
