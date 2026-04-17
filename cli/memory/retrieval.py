"""BM25 memory retrieval — pure, deterministic, no I/O.

Ranks :class:`cli.memory.types.Memory` entries against a query using
classical BM25 over ``name + description + body``. Score is augmented by
a tiny recency bonus (so identical BM25 scores tiebreak on freshness)
and a large name-match boost (so an exact query hit in the memory's
name always beats a body-only match).

Everything in this module is a pure function — no filesystem, no clock
reads except through the caller-supplied ``now`` (which defaults to
``datetime.now(timezone.utc)`` when omitted).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from .types import Memory


_TOKEN_RE = re.compile(r"[a-z0-9]+")

# BM25 tuning
_K1 = 1.5
_B = 0.75

# Score components
_RECENCY_WEIGHT = 0.01
_RECENCY_HALFLIFE_DAYS = 30.0
_NAME_MATCH_BOOST = 1.0


@dataclass(frozen=True)
class RetrievalReason:
    """Why a given memory appeared in the results."""

    name: str
    term_hits: dict[str, int]
    recency_bonus: float
    final_score: float


@dataclass(frozen=True)
class RetrievalResult:
    """Top-k memories plus a parallel list of reasons."""

    memories: list[Memory]
    reasons: list[RetrievalReason]


def _tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alphanumeric, drop empties."""
    return _TOKEN_RE.findall(text.lower())


def _searchable(memory: Memory) -> str:
    return f"{memory.name} {memory.description} {memory.body}"


def _recency_bonus(created_at: datetime | None, now: datetime) -> float:
    if created_at is None:
        return 0.0
    age_days = (now - created_at).total_seconds() / 86400.0
    if age_days < 0:
        age_days = 0.0
    return _RECENCY_WEIGHT * math.exp(-age_days / _RECENCY_HALFLIFE_DAYS)


def find_relevant(
    query: str,
    memories: list[Memory],
    *,
    k: int = 5,
    now: datetime | None = None,
) -> RetrievalResult:
    """BM25 over name + description + body; recency tiebreak; deterministic.

    Args:
        query: Free-text query. Tokenized the same way as memories.
        memories: Corpus to rank. Original order is preserved for stable
            tiebreaks.
        k: Maximum number of results to return. ``k=0`` short-circuits
            and returns an empty result.
        now: Clock for the recency bonus. Defaults to
            ``datetime.now(timezone.utc)`` if omitted.

    Returns:
        A :class:`RetrievalResult` with up to ``k`` memories sorted by
        final score (descending). Memories with a zero score are
        dropped. If every memory scores zero, an empty result is
        returned rather than arbitrary picks.
    """
    if k <= 0 or not memories:
        return RetrievalResult(memories=[], reasons=[])

    if now is None:
        now = datetime.now(timezone.utc)

    query_lower = query.lower()
    query_terms = _tokenize(query)

    # Tokenize corpus up-front so we only do it once.
    doc_tokens: list[list[str]] = [_tokenize(_searchable(m)) for m in memories]
    doc_lens = [len(toks) for toks in doc_tokens]
    n_docs = len(memories)
    avgdl = (sum(doc_lens) / n_docs) if n_docs else 0.0

    # Document frequency for each query term (de-duped across the query
    # so repeated terms don't double-count IDF).
    unique_terms = list(dict.fromkeys(query_terms))
    df: dict[str, int] = {}
    for term in unique_terms:
        df[term] = sum(1 for toks in doc_tokens if term in toks)

    scored: list[tuple[float, int, Memory, RetrievalReason]] = []
    for idx, memory in enumerate(memories):
        toks = doc_tokens[idx]
        dl = doc_lens[idx]
        # Count hits for every query term (including repeats mapped to
        # the same key — repeated terms just look up the same count).
        term_hits: dict[str, int] = {}
        bm25 = 0.0
        for term in unique_terms:
            tf = toks.count(term)
            if tf == 0:
                continue
            term_hits[term] = tf
            n = df[term]
            idf = math.log((n_docs - n + 0.5) / (n + 0.5) + 1.0)
            denom = tf + _K1 * (1.0 - _B + _B * (dl / avgdl if avgdl else 0.0))
            bm25 += idf * (tf * (_K1 + 1.0)) / denom if denom else 0.0

        name_boost = 0.0
        if query_lower and query_lower in memory.name.lower():
            name_boost = _NAME_MATCH_BOOST

        # A memory with no term hits and no name boost is a pure miss:
        # the recency bonus alone must not surface it, otherwise any
        # query — including nonsense — would return the newest memories.
        if bm25 <= 0.0 and name_boost <= 0.0:
            continue

        recency = _recency_bonus(memory.created_at, now)
        final = bm25 + recency + name_boost

        reason = RetrievalReason(
            name=memory.name,
            term_hits=term_hits,
            recency_bonus=recency,
            final_score=final,
        )
        scored.append((final, idx, memory, reason))

    # Sort: score desc, then newer created_at wins, then original index
    # (stable insertion order).
    def _sort_key(item: tuple[float, int, Memory, RetrievalReason]) -> tuple:
        final, idx, memory, _ = item
        ts = memory.created_at.timestamp() if memory.created_at is not None else float("-inf")
        return (-final, -ts, idx)

    scored.sort(key=_sort_key)
    top = scored[:k]

    return RetrievalResult(
        memories=[m for _, _, m, _ in top],
        reasons=[r for _, _, _, r in top],
    )
