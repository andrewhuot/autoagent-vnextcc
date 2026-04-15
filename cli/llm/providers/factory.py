"""Provider factory — maps a model name to a concrete :class:`ModelClient`.

One-stop shop for callers (REPL, print mode, orchestrator tests) that
want a live model client. The factory:

* Inspects the model name prefix to pick a provider family.
* Consults env + keyword args for credentials without committing to
  where they come from.
* Returns a stub :class:`EchoModel` when the provider family is
  ``"echo"`` so CI smoke tests work without API keys.

Adding a new provider is a two-step operation: map its names in
:data:`MODEL_PROVIDERS` and write a concrete adapter alongside the
Anthropic / OpenAI ones."""

from __future__ import annotations

import os
from typing import Any, Callable

from cli.llm.providers.anthropic_client import AnthropicClient
from cli.llm.providers.openai_client import OpenAIClient
from cli.llm.types import ModelClient


class ProviderFactoryError(RuntimeError):
    """Raised when no provider can be resolved for a model + env combo."""


# Canonical provider → prefix mapping. A resolver picks the longest prefix
# that matches, so callers can still use "gpt-4o" or "gpt-5-mini" without
# listing every variant. Unknown models default to the "anthropic" family
# only when the env/settings explicitly say so — otherwise we raise and
# let the caller supply an override.
MODEL_PROVIDERS: list[tuple[str, str]] = [
    ("claude-", "anthropic"),
    ("gpt-", "openai"),
    ("o1-", "openai"),
    ("o3-", "openai"),
    ("gemini-", "gemini"),
    ("echo", "echo"),
]
"""Order matters — the first match wins. Supports the common alias
shapes: ``claude-sonnet-4-5``, ``gpt-4o``, ``gpt-5-codex``, ``o3-mini``."""


ProviderBuilder = Callable[..., ModelClient]


def create_model_client(
    *,
    model: str,
    api_key: str | None = None,
    request_options: dict[str, Any] | None = None,
    echo_fallback_on_missing_keys: bool = False,
) -> ModelClient:
    """Return a :class:`ModelClient` for ``model``.

    ``echo_fallback_on_missing_keys`` lets headless smoke tests degrade
    gracefully when no provider credentials are configured — print mode
    uses this so ``agentlab print`` is exercisable on a fresh clone
    without secrets. Production callers leave it off so missing keys
    surface as an explicit error."""
    provider = resolve_provider(model)
    options = dict(request_options or {})

    if provider == "anthropic":
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key and echo_fallback_on_missing_keys:
            return _echo_client()
        return AnthropicClient(model=model, api_key=key, request_options=options)

    if provider == "openai":
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key and echo_fallback_on_missing_keys:
            return _echo_client()
        return OpenAIClient(model=model, api_key=key, request_options=options)

    if provider == "gemini":
        # Placeholder — Gemini adapter ships later. For now we fall through
        # to echo when the fallback is allowed so tests keep working.
        if echo_fallback_on_missing_keys:
            return _echo_client()
        raise ProviderFactoryError(
            f"No Gemini adapter bundled yet for model {model!r}. "
            "Use --model echo for smoke tests or wait for the adapter."
        )

    if provider == "echo":
        return _echo_client()

    raise ProviderFactoryError(
        f"No provider match for model {model!r}. "
        f"Known prefixes: {[prefix for prefix, _ in MODEL_PROVIDERS]}."
    )


def resolve_provider(model: str) -> str:
    """Return the provider family for ``model`` — pure function, easy to test."""
    lowered = model.lower()
    best_match = ""
    best_provider = ""
    for prefix, provider in MODEL_PROVIDERS:
        if lowered.startswith(prefix.lower()) and len(prefix) > len(best_match):
            best_match = prefix
            best_provider = provider
    if not best_provider:
        raise ProviderFactoryError(
            f"Cannot resolve provider for model {model!r}. "
            "Update MODEL_PROVIDERS or use an alias."
        )
    return best_provider


def _echo_client() -> ModelClient:
    """Late import to avoid a cycle with :mod:`cli.print_mode`."""
    from cli.print_mode import EchoModel

    return EchoModel()


__all__ = [
    "MODEL_PROVIDERS",
    "ProviderBuilder",
    "ProviderFactoryError",
    "create_model_client",
    "resolve_provider",
]
