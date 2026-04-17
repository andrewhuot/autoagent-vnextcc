"""Tool-phase digest generator (pure + forked-model client).

When compaction fires the orchestrator needs to collapse a chunk of old
tool-call traffic into something the model can still reason about
without re-paying for 5KB of grep output. This module produces that
replacement:

* :func:`group_tool_phase` — split a transcript slice into contiguous
  tool-call phases (text-only turns stay singleton).
* :func:`choose_strategy` — pure selector on a slice. One oversized
  blob flips the whole phase to ``"extractive"``; everything else is
  ``"abstractive"``.
* :func:`digest_tool_phase` — produce a
  :class:`ToolUseSummaryMessage` for a slice. Branches on strategy and
  gracefully falls back to extractive when the forked model isn't
  available or misbehaves.

Design notes:

* **Model factory is injected.** Tests pass ``model_factory=None`` and
  exercise the extractive branch exclusively; production wires
  ``lambda: create_model_client(model=cheap_model_for(active))``. The
  module never imports :mod:`cli.llm.providers.factory` at module-load
  time — no circular import with the compaction wiring that will live
  in orchestrator.py.

* **Never parses partial JSON.** The digest operates on complete
  messages only. If a shape surprises us we wrap the value in
  ``str()`` rather than crash — the digest is lossy by definition, so
  a best-effort stringification is strictly better than raising inside
  a compaction step.

* **First/last-20-line extractive default.** Chosen because grep /
  file_read output almost always has its signal at either the head
  (matches near top) or the tail (error traceback). 40 preserved
  lines fits comfortably under the big-blob threshold even after
  round-tripping, so extractive digests are strictly smaller than the
  originals.

* **Abstractive targets ≤ 500 tokens.** Enforced via prompt
  instruction since we can't hard-cap without a tokenizer. Callers
  that need a tighter bound read ``total_bytes_out`` and escalate.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Sequence


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


BIG_BLOB_BYTES = 2048
"""Any single tool_result block strictly greater than this forces the
entire phase into the extractive branch. Matches the TDD plan's 2KB
cutoff — a grep / file_read result over ~2KB is almost certainly a
blob we can't reliably summarise without losing signal."""


_EXTRACTIVE_HEAD_LINES = 20
_EXTRACTIVE_TAIL_LINES = 20
_ABSTRACTIVE_MAX_TOKENS = 500


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolUseSummaryMessage:
    """A digest that replaces a contiguous tool-call phase in the transcript.

    Renders as a system message in the transcript and as a normal
    assistant turn for the model. Preserves enough detail for the
    model to reason about what happened without re-exposing big blobs.

    Attributes:
        tool_names: Ordered tool names pulled from the original slice
            (duplicates preserved — the order is semantically load-
            bearing for the model).
        strategy: Either ``"extractive"`` or ``"abstractive"``.
        summary: The human-readable digest body. Rendered as-is in the
            transcript UI and as the content of the replacement
            assistant turn.
        original_turn_count: Number of transcript messages collapsed
            into this digest. Used by ``/doctor`` to report compaction
            ratios.
        total_bytes_in: Sum of ``len(str(content))`` across the
            original messages. Diagnostic only.
        total_bytes_out: ``len(summary.encode('utf-8'))`` — the bytes
            the digest actually costs. ``/doctor`` divides this into
            ``total_bytes_in`` for the compression ratio.
    """

    tool_names: tuple[str, ...]
    strategy: str
    summary: str
    original_turn_count: int
    total_bytes_in: int
    total_bytes_out: int


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _content_blocks(message: object) -> list[Any]:
    """Return ``message.content`` as a list of blocks.

    Strings and ``None`` return ``[]`` — text-only turns have no tool
    blocks. A list is returned as-is. Anything else is wrapped in a
    single-element list so downstream code can uniformly iterate.
    """
    content = getattr(message, "content", None)
    if content is None or isinstance(content, str):
        return []
    if isinstance(content, list):
        return list(content)
    return [content]


