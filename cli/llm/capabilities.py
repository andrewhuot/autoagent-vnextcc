"""Per-model capability registry.

The REPL used to hardcode a 200k context window everywhere (see
:data:`cli.workbench_app.context_viz.DEFAULT_CONTEXT_LIMIT`), which quietly
lies about usage for GPT-5's 1M window and for smaller Haiku-class models.
This module owns the canonical capability table so the status bar and
``/usage`` grid display the right limit for whatever model is active.

We keep the data as a plain dict of :class:`ModelCapability` dataclasses —
no pydantic, no YAML — because the registry is small, hand-curated, and
must be importable with zero third-party dependencies (tests run offline).
Lookups are case-insensitive and tolerant of the ``-latest`` / date suffixes
vendors attach to model ids so callers can pass whatever their adapter
reports without pre-normalising.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelCapability:
    """Static capability metadata for a single model.

    Costs are USD per 1M tokens at the time of curation. They are here for
    future ``/cost`` style renderers — no code reads them yet, but baking
    them into the registry keeps every consumer pulling from one place.
    """

    name: str
    context_window: int
    max_output_tokens: int
    supports_tool_use: bool
    supports_streaming: bool
    supports_thinking: bool
    supports_prompt_cache: bool
    input_cost_per_1m: float
    output_cost_per_1m: float


def _claude(
    name: str,
    *,
    max_output: int,
    thinking: bool,
    input_cost: float,
    output_cost: float,
) -> ModelCapability:
    # Every Claude 4.x / 3.5 model shares a 200k window, tool use, streaming
    # and prompt caching — only output ceiling and thinking vary.
    return ModelCapability(
        name=name,
        context_window=200_000,
        max_output_tokens=max_output,
        supports_tool_use=True,
        supports_streaming=True,
        supports_thinking=thinking,
        supports_prompt_cache=True,
        input_cost_per_1m=input_cost,
        output_cost_per_1m=output_cost,
    )


MODEL_CAPABILITIES: dict[str, ModelCapability] = {
    # --- Anthropic Claude ---------------------------------------------------
    "claude-haiku-4-5": _claude(
        "claude-haiku-4-5",
        max_output=8_192,
        thinking=False,
        input_cost=1.0,
        output_cost=5.0,
    ),
    "claude-sonnet-4-5": _claude(
        "claude-sonnet-4-5",
        max_output=64_000,
        thinking=False,
        input_cost=3.0,
        output_cost=15.0,
    ),
    "claude-opus-4-5": _claude(
        "claude-opus-4-5",
        max_output=32_000,
        thinking=True,
        input_cost=15.0,
        output_cost=75.0,
    ),
    "claude-opus-4-6": _claude(
        "claude-opus-4-6",
        max_output=64_000,
        thinking=True,
        input_cost=15.0,
        output_cost=75.0,
    ),
    "claude-sonnet-4-6": _claude(
        "claude-sonnet-4-6",
        max_output=64_000,
        thinking=True,
        input_cost=3.0,
        output_cost=15.0,
    ),
    "claude-3-5-sonnet-20241022": _claude(
        "claude-3-5-sonnet-20241022",
        max_output=8_192,
        thinking=False,
        input_cost=3.0,
        output_cost=15.0,
    ),
    "claude-3-5-haiku-20241022": _claude(
        "claude-3-5-haiku-20241022",
        max_output=8_192,
        thinking=False,
        input_cost=0.8,
        output_cost=4.0,
    ),
    # --- OpenAI -------------------------------------------------------------
    # GPT-4o family keeps the classic 128k window; GPT-4.1 bumped to 1M; GPT-5
    # also lands at 1M with a larger output ceiling and reasoning support.
    "gpt-4o": ModelCapability(
        name="gpt-4o",
        context_window=128_000,
        max_output_tokens=16_384,
        supports_tool_use=True,
        supports_streaming=True,
        supports_thinking=False,
        supports_prompt_cache=True,
        input_cost_per_1m=2.5,
        output_cost_per_1m=10.0,
    ),
    "gpt-4o-mini": ModelCapability(
        name="gpt-4o-mini",
        context_window=128_000,
        max_output_tokens=16_384,
        supports_tool_use=True,
        supports_streaming=True,
        supports_thinking=False,
        supports_prompt_cache=True,
        input_cost_per_1m=0.15,
        output_cost_per_1m=0.6,
    ),
    "gpt-4.1": ModelCapability(
        name="gpt-4.1",
        context_window=1_000_000,
        max_output_tokens=32_768,
        supports_tool_use=True,
        supports_streaming=True,
        supports_thinking=False,
        supports_prompt_cache=True,
        input_cost_per_1m=2.0,
        output_cost_per_1m=8.0,
    ),
    "gpt-5": ModelCapability(
        name="gpt-5",
        context_window=1_000_000,
        max_output_tokens=200_000,
        supports_tool_use=True,
        supports_streaming=True,
        supports_thinking=True,
        supports_prompt_cache=True,
        input_cost_per_1m=5.0,
        output_cost_per_1m=20.0,
    ),
    # --- Google Gemini ------------------------------------------------------
    "gemini-2.5-pro": ModelCapability(
        name="gemini-2.5-pro",
        context_window=1_000_000,
        max_output_tokens=65_536,
        supports_tool_use=True,
        supports_streaming=True,
        supports_thinking=True,
        supports_prompt_cache=True,
        input_cost_per_1m=1.25,
        output_cost_per_1m=10.0,
    ),
    "gemini-2.5-flash": ModelCapability(
        name="gemini-2.5-flash",
        context_window=1_000_000,
        max_output_tokens=65_536,
        supports_tool_use=True,
        supports_streaming=True,
        supports_thinking=True,
        supports_prompt_cache=True,
        input_cost_per_1m=0.3,
        output_cost_per_1m=2.5,
    ),
}


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def _normalize(name: str) -> str:
    """Lower-case and trim — adapters often report ``Claude-Opus-4-6`` or
    ``claude-opus-4-6-latest``; strip common marketing suffixes so the
    hand-curated keys keep working without duplicate entries."""
    cleaned = (name or "").strip().lower()
    for suffix in ("-latest", "-preview"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
    return cleaned


def get_capability(model_name: str) -> ModelCapability | None:
    """Return the capability for ``model_name`` or ``None`` when unknown.

    Callers that need a guaranteed non-null value should use
    :func:`resolve_context_limit` / :func:`resolve_max_output`, which
    fall back to safe defaults."""
    if not model_name:
        return None
    key = _normalize(model_name)
    if key in MODEL_CAPABILITIES:
        return MODEL_CAPABILITIES[key]
    # Date-suffixed ids like ``claude-3-5-sonnet-20241022`` already exist as
    # exact keys; for unseen date stamps on known families, strip the trailing
    # ``-YYYYMMDD`` and retry once so we degrade gracefully.
    if len(key) > 9 and key[-9] == "-" and key[-8:].isdigit():
        trimmed = key[:-9]
        if trimmed in MODEL_CAPABILITIES:
            return MODEL_CAPABILITIES[trimmed]
    return None


def resolve_context_limit(model_name: str | None, default: int = 200_000) -> int:
    """Return the context window for ``model_name`` or ``default`` when
    the model isn't in the registry.

    Callers like the ``/usage`` renderer pass the active-model id straight
    through; keeping the fallback here means every consumer gets the same
    conservative 200k default without duplicating the constant."""
    if not model_name:
        return default
    cap = get_capability(model_name)
    return cap.context_window if cap is not None else default


def resolve_max_output(model_name: str | None, default: int = 8_192) -> int:
    """Return the max-output ceiling for ``model_name`` or ``default``."""
    if not model_name:
        return default
    cap = get_capability(model_name)
    return cap.max_output_tokens if cap is not None else default


__all__ = [
    "MODEL_CAPABILITIES",
    "ModelCapability",
    "get_capability",
    "resolve_context_limit",
    "resolve_max_output",
]
