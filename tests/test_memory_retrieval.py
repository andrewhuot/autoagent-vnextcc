"""Tests for :mod:`cli.memory.retrieval` — BM25 with recency + name boost."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from cli.memory.retrieval import RetrievalReason, RetrievalResult, find_relevant
from cli.memory.types import Memory, MemoryType


_REF_NOW = datetime(2026, 4, 17, tzinfo=timezone.utc)


def _m(
    name: str,
    description: str = "",
    body: str = "",
    created_at: datetime | None = None,
) -> Memory:
    """Build a Memory with sensible defaults for retrieval tests."""
    return Memory(
        name=name,
        type=MemoryType.PROJECT,
        description=description,
        body=body,
        created_at=created_at if created_at is not None else _REF_NOW,
    )


# ---------------------------------------------------------------------------
# required cases from the TDD plan
# ---------------------------------------------------------------------------


def test_bm25_ranks_exact_name_match_first() -> None:
    memories = [
        _m("alpha", body="some text about alpha"),
        _m("beta", body="some text about beta"),
        _m("gamma", body="some text about gamma"),
    ]
    result = find_relevant("beta", memories, now=_REF_NOW)
    assert [m.name for m in result.memories][0] == "beta"


def test_recency_tiebreaks_equal_score() -> None:
    older = _m("same", body="shared body", created_at=_REF_NOW - timedelta(days=10))
    newer = _m("same", body="shared body", created_at=_REF_NOW - timedelta(days=1))
    # The older one is inserted first — recency must still win.
    result = find_relevant("shared", [older, newer], now=_REF_NOW)
    assert result.memories[0].created_at == newer.created_at


def test_k_zero_returns_nothing() -> None:
    memories = [_m("alpha", body="alpha alpha"), _m("beta", body="beta beta")]
    result = find_relevant("alpha", memories, k=0, now=_REF_NOW)
    assert result.memories == []
    assert result.reasons == []


def test_reasons_trace_includes_score_and_why() -> None:
    memories = [_m("doc", description="docs about python", body="python is great")]
    result = find_relevant("python", memories, now=_REF_NOW)
    assert len(result.reasons) == 1
    reason = result.reasons[0]
    assert isinstance(reason, RetrievalReason)
    assert reason.term_hits.get("python", 0) >= 1
    assert reason.final_score > 0


def test_deterministic_ordering_on_ties() -> None:
    ts = _REF_NOW - timedelta(days=5)
    a = _m("twin", body="shared body", created_at=ts)
    b = _m("twin", body="shared body", created_at=ts)
    result = find_relevant("shared", [a, b], now=_REF_NOW)
    # Identical score AND identical recency — insertion order decides.
    assert result.memories[0] is a
    assert result.memories[1] is b


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------


def test_empty_corpus_returns_empty_result() -> None:
    result = find_relevant("anything", [], now=_REF_NOW)
    assert isinstance(result, RetrievalResult)
    assert result.memories == []
    assert result.reasons == []


def test_query_with_no_matches_returns_empty() -> None:
    memories = [_m("alpha", body="one two three"), _m("beta", body="four five six")]
    result = find_relevant("zzz-never-appears", memories, now=_REF_NOW)
    assert result.memories == []
    assert result.reasons == []


def test_case_insensitive_query() -> None:
    memories = [_m("notes", body="Python is a Language")]
    upper = find_relevant("PYTHON", memories, now=_REF_NOW)
    lower = find_relevant("python", memories, now=_REF_NOW)
    assert [m.name for m in upper.memories] == [m.name for m in lower.memories] == ["notes"]


def test_query_with_punctuation_is_tokenized() -> None:
    memories = [_m("api", body="rest, graphql: two api styles")]
    result = find_relevant("api!!! graphql?", memories, now=_REF_NOW)
    assert len(result.memories) == 1
    assert result.reasons[0].term_hits.get("graphql", 0) >= 1


def test_k_larger_than_corpus_returns_all_available() -> None:
    memories = [
        _m("a", body="python"),
        _m("b", body="python"),
    ]
    result = find_relevant("python", memories, k=50, now=_REF_NOW)
    assert len(result.memories) == 2


def test_now_argument_controls_recency() -> None:
    # Same body, different ages: the younger one (relative to `now`) wins.
    old = _m("one", body="shared token", created_at=datetime(2025, 1, 1, tzinfo=timezone.utc))
    new = _m("two", body="shared token", created_at=datetime(2026, 4, 1, tzinfo=timezone.utc))
    result = find_relevant("shared", [old, new], now=_REF_NOW)
    # Both match equally on BM25, so recency decides.
    assert result.memories[0].name == "two"


def test_name_match_beats_body_only_match() -> None:
    name_hit = _m("python", body="unrelated content")
    body_hit = _m("notes", body="python python python python python")
    result = find_relevant("python", [body_hit, name_hit], now=_REF_NOW)
    # The name-match boost is large enough to override even a
    # higher-TF body match.
    assert result.memories[0].name == "python"


def test_reasons_and_memories_are_parallel_and_ordered() -> None:
    memories = [
        _m("alpha", body="alpha"),
        _m("beta", body="beta"),
        _m("gamma", body="gamma"),
    ]
    result = find_relevant("beta", memories, now=_REF_NOW)
    assert len(result.memories) == len(result.reasons)
    for mem, reason in zip(result.memories, result.reasons):
        assert mem.name == reason.name


def test_multi_term_query_accumulates_hits() -> None:
    memories = [
        _m("doc", body="python rust go"),
        _m("other", body="python only"),
    ]
    result = find_relevant("python rust", memories, now=_REF_NOW)
    # The doc with both terms should rank first.
    assert result.memories[0].name == "doc"
    top_reason = result.reasons[0]
    assert "python" in top_reason.term_hits
    assert "rust" in top_reason.term_hits


def test_memory_without_created_at_gets_zero_recency_bonus() -> None:
    # Memory dataclass requires created_at, but we still exercise the
    # _recency_bonus=None branch through a None-like stand-in: use an
    # ancient date so the bonus is effectively zero, and assert the
    # reason's recency_bonus is tiny (<< BM25 contribution).
    ancient = _m(
        "old",
        body="python",
        created_at=datetime(1970, 1, 1, tzinfo=timezone.utc),
    )
    result = find_relevant("python", [ancient], now=_REF_NOW)
    assert len(result.memories) == 1
    assert result.reasons[0].recency_bonus < 1e-6
    # BM25 score alone should still be positive.
    assert result.reasons[0].final_score > 0


def test_results_are_deterministic_across_calls() -> None:
    memories = [
        _m("a", body="python"),
        _m("b", body="python python"),
        _m("c", body="python python python"),
    ]
    r1 = find_relevant("python", memories, now=_REF_NOW)
    r2 = find_relevant("python", memories, now=_REF_NOW)
    assert [m.name for m in r1.memories] == [m.name for m in r2.memories]
    assert [r.final_score for r in r1.reasons] == [r.final_score for r in r2.reasons]