def _block_type(block: Any) -> str:
    """Return the ``type`` field of a block, or ``""`` if absent.

    Blocks can be dicts (tool_result style) or dataclass instances
    (AssistantToolUseBlock). Both expose ``type``; a missing value
    means the block is opaque and we treat it as neither tool_use nor
    tool_result.
    """
    if isinstance(block, dict):
        return str(block.get("type", ""))
    return str(getattr(block, "type", ""))


def _block_name(block: Any) -> str:
    """Return the tool ``name`` on a tool_use block, or ``""``."""
    if isinstance(block, dict):
        return str(block.get("name", ""))
    return str(getattr(block, "name", ""))


def _block_content(block: Any) -> str:
    """Return the text content of a tool_result block as a string.

    Tool results can carry a string directly or a list of content
    sub-blocks (the Anthropic wire shape). We stringify defensively —
    the digest is lossy, so a ``str()`` fallback beats raising.
    """
    if isinstance(block, dict):
        value = block.get("content", "")
    else:
        value = getattr(block, "content", "")
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for sub in value:
            if isinstance(sub, dict) and "text" in sub:
                parts.append(str(sub.get("text", "")))
            else:
                parts.append(str(sub))
        return "\n".join(parts)
    return str(value)


def _message_has_tool_use(message: object) -> bool:
    """True if ``message`` carries any ``tool_use`` or ``tool_result`` block."""
    for block in _content_blocks(message):
        if _block_type(block) in ("tool_use", "tool_result"):
            return True
    return False


def _bytes_of(message: object) -> int:
    """Cheap byte-count proxy for accounting."""
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return len(content.encode("utf-8"))
    return len(str(content).encode("utf-8"))


# ---------------------------------------------------------------------------
# group_tool_phase
# ---------------------------------------------------------------------------


def group_tool_phase(
    transcript: Sequence[object],
    start: int,
    end: int,
) -> list[tuple[int, int]]:
    """Return ``[(start_i, end_i), ...]`` sub-ranges over ``[start, end)``.

    Each sub-range is either:

    * a contiguous run of tool-call / tool-result turns, or
    * a single text-only assistant or user turn.

    Runs split on text-only turns so the digester can treat each tool
    phase independently. An empty input range returns ``[]``.
    """
    if start >= end or start < 0:
        return []

    ranges: list[tuple[int, int]] = []
    i = start
    while i < end:
        is_tool = _message_has_tool_use(transcript[i])
        if not is_tool:
            # Text-only turn: emit as singleton so the caller sees it in
            # order but doesn't merge it into the surrounding tool runs.
            ranges.append((i, i + 1))
            i += 1
            continue
        # Extend while the next turn is also a tool-carrying turn.
        j = i + 1
        while j < end and _message_has_tool_use(transcript[j]):
            j += 1
        ranges.append((i, j))
        i = j
    return ranges


# ---------------------------------------------------------------------------
# choose_strategy
# ---------------------------------------------------------------------------


def choose_strategy(
    transcript_slice: Sequence[object],
    *,
    big_blob_bytes: int = BIG_BLOB_BYTES,
) -> str:
    """Return ``"extractive"`` if any single tool_result exceeds the
    big-blob threshold, else ``"abstractive"``.

    The comparison is strict ``>`` — a result of exactly
    ``big_blob_bytes`` stays on the abstractive path. This matches the
    ``should_compact`` threshold convention in
    :mod:`cli.llm.compaction`.
    """
    for message in transcript_slice:
        for block in _content_blocks(message):
            if _block_type(block) != "tool_result":
                continue
            body = _block_content(block)
            if len(body.encode("utf-8")) > big_blob_bytes:
                return "extractive"
    return "abstractive"


# ---------------------------------------------------------------------------
# Extractive renderer
# ---------------------------------------------------------------------------


