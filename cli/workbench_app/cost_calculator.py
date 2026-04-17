"""Map LLM usage tokens × model pricing → USD cost.

The conversation loop calls :func:`compute_turn_cost` after every
turn to advance ``WorkbenchSession.cost_ticker_usd``. The function
**never raises** — an unknown model, missing pricing, or empty
usage returns ``0.0``. Cost reporting must never block the user.

Slash-command LLM calls share the same sink via
:func:`record_slash_cost`, which wraps ``compute_turn_cost`` and
``session.increment_cost`` so a handler can credit cost with one
line. Keeping a single entry point means the status-bar ticker
cannot drift from the computed total, and future pricing fixes only
have to land in one place.

P0.5e moved the canonical rate card into :mod:`cli.llm.pricing`. When
the caller passes ``provider`` we route through the cross-provider
table (with optional settings overrides); when they don't, we fall back
to the legacy :func:`cli.llm.capabilities.get_capability` lookup so
existing call sites (and their tests) keep working unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Mapping

from cli.llm.capabilities import get_capability
from cli.llm.pricing import compute_cost, resolve


if TYPE_CHECKING:  # pragma: no cover — import cycle guard
    from cli.workbench_app.session_state import WorkbenchSession


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


def compute_turn_cost(
    usage: Mapping[str, object] | None,
    model_id: str | None,
    *,
    provider: str | None = None,
    overrides: Mapping[str, Mapping[str, float]] | None = None,
) -> float:
    """Return USD cost for one turn's usage dict.

    Back-compatible with the pre-P0.5e signature: when ``provider`` is
    ``None`` we fall back to the legacy capability table so existing
    call sites (``compute_turn_cost(usage, "claude-sonnet-4-5")``) get
    identical numbers to before.

    When ``provider`` is supplied we route through
    :func:`cli.llm.pricing.resolve` which handles cross-provider rates
    and per-project ``pricing_overrides`` from settings.

    Accepts both Anthropic-style key names (``input_tokens`` /
    ``output_tokens``) and OpenAI-style aliases (``prompt_tokens`` /
    ``completion_tokens``). Cache-read and reasoning/thinking token
    keys are also honored when ``provider`` is set — the legacy path
    stays input+output only to preserve the existing rounding behavior
    that ``test_cost_calculator`` asserts on.

    Returns 0.0 (not negative, never raises) when:
    - usage is None or empty
    - model_id is None or empty
    - the model is unknown to the capabilities table (legacy path)
    - both token counts are zero
    """
    if not usage or not model_id:
        return 0.0

    # Legacy path — preserves the exact pre-P0.5e behavior for call
    # sites that don't know (or don't care) which provider the model
    # belongs to. Unknown models here return 0.0 as before; P0.5e did
    # **not** change that contract because too many call sites rely on
    # "unknown → free" to gate cost reporting.
    if provider is None:
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

    # Cross-provider path — consult the new pricing table with overrides
    # layered on top. ``resolve`` falls back to DEFAULT_PRICE for unknown
    # pairs and logs once per process, so unknown models here cost money
    # (non-zero) instead of silently showing zero — the intent is to
    # surface mis-configured models on the ticker rather than hide them.
    try:
        price = resolve(provider, model_id, overrides=overrides)
    except Exception:  # pragma: no cover — defensive only
        return 0.0
    try:
        return compute_cost(price, usage)
    except Exception:  # pragma: no cover — defensive only
        return 0.0


def record_slash_cost(
    session: "WorkbenchSession",
    *,
    usage: Mapping[str, int] | None,
    model_id: str | None,
    provider: str | None = None,
    overrides: Mapping[str, Mapping[str, float]] | None = None,
) -> float:
    """Compute a slash-command's turn cost and credit it to ``session``.

    Single seam so eval/improve/optimize handlers don't duplicate the
    ``compute_turn_cost`` -> ``increment_cost`` dance — and, more importantly,
    so the status-bar ticker and the calculator can never disagree about
    what was spent. Returns the delta that was applied (``0.0`` when the
    calculator couldn't price the turn) for callers that want to log it.

    Like ``compute_turn_cost``, this never raises: a missing model, empty
    usage, or a zero delta is a no-op on the session.
    """
    delta = compute_turn_cost(usage, model_id, provider=provider, overrides=overrides)
    if delta > 0:
        session.increment_cost(delta)
    return delta


__all__ = ["compute_turn_cost", "record_slash_cost"]
