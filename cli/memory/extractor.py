"""Pure memory extractor.

Given a conversation turn, call a cheap model via the :class:`ModelClient`
protocol and produce a list of :class:`Memory` candidates. The extractor
does **not** write to disk — it returns an :class:`ExtractionResult` so
callers (the orchestrator's background-dispatch wrapper, arriving in
P2.orch) can decide whether and when to persist.

Design choices
--------------

* Provider-neutral prompt. We build one prompt and branch only on how
  we ask the adapter to enforce JSON: ``json_mode=True`` providers
  (OpenAI, Gemini) receive ``response_format={"type": "json_object"}``
  as a kwarg; ``json_mode=False`` providers (Anthropic today) get the
  same prompt without the hint and we parse best-effort.
* Never raises. Model errors, invalid JSON, empty response, and
  per-memory schema violations all surface as a ``warnings`` tuple in
  the result.
* Dedup uses a local character-trigram Jaccard — no embedding model
  required. Exact ``name`` collision is checked first (cheap + common).
* Caps are enforced in this order: schema-validate → dedup → per-turn
  cap → per-session cap. Counts are tracked separately so callers can
  tell why memories were dropped.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

from cli.memory.types import Memory, MemoryType

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Public constants                                                            #
# --------------------------------------------------------------------------- #

MAX_MEMORIES_PER_TURN = 3
MAX_MEMORIES_PER_SESSION = 5

# Jaccard-over-trigrams threshold at which we treat two descriptions as
# saying the same thing. Chosen empirically so "project uses postgres"
# and "the project uses PostgreSQL" dedup (~0.92) while "uses postgres"
# and "uses redis" do not (~0.33). See tests for pinned cases.
DEDUP_DESCRIPTION_SIMILARITY = 0.9

# Schema bounds — mirror the prompt.
_MAX_NAME_LEN = 60
_MAX_DESCRIPTION_LEN = 100
_MAX_BODY_LEN = 500

# Name slug regex: lowercase letters / digits / underscores. Matches the
# frontmatter-friendly subset allowed by the store's _validate_name, but
# tighter — we don't want the extractor proposing awkward identifiers.
_NAME_SLUG_RE = re.compile(r"^[a-z0-9_]+$")

_VALID_TYPES = {t.value for t in MemoryType}


# --------------------------------------------------------------------------- #
# Result                                                                      #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ExtractionResult:
    """Outcome of one extractor call.

    Attributes:
        memories: Newly extracted memories, in model-emitted order, after
            schema validation, dedup, and cap enforcement.
        dropped_cap: Count of memories discarded because a per-turn or
            per-session cap was reached.
        dropped_dup: Count discarded as duplicates of ``existing_memories``.
        warnings: Human-readable diagnostics — schema violations, parse
            errors, model failures. Never raises; everything actionable
            surfaces here.
    """

    memories: tuple[Memory, ...]
    dropped_cap: int
    dropped_dup: int
    warnings: tuple[str, ...]


# --------------------------------------------------------------------------- #
# Prompt                                                                      #
# --------------------------------------------------------------------------- #


def _build_prompt(turn_text: str, max_per_turn: int) -> str:
    return (
        "You are extracting durable memories from the following "
        "conversation turn.\n"
        "A memory is a fact, preference, or observation that should be "
        "remembered across future sessions.\n\n"
        "Output STRICT JSON matching this schema:\n"
        "{\n"
        '  "memories": [\n'
        "    {\n"
        '      "name": "<slug-safe identifier, lowercase-with-underscores, '
        f'\u2264{_MAX_NAME_LEN} chars>",\n'
        '      "type": "user" | "feedback" | "project" | "reference",\n'
        '      "description": "<one-line summary, '
        f'\u2264{_MAX_DESCRIPTION_LEN} chars>",\n'
        '      "body": "<markdown body, '
        f'\u2264{_MAX_BODY_LEN} chars>"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        f"- Emit at most {max_per_turn} memories.\n"
        "- Skip if the turn contains no durable information.\n"
        "- Do NOT invent information not in the turn.\n\n"
        "Turn content:\n"
        f"{turn_text}"
    )


# --------------------------------------------------------------------------- #
# Similarity helper                                                           #
# --------------------------------------------------------------------------- #


def _trigrams(text: str) -> set[str]:
    """Character trigrams of a normalised string. Empty / short input
    yields a set containing the whole input (or empty)."""
    normalised = re.sub(r"\s+", " ", text.strip().lower())
    if len(normalised) < 3:
        return {normalised} if normalised else set()
    return {normalised[i : i + 3] for i in range(len(normalised) - 2)}


def _similarity(a: str, b: str) -> float:
    """Jaccard similarity on character 3-grams. Returns 0.0 to 1.0.

    Both inputs empty → 1.0 (identical). One empty, other non-empty → 0.0.
    """
    ta = _trigrams(a)
    tb = _trigrams(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


# --------------------------------------------------------------------------- #
# Parsing                                                                     #
# --------------------------------------------------------------------------- #


def _extract_json_object(text: str) -> str | None:
    """Return the first balanced ``{...}`` substring, or ``None``.

    Tolerant of surrounding prose (``Here's the JSON: {...}``) and of
    Markdown fencing (```json ... ```). Does not attempt to recover from
    mid-object corruption — returns the first candidate that survives
    brace-matching; caller is responsible for parsing.
    """
    # Strip common markdown code fences first.
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        return fenced.group(1)
    # Walk the string and brace-match the first top-level object.
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        start = text.find("{", start + 1)
    return None


def _response_text(response: Any) -> str:
    """Pull the first text block out of a :class:`ModelResponse`-like object.

    Accepts any object with a ``blocks`` attribute whose first element
    has a ``text`` field. Returns an empty string if the shape doesn't
    match — the caller treats that as "empty response".
    """
    blocks = getattr(response, "blocks", None)
    if not blocks:
        return ""
    first = blocks[0]
    text = getattr(first, "text", None)
    if isinstance(text, str):
        return text
    return ""


def _validate_memory_dict(
    raw: Any,
    *,
    session_id: str | None,
    now: datetime,
) -> tuple[Memory | None, str | None]:
    """Validate one memory dict. Returns (memory, warning).

    Exactly one of the two is non-None: a valid dict yields
    ``(Memory, None)``; any violation yields ``(None, reason)``.
    """
    if not isinstance(raw, dict):
        return None, f"memory entry is not an object: {type(raw).__name__}"

    for required in ("name", "type", "description", "body"):
        if required not in raw:
            return None, f"memory missing required field {required!r}"

    name = raw["name"]
    if not isinstance(name, str):
        return None, "memory name must be a string"
    if len(name) == 0:
        return None, "memory name is empty"
    if len(name) > _MAX_NAME_LEN:
        return None, f"memory name exceeds {_MAX_NAME_LEN} chars: {name!r}"
    if not _NAME_SLUG_RE.match(name):
        return None, f"memory name is not slug-safe: {name!r}"

    type_raw = raw["type"]
    if type_raw not in _VALID_TYPES:
        return None, f"memory type is invalid: {type_raw!r}"
    mem_type = MemoryType(type_raw)

    description = raw["description"]
    if not isinstance(description, str):
        return None, "memory description must be a string"
    if len(description) > _MAX_DESCRIPTION_LEN:
        return None, (
            f"memory description exceeds {_MAX_DESCRIPTION_LEN} chars: "
            f"{name!r}"
        )

    body = raw["body"]
    if not isinstance(body, str):
        return None, "memory body must be a string"
    if len(body) > _MAX_BODY_LEN:
        return None, f"memory body exceeds {_MAX_BODY_LEN} chars: {name!r}"

    return (
        Memory(
            name=name,
            type=mem_type,
            description=description,
            body=body,
            created_at=now,
            source_session_id=session_id,
        ),
        None,
    )


# --------------------------------------------------------------------------- #
# Main entry point                                                            #
# --------------------------------------------------------------------------- #


def extract_memories(
    *,
    turn_text: str,
    existing_memories: Sequence[Memory],
    model_client: Any,
    session_id: str | None = None,
    session_extraction_count: int = 0,
    max_per_turn: int = MAX_MEMORIES_PER_TURN,
    max_per_session: int = MAX_MEMORIES_PER_SESSION,
) -> ExtractionResult:
    """Run a forked cheap-model call to extract durable memories.

    Branches on ``model_client.capabilities.json_mode``:

    * ``json_mode=True`` — pass ``response_format={"type": "json_object"}``
      as an extra kwarg to ``complete()``.
    * ``json_mode=False`` — same prompt, no hint; parse best-effort.

    Dedup against ``existing_memories`` by exact ``name`` and by
    description trigram similarity (threshold
    :data:`DEDUP_DESCRIPTION_SIMILARITY`).

    Never raises. See module docstring for the full rationale.
    """
    prompt = _build_prompt(turn_text, max_per_turn)

    caps = getattr(model_client, "capabilities", None)
    use_json_mode = bool(getattr(caps, "json_mode", False))

    # Call the model. Real adapters accept (system_prompt, messages, tools);
    # the response_format kwarg is a hint they may ignore. On any exception
    # we return an empty result with a warning — the extractor is best-effort
    # and must never blow up the caller.
    call_kwargs: dict[str, Any] = {
        "system_prompt": prompt,
        "messages": [],
        "tools": [],
    }
    if use_json_mode:
        call_kwargs["response_format"] = {"type": "json_object"}

    try:
        response = model_client.complete(**call_kwargs)
    except Exception as exc:  # noqa: BLE001 — extractor must never raise
        logger.warning("extractor model call failed: %s", exc)
        return ExtractionResult(
            memories=(),
            dropped_cap=0,
            dropped_dup=0,
            warnings=(f"extractor schema violation: model call failed: {exc}",),
        )

    text = _response_text(response)
    if not text.strip():
        return ExtractionResult(
            memories=(),
            dropped_cap=0,
            dropped_dup=0,
            warnings=("extractor schema violation: empty model response",),
        )

    # Parse JSON. json_mode=True providers *should* give us pure JSON; if
    # they don't, fall through to the lenient extractor. Either way a
    # failure lands in warnings rather than raising.
    parsed: Any
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        blob = _extract_json_object(text)
        if blob is None:
            return ExtractionResult(
                memories=(),
                dropped_cap=0,
                dropped_dup=0,
                warnings=(
                    "extractor schema violation: response is not valid JSON",
                ),
            )
        try:
            parsed = json.loads(blob)
        except json.JSONDecodeError as exc:
            return ExtractionResult(
                memories=(),
                dropped_cap=0,
                dropped_dup=0,
                warnings=(
                    f"extractor schema violation: JSON parse error: {exc}",
                ),
            )

    if not isinstance(parsed, dict):
        return ExtractionResult(
            memories=(),
            dropped_cap=0,
            dropped_dup=0,
            warnings=(
                "extractor schema violation: top-level JSON is not an object",
            ),
        )

    raw_list = parsed.get("memories")
    if raw_list is None:
        return ExtractionResult(
            memories=(),
            dropped_cap=0,
            dropped_dup=0,
            warnings=(
                "extractor schema violation: missing 'memories' key",
            ),
        )
    if not isinstance(raw_list, list):
        return ExtractionResult(
            memories=(),
            dropped_cap=0,
            dropped_dup=0,
            warnings=(
                "extractor schema violation: 'memories' is not a list",
            ),
        )

    # Empty list is a legitimate "nothing durable in this turn" signal —
    # not a warning.
    if not raw_list:
        return ExtractionResult(
            memories=(), dropped_cap=0, dropped_dup=0, warnings=()
        )

    now = datetime.now(tz=timezone.utc)
    validated: list[Memory] = []
    warnings: list[str] = []
    for raw in raw_list:
        mem, warning = _validate_memory_dict(raw, session_id=session_id, now=now)
        if warning:
            warnings.append(f"extractor schema violation: {warning}")
        if mem is not None:
            validated.append(mem)

    # Dedup against existing memories. Exact-name match wins cheap; fall
    # back to description similarity. Also dedup within the batch itself
    # so the model can't smuggle two copies of the same thing past us.
    existing_names = {m.name for m in existing_memories}
    existing_descriptions = [m.description for m in existing_memories]
    kept: list[Memory] = []
    dropped_dup = 0
    for mem in validated:
        if mem.name in existing_names:
            dropped_dup += 1
            warnings.append(
                f"extractor dedup: dropped {mem.name!r} (exact name match)"
            )
            continue
        if any(
            _similarity(mem.description, d) >= DEDUP_DESCRIPTION_SIMILARITY
            for d in existing_descriptions
        ):
            dropped_dup += 1
            warnings.append(
                f"extractor dedup: dropped {mem.name!r} "
                "(description similar to existing)"
            )
            continue
        # In-batch dedup — compare against already-kept candidates.
        if mem.name in {k.name for k in kept} or any(
            _similarity(mem.description, k.description)
            >= DEDUP_DESCRIPTION_SIMILARITY
            for k in kept
        ):
            dropped_dup += 1
            warnings.append(
                f"extractor dedup: dropped {mem.name!r} (duplicate in batch)"
            )
            continue
        kept.append(mem)

    # Per-turn cap.
    dropped_cap = 0
    if len(kept) > max_per_turn:
        dropped_cap += len(kept) - max_per_turn
        kept = kept[:max_per_turn]

    # Per-session cap. Keep from the front (model emits roughly by
    # importance); surplus counts as dropped_cap.
    remaining_session_budget = max(0, max_per_session - session_extraction_count)
    if len(kept) > remaining_session_budget:
        dropped_cap += len(kept) - remaining_session_budget
        kept = kept[:remaining_session_budget]

    return ExtractionResult(
        memories=tuple(kept),
        dropped_cap=dropped_cap,
        dropped_dup=dropped_dup,
        warnings=tuple(warnings),
    )


__all__ = [
    "DEDUP_DESCRIPTION_SIMILARITY",
    "ExtractionResult",
    "MAX_MEMORIES_PER_SESSION",
    "MAX_MEMORIES_PER_TURN",
    "extract_memories",
]