def _trim_body(body: str) -> str:
    """Apply the first-20 / last-20 rule with an omission marker.

    Bodies of 40 lines or fewer pass through unchanged — the head/tail
    slice would overlap and produce a confusing duplicate if we
    applied it unconditionally.
    """
    lines = body.splitlines()
    total = len(lines)
    if total <= _EXTRACTIVE_HEAD_LINES + _EXTRACTIVE_TAIL_LINES:
        return body
    omitted = total - _EXTRACTIVE_HEAD_LINES - _EXTRACTIVE_TAIL_LINES
    head = lines[:_EXTRACTIVE_HEAD_LINES]
    tail = lines[-_EXTRACTIVE_TAIL_LINES:]
    return "\n".join(
        head + [f"... <{omitted} lines omitted> ..."] + tail
    )


def _extractive_summary(transcript_slice: Sequence[object]) -> tuple[str, tuple[str, ...]]:
    """Return ``(summary_text, tool_names)`` for the extractive branch.

    Walks each tool_use and tool_result block in order, preserving
    tool names and trimming any oversized body via :func:`_trim_body`.
    Tool_use and tool_result blocks are paired by their position in
    the stream, not by id — pairing-by-id is correct for the adapter
    layer but the digest only needs positional ordering.
    """
    names: list[str] = []
    chunks: list[str] = []
    for message in transcript_slice:
        for block in _content_blocks(message):
            btype = _block_type(block)
            if btype == "tool_use":
                name = _block_name(block) or "<unknown>"
                names.append(name)
                chunks.append(f"- `{name}` (tool_use)")
            elif btype == "tool_result":
                body = _block_content(block)
                # is_error flag lives on the dict shape only
                is_error = False
                if isinstance(block, dict):
                    is_error = bool(block.get("is_error", False))
                status = "error" if is_error else "ok"
                size = len(body.encode("utf-8"))
                trimmed = _trim_body(body)
                chunks.append(
                    f"- tool_result ({size}B, {status}):\n{trimmed}"
                )
    if not chunks:
        summary = "(no tool activity)"
    else:
        summary = "Tool phase summary (extractive):\n" + "\n".join(chunks)
    return summary, tuple(names)


# ---------------------------------------------------------------------------
# Abstractive renderer
# ---------------------------------------------------------------------------


_ABSTRACTIVE_PROMPT_TEMPLATE = (
    "You are compacting a transcript for a coding-agent session. "
    "Below is a contiguous phase of {n} tool calls and their results. "
    "Summarise what the tools did and what was learned, in at most "
    "{max_tokens} tokens. Be concrete — name files, symbols, and "
    "outcomes. Do not include large verbatim blobs. Do not wrap your "
    "response in markdown fences.\n\n"
    "--- tool phase ---\n{body}\n--- end tool phase ---"
)


def _render_phase_for_prompt(transcript_slice: Sequence[object]) -> tuple[str, int]:
    """Flatten the phase into a prompt-friendly body. Returns ``(body, n_calls)``."""
    lines: list[str] = []
    n_calls = 0
    for message in transcript_slice:
        for block in _content_blocks(message):
            btype = _block_type(block)
            if btype == "tool_use":
                n_calls += 1
                name = _block_name(block) or "<unknown>"
                lines.append(f"[call {n_calls}] {name}")
            elif btype == "tool_result":
                body = _block_content(block)
                trimmed = _trim_body(body)
                lines.append(f"[result {n_calls}]\n{trimmed}")
    return "\n".join(lines), n_calls


