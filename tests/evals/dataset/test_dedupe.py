"""Tests for evals.dataset.dedupe — cosine-similarity near-duplicate removal.

Slice B.2 of the R5 eval corpus plan.
"""

from __future__ import annotations

import math

import pytest

from evals.runner import TestCase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _case(
    id: str,
    user_message: str = "",
    reference_answer: str = "",
    *,
    category: str = "support",
    expected_specialist: str = "support",
    expected_behavior: str = "answer",
) -> TestCase:
    return TestCase(
        id=id,
        category=category,
        user_message=user_message,
        expected_specialist=expected_specialist,
        expected_behavior=expected_behavior,
        reference_answer=reference_answer,
    )


class _SpyEmbedder:
    """Wraps an inner embedder and counts ``embed`` calls."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.calls = 0

    @property
    def model_name(self) -> str:
        return self.inner.model_name

    def embed(self, texts):
        self.calls += 1
        return self.inner.embed(texts)


class _StubEmbedder:
    """Hand-crafted vectors keyed by text. Lets tests control similarities exactly."""

    model_name = "stub"

    def __init__(self, vectors_by_text: dict[str, list[float]]) -> None:
        self._by_text = vectors_by_text

    def embed(self, texts):
        return [list(self._by_text[t]) for t in texts]


# ---------------------------------------------------------------------------
# B.2 tests
# ---------------------------------------------------------------------------


def test_dedupe_empty_returns_empty():
    from evals.dataset.dedupe import dedupe
    from evals.dataset.embedder import FakeEmbedder

    report = dedupe([], FakeEmbedder())
    assert report.kept == []
    assert report.dropped_ids == []
    assert report.dropped_pairs == []


def test_dedupe_identical_texts_removed():
    from evals.dataset.dedupe import dedupe
    from evals.dataset.embedder import FakeEmbedder

    cases = [
        _case("a", user_message="hello world"),
        _case("b", user_message="hello world"),
        _case("c", user_message="hello world"),
    ]
    report = dedupe(cases, FakeEmbedder())
    assert len(report.kept) == 1
    assert len(report.dropped_ids) == 2
    assert len(report.kept) + len(report.dropped_ids) == len(cases)


def test_dedupe_below_threshold_all_kept():
    from evals.dataset.dedupe import dedupe
    from evals.dataset.embedder import FakeEmbedder

    cases = [
        _case("a", user_message="alpha beta gamma"),
        _case("b", user_message="refund broken widget please help"),
        _case("c", user_message="how do I reset my password"),
        _case("d", user_message="my invoice seems wrong"),
    ]
    report = dedupe(cases, FakeEmbedder(), threshold=0.999)
    assert len(report.kept) == 4
    assert report.dropped_ids == []
    assert report.dropped_pairs == []


def test_dedupe_keeps_longer_reference_answer():
    from evals.dataset.dedupe import dedupe
    from evals.dataset.embedder import FakeEmbedder

    cases = [
        _case("a", user_message="same text", reference_answer="short"),
        _case("b", user_message="same text", reference_answer="a much longer reference answer"),
    ]
    report = dedupe(cases, FakeEmbedder())
    assert [c.id for c in report.kept] == ["b"]
    assert report.dropped_ids == ["a"]


def test_dedupe_tie_breaks_lexicographic_id():
    from evals.dataset.dedupe import dedupe
    from evals.dataset.embedder import FakeEmbedder

    # Equal-length reference_answer → lex id tiebreak.
    cases = [
        _case("b_id", user_message="tie text", reference_answer="ref"),
        _case("a_id", user_message="tie text", reference_answer="ref"),
    ]
    report = dedupe(cases, FakeEmbedder())
    assert [c.id for c in report.kept] == ["a_id"]
    assert report.dropped_ids == ["b_id"]


def test_dedupe_preserves_input_order():
    from evals.dataset.dedupe import dedupe
    from evals.dataset.embedder import FakeEmbedder

    cases = [
        _case("z", user_message="dup text", reference_answer="longer keeper"),
        _case("y", user_message="unique one about refunds"),
        _case("x", user_message="dup text", reference_answer="short"),
        _case("w", user_message="unique two about passwords"),
    ]
    report = dedupe(cases, FakeEmbedder())
    kept_ids = [c.id for c in report.kept]
    # z is the keeper (longer reference_answer); x is dropped.
    # Original order: z, y, x, w → kept = z, y, w.
    assert kept_ids == ["z", "y", "w"]


def test_dedupe_calls_embed_once():
    from evals.dataset.dedupe import dedupe
    from evals.dataset.embedder import FakeEmbedder

    cases = [_case(f"c{i}", user_message=f"msg {i}") for i in range(50)]
    spy = _SpyEmbedder(FakeEmbedder())
    dedupe(cases, spy)
    assert spy.calls == 1


def test_dedupe_dropped_pairs_shape():
    from evals.dataset.dedupe import dedupe
    from evals.dataset.embedder import FakeEmbedder

    cases = [
        _case("a", user_message="same"),
        _case("b", user_message="same"),
        _case("c", user_message="same"),
    ]
    report = dedupe(cases, FakeEmbedder())
    kept_ids = {c.id for c in report.kept}
    dropped_ids = set(report.dropped_ids)
    assert kept_ids & dropped_ids == set()
    for kept, dropped, sim in report.dropped_pairs:
        assert kept in kept_ids
        assert dropped in dropped_ids
        assert 0.0 <= sim <= 1.0 + 1e-9


def test_dedupe_transitive_component():
    from evals.dataset.dedupe import dedupe

    # Build three vectors so that A~B (sim=1.0 exactly), B~C (sim=1.0),
    # but A~C below threshold. Using 3D unit vectors:
    # A=(1,0,0); B=(0.97,0.242,0) cos(A,B)=0.97
    # C=(0.8,0.6,0): cos(B,C)=0.97*0.8+0.242*0.6=0.776+0.145=0.921
    # cos(A,C)=0.8  < 0.9 threshold
    # Recompute: use threshold=0.9 so A~B(0.97) and B~C(0.921) are edges but A~C(0.8) isn't.
    vectors = {
        "txt_a": [1.0, 0.0, 0.0],
        "txt_b": [0.97, 0.2431, 0.0],  # nearly A
        "txt_c": [0.8, 0.6, 0.0],
    }
    # Normalize just to make sure.
    def _norm(v):
        n = math.sqrt(sum(x * x for x in v))
        return [x / n for x in v]

    vectors = {k: _norm(v) for k, v in vectors.items()}

    # Verify the setup matches our assumption.
    def dot(u, v):
        return sum(a * b for a, b in zip(u, v))

    assert dot(vectors["txt_a"], vectors["txt_b"]) > 0.9
    assert dot(vectors["txt_b"], vectors["txt_c"]) > 0.9
    assert dot(vectors["txt_a"], vectors["txt_c"]) < 0.9

    cases = [
        _case("a", user_message="txt_a", reference_answer="short"),
        _case("b", user_message="txt_b", reference_answer="mid ref"),
        _case("c", user_message="txt_c", reference_answer="longest ref answer here"),
    ]
    stub = _StubEmbedder(vectors)
    report = dedupe(cases, stub, threshold=0.9)
    # Transitive component {a, b, c}; keeper = longest ref = "c".
    assert [kc.id for kc in report.kept] == ["c"]
    assert set(report.dropped_ids) == {"a", "b"}


def test_dedupe_caps_at_2000():
    from evals.dataset.dedupe import dedupe
    from evals.dataset.embedder import FakeEmbedder

    cases = [_case(f"c{i}", user_message=f"m{i}") for i in range(2001)]
    with pytest.raises(ValueError) as exc_info:
        dedupe(cases, FakeEmbedder())
    msg = str(exc_info.value)
    assert "2000" in msg
    assert "2001" in msg


def test_dedupe_custom_text_fn():
    from evals.dataset.dedupe import dedupe
    from evals.dataset.embedder import FakeEmbedder

    cases = [
        _case("a", user_message="different msg 1", reference_answer="identical reference"),
        _case("b", user_message="different msg 2", reference_answer="identical reference"),
    ]
    report = dedupe(cases, FakeEmbedder(), text_fn=lambda c: c.reference_answer)
    assert len(report.kept) == 1
    assert len(report.dropped_ids) == 1
