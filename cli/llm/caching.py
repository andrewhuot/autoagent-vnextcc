"""Prompt-cache breakpoint helpers for Anthropic.

Anthropic's prompt cache lets providers mark large static prefixes of a
request (system prompt, tool schema, pinned memory) so subsequent calls
within a 5-minute window hit the cached prefix at a fraction of the
normal input cost. Dropping breakpoints by hand on every call is
repetitive; this module centralises the decision logic so the provider
client stays focused on SDK translation.

Design:

* :func:`compute_cache_blocks` returns the list of content blocks for
  the *system* field with ``cache_control`` markers attached. The caller
  splices them into the provider request.
* We never cache user-visible messages — they change every turn, which
  would invalidate the cache on each call. The cache targets only
  session-stable content.
* Short prefixes (under :data:`MIN_CACHEABLE_CHARS`) are not cached —
  the cache lookup itself has overhead, so sub-kilobyte prefixes are
  faster served fresh.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


MIN_CACHEABLE_CHARS = 2048
"""Below this size the cache overhead outweighs the savings. Empirically
this threshold mirrors Anthropic's own guidance of "≥1024 tokens" with
margin for multi-byte characters."""


@dataclass
class CacheInput:
    """Inputs that drive the cache decision.

    Keeping the decision inputs in a dataclass rather than threading
    individual kwargs through makes the policy easy to unit-test without
    a provider client in scope."""

    system_prompt: str = ""
    tool_schema_text: str = ""
    """Pre-serialised tool schema. The provider client stringifies the
    tool list once and hands us the text; we don't re-serialise here."""

    pinned_memory: str = ""
    """Session-stable memory (e.g. the rendered AGENTLAB.md) the caller
    wants to share across turns. Passed through unchanged."""


def compute_cache_blocks(inputs: CacheInput) -> list[dict[str, Any]]:
    """Return the cache-annotated content blocks for the provider ``system``
    field.

    The returned list is ready to drop into an Anthropic request as
    ``system=[{...}, {...}]``. Each block carries a ``cache_control``
    marker on its terminal position so the provider uses it as a
    breakpoint. Empty / undersized inputs produce no cache markers so
    callers can unconditionally forward the block list."""
    blocks: list[dict[str, Any]] = []
    if inputs.pinned_memory.strip():
        blocks.append(
            _block(
                inputs.pinned_memory,
                cache=len(inputs.pinned_memory) >= MIN_CACHEABLE_CHARS,
            )
        )
    if inputs.tool_schema_text.strip():
        blocks.append(
            _block(
                inputs.tool_schema_text,
                cache=len(inputs.tool_schema_text) >= MIN_CACHEABLE_CHARS,
            )
        )
    if inputs.system_prompt.strip():
        blocks.append(
            _block(
                inputs.system_prompt,
                cache=len(inputs.system_prompt) >= MIN_CACHEABLE_CHARS,
            )
        )
    return blocks


def _block(text: str, *, cache: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {"type": "text", "text": text}
    if cache:
        payload["cache_control"] = {"type": "ephemeral"}
    return payload


__all__ = ["CacheInput", "MIN_CACHEABLE_CHARS", "compute_cache_blocks"]
