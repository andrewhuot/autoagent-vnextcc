"""Tests for evals.dataset.balance — histogram + rebalance recommendations.

Slice B.4 of the R5 eval corpus plan.
"""

from __future__ import annotations

import pytest

from evals.runner import TestCase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _case(
    id: str,
    *,
    category: str = "support",
    tags: list[str] | None = None,
) -> TestCase:
    return TestCase(
        id=id,
        category=category,
        user_message=f"msg for {id}",
        expected_specialist="support",
        expected_behavior="answer",
        tags=tags or [],
    )


# ---------------------------------------------------------------------------
# histogram()
# ---------------------------------------------------------------------------


def test_histogram_default_by_category():
    from evals.dataset.balance import histogram

    cases = [
        _case("c1", category="a"),
        _case("c2", category="a"),
        _case("c3", category="a"),
        _case("c4", category="b"),
        _case("c5", category="b"),
    ]
    assert histogram(cases) == {"a": 3, "b": 2}


def test_histogram_by_tag_counts_multi_tag_cases():
    from evals.dataset.balance import histogram

    cases = [
        _case("c1", tags=["a", "b"]),
        _case("c2", tags=["a"]),
        _case("c3", tags=["c"]),
    ]
    hist = histogram(cases, by="tag")
    assert hist == {"a": 2, "b": 1, "c": 1}
    # Sum > len(cases) because c1 contributes to two buckets.
    assert sum(hist.values()) > len(cases)


def test_histogram_empty_list():
    from evals.dataset.balance import histogram

    assert histogram([]) == {}
    assert histogram([], by="tag") == {}


def test_histogram_invalid_by_raises():
    from evals.dataset.balance import histogram

    with pytest.raises(ValueError):
        histogram([_case("c1")], by="foo")


# ---------------------------------------------------------------------------
# recommendations()
# ---------------------------------------------------------------------------


def test_recommendations_below_median():
    from evals.dataset.balance import recommendations

    recs = recommendations({"a": 10, "b": 5})
    # median of [5, 10] with N=2 → counts[N//2] = counts[1] = 10
    # so 'b' is below median, 'a' is at median (omitted).
    assert len(recs) == 1
    assert "Add 5" in recs[0]
    assert "'b'" in recs[0]
    assert "currently 5" in recs[0]


def test_recommendations_above_median():
    from evals.dataset.balance import recommendations

    recs = recommendations({"a": 10, "b": 20, "c": 10})
    # counts sorted ascending: [10, 10, 20]; N//2 = 1 → median = 10.
    # 'b' is above median.
    above = [r for r in recs if "'b'" in r]
    assert len(above) == 1
    assert "20" in above[0]
    assert "median is 10" in above[0]
    assert "trimming" in above[0] or "downsampling" in above[0]


def test_recommendations_at_median_omits_bucket():
    from evals.dataset.balance import recommendations

    recs = recommendations({"a": 10, "b": 10, "c": 10})
    # Every bucket at median → no recommendations.
    assert recs == []


def test_recommendations_sorted_alphabetically():
    from evals.dataset.balance import recommendations

    # Build an uneven histogram with several buckets to verify stable ordering.
    hist = {"zeta": 5, "alpha": 20, "mu": 5, "beta": 20}
    recs = recommendations(hist)
    # Extract the bucket name referenced in each rec line (quoted).
    import re
    mentioned = [re.search(r"'([^']+)'", r).group(1) for r in recs]
    assert mentioned == sorted(mentioned)


def test_recommendations_empty_hist():
    from evals.dataset.balance import recommendations

    assert recommendations({}) == []


def test_recommendations_never_add_or_trim_zero():
    from evals.dataset.balance import recommendations

    # At-median buckets must be omitted entirely — no "add 0" / "trim 0" lines.
    recs = recommendations({"a": 5, "b": 5, "c": 10})
    # median = counts[3//2] = counts[1] = 5. 'c' above, a/b at median.
    for r in recs:
        assert "add 0" not in r.lower()
        assert "trim 0" not in r.lower()


# ---------------------------------------------------------------------------
# balance() — convenience wrapper
# ---------------------------------------------------------------------------


def test_balance_integrates_both():
    from evals.dataset.balance import balance, histogram, recommendations

    cases = [
        _case("c1", category="a"),
        _case("c2", category="a"),
        _case("c3", category="b"),
    ]
    report = balance(cases)
    assert report.by == "category"
    assert report.histogram == histogram(cases)
    assert report.recommendations == recommendations(report.histogram)


def test_balance_does_not_mutate_input():
    from evals.dataset.balance import balance

    cases = [
        _case("c1", category="a", tags=["x", "y"]),
        _case("c2", category="b", tags=["x"]),
    ]
    original_len = len(cases)
    first = cases[0]
    balance(cases, by="tag")
    balance(cases, by="category")
    assert len(cases) == original_len
    assert cases[0] is first
    # Ensure tags list itself not mutated.
    assert cases[0].tags == ["x", "y"]


def test_balance_by_tag_report_fields():
    from evals.dataset.balance import balance

    cases = [
        _case("c1", tags=["a", "b"]),
        _case("c2", tags=["a"]),
    ]
    report = balance(cases, by="tag")
    assert report.by == "tag"
    assert report.histogram == {"a": 2, "b": 1}


# ---------------------------------------------------------------------------
# Median semantics
# ---------------------------------------------------------------------------


def test_median_upper_for_even_count():
    from evals.dataset.balance import balance

    # 4 buckets: counts sorted ascending → [1, 2, 3, 4]; N//2 = 2 → median 3.
    cases = (
        [_case(f"a{i}", category="a") for i in range(1)]
        + [_case(f"b{i}", category="b") for i in range(2)]
        + [_case(f"c{i}", category="c") for i in range(3)]
        + [_case(f"d{i}", category="d") for i in range(4)]
    )
    report = balance(cases)
    assert report.median == 3


def test_median_of_empty_histogram_is_zero():
    from evals.dataset.balance import balance

    report = balance([])
    assert report.median == 0
    assert report.histogram == {}
    assert report.recommendations == []
