"""Category/tag histogram and rebalance recommendations for eval corpora.

Slice B.4 of the R5 eval corpus plan. Read-only analysis — functions here
never mutate their inputs. Callers decide whether to bootstrap new cases or
trim oversized buckets based on the advice returned.

Two bucket keys are supported:

- ``by="category"`` (default): disjoint. Each case contributes exactly one
  bucket (``case.category``). ``sum(histogram.values()) == len(cases)``.
- ``by="tag"``: non-disjoint. Each tag on a case produces a bucket entry,
  so a case with two tags contributes to two buckets.
  ``sum(histogram.values()) >= len(cases)`` (every case has at least one
  tag after the Slice A.1 fallback).

See §1.6 and §3 of the plan.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from evals.runner import TestCase

_VALID_BY = ("category", "tag")


@dataclass
class BalanceReport:
    """Structured result returned by :func:`balance`."""

    by: str
    histogram: dict[str, int] = field(default_factory=dict)
    median: int = 0
    recommendations: list[str] = field(default_factory=list)


def histogram(cases: list[TestCase], by: str = "category") -> dict[str, int]:
    """Count cases per bucket.

    ``by="category"``: one bucket per unique ``case.category`` (disjoint).
    ``by="tag"``: one bucket per tag; cases with multiple tags count in
    each of their tag buckets.

    An empty list yields ``{}``. Any ``by`` value other than ``"category"``
    or ``"tag"`` raises :class:`ValueError`.
    """
    if by not in _VALID_BY:
        raise ValueError(
            f"balance histogram: unsupported by={by!r} "
            f"(expected one of {_VALID_BY})"
        )
    counts: dict[str, int] = {}
    if by == "category":
        for case in cases:
            counts[case.category] = counts.get(case.category, 0) + 1
        return counts
    # by == "tag"
    for case in cases:
        for tag in case.tags:
            counts[tag] = counts.get(tag, 0) + 1
    return counts


def _median_bucket(hist: dict[str, int]) -> int:
    """Median bucket count.

    For N buckets, sort counts ascending and return ``counts[N // 2]``
    (upper median when N is even). Empty histogram → 0.
    """
    if not hist:
        return 0
    sorted_counts = sorted(hist.values())
    return sorted_counts[len(sorted_counts) // 2]


def recommendations(hist: dict[str, int]) -> list[str]:
    """Per-bucket rebalance advice targeting the median bucket size.

    One string per off-median bucket:

    - Below median → ``"Add M cases to 'bucket' to reach median (currently N)"``
    - Above median → ``"'bucket' has N cases; median is M — consider trimming or downsampling"``
    - At median → omitted entirely.

    Output is sorted alphabetically by bucket name for stable display.
    Empty histogram → ``[]``. Never emits "add 0" or "trim 0" lines.
    """
    if not hist:
        return []
    median = _median_bucket(hist)
    recs: list[str] = []
    for bucket in sorted(hist):
        count = hist[bucket]
        if count == median:
            continue
        if count < median:
            delta = median - count
            recs.append(
                f"Add {delta} cases to '{bucket}' to reach median (currently {count})"
            )
        else:
            recs.append(
                f"'{bucket}' has {count} cases; median is {median} — "
                "consider trimming or downsampling"
            )
    return recs


def balance(cases: list[TestCase], by: str = "category") -> BalanceReport:
    """Build a :class:`BalanceReport` in one call.

    Convenience wrapper around :func:`histogram` and :func:`recommendations`.
    Read-only: does not mutate ``cases``.
    """
    hist = histogram(cases, by=by)
    return BalanceReport(
        by=by,
        histogram=hist,
        median=_median_bucket(hist),
        recommendations=recommendations(hist),
    )