def _abstractive_summary(
    transcript_slice: Sequence[object],
    model_factory: Callable[[], object],
) -> str | None:
    """Call the forked model once. Return the summary text or ``None``.

    ``None`` on any failure — missing factory, client raise, empty
    completion. The caller falls back to extractive so the compaction
    step never hard-errors on a transient model issue.
    """
    body, n_calls = _render_phase_for_prompt(transcript_slice)
    prompt = _ABSTRACTIVE_PROMPT_TEMPLATE.format(
        n=n_calls, max_tokens=_ABSTRACTIVE_MAX_TOKENS, body=body
    )

    try:
        client = model_factory()
    except Exception:  # noqa: BLE001 — factory errors should fall back, not crash
        logger.exception("digest model_factory() raised; falling back to extractive")
        return None

    try:
        # Import lazily so tests with no client never need TurnMessage
        # in the ``model_factory=None`` path. This keeps the module
        # load-time import graph minimal.
        from cli.llm.types import TurnMessage

        response = client.complete(  # type: ignore[attr-defined]
            system_prompt="You are a helpful summarisation assistant.",
            messages=[TurnMessage(role="user", content=prompt)],
            tools=[],
        )
    except Exception:  # noqa: BLE001
        logger.exception("digest model client.complete() raised; falling back to extractive")
        return None

    text = _extract_response_text(response)
    if not text.strip():
        logger.warning("digest model returned empty completion; falling back to extractive")
        return None
    return text.strip()


def _extract_response_text(response: object) -> str:
    """Pull text out of a :class:`ModelResponse`-shaped object.

    We don't import :class:`ModelResponse` here; duck-typing keeps the
    tests' fake clients trivial. The response can expose either:

    * ``text_blocks()`` returning objects with a ``.text`` attribute
      (the real adapter shape), or
    * a ``.text`` attribute directly (the test-fake shape), or
    * a plain string (even simpler test fake).
    """
    if isinstance(response, str):
        return response
    text_blocks = getattr(response, "text_blocks", None)
    if callable(text_blocks):
        try:
            blocks = text_blocks()
        except Exception:  # noqa: BLE001
            blocks = []
        parts = [str(getattr(b, "text", "")) for b in blocks]
        joined = "".join(parts)
        if joined:
            return joined
    direct = getattr(response, "text", None)
    if isinstance(direct, str):
        return direct
    return ""


# ---------------------------------------------------------------------------
# digest_tool_phase
# ---------------------------------------------------------------------------


def digest_tool_phase(
    transcript: Sequence[object],
    start: int,
    end: int,
    *,
    model_factory: Callable[[], object] | None = None,
    big_blob_bytes: int = BIG_BLOB_BYTES,
) -> ToolUseSummaryMessage:
    """Digest ``transcript[start:end]`` into a single summary message.

    Strategy is chosen by :func:`choose_strategy`. When the choice is
    ``"abstractive"`` but ``model_factory`` is ``None`` (or the model
    call fails), we log and transparently fall back to extractive.

    The caller owns replacing ``transcript[start:end]`` with the
    returned summary — this function is pure on the input slice.
    """
    phase = list(transcript[start:end])
    total_bytes_in = sum(_bytes_of(m) for m in phase)

    strategy = choose_strategy(phase, big_blob_bytes=big_blob_bytes)

    if strategy == "abstractive":
        if model_factory is None:
            logger.warning(
                "digest_tool_phase: abstractive branch requested but "
                "model_factory is None; falling back to extractive"
            )
            strategy = "extractive"
        else:
            abstract_text = _abstractive_summary(phase, model_factory)
            if abstract_text is None:
                strategy = "extractive"
            else:
                # Pull tool names in order for the message metadata;
                # abstractive summary body comes from the model.
                _, names = _extractive_summary(phase)
                out_bytes = len(abstract_text.encode("utf-8"))
                return ToolUseSummaryMessage(
                    tool_names=names,
                    strategy="abstractive",
                    summary=abstract_text,
                    original_turn_count=len(phase),
                    total_bytes_in=total_bytes_in,
                    total_bytes_out=out_bytes,
                )

    # Extractive branch (chosen or fallen-back-to).
    summary, names = _extractive_summary(phase)
    out_bytes = len(summary.encode("utf-8"))
    return ToolUseSummaryMessage(
        tool_names=names,
        strategy="extractive",
        summary=summary,
        original_turn_count=len(phase),
        total_bytes_in=total_bytes_in,
        total_bytes_out=out_bytes,
    )


__all__ = [
    "BIG_BLOB_BYTES",
    "ToolUseSummaryMessage",
    "choose_strategy",
    "digest_tool_phase",
    "group_tool_phase",
]
