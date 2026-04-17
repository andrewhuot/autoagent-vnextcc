"""Tests for CardCaseGenerator.generate_variants_from_cluster (R5 C.5).

Failure-driven variant generation: given a FailureCluster seed, produce
3-5 deterministic variant GeneratedCases tagged with
``source="failure_cluster:<cluster_id>"``.
"""

from __future__ import annotations

import os

import pytest

from evals.card_case_generator import CardCaseGenerator, GeneratedCase
from optimizer.failure_analyzer import FailureCluster


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cluster_with_samples(
    cluster_id: str = "c1",
    sample_messages: list[str] | None = None,
) -> FailureCluster:
    """Build a FailureCluster whose sample_ids reflect representative cases.

    The generator reads ``cluster.failure_samples`` (a list of dicts with a
    ``user_message`` field) when present; we attach that attribute dynamically
    since FailureCluster in the repo stores only sample_ids, not the full
    sample payload.
    """
    cluster = FailureCluster(
        cluster_id=cluster_id,
        description="Seed cluster for variant generation tests.",
        root_cause_hypothesis="Routing keyword gap.",
        failure_type="routing_error",
        sample_ids=[f"s_{i}" for i in range(len(sample_messages or []))],
        affected_agent="root",
        severity=0.7,
        count=len(sample_messages or []),
    )
    # Attach sample payload so the generator has seed user_messages available.
    cluster.failure_samples = [  # type: ignore[attr-defined]
        {"id": f"s_{i}", "user_message": msg, "category": "routing"}
        for i, msg in enumerate(sample_messages or [])
    ]
    return cluster


# ---------------------------------------------------------------------------
# Count clamping / validation
# ---------------------------------------------------------------------------


def test_generate_variants_default_count_4() -> None:
    gen = CardCaseGenerator()
    cluster = _cluster_with_samples(sample_messages=["I want a refund please"])
    variants = gen.generate_variants_from_cluster(cluster)
    assert len(variants) == 4


def test_generate_variants_count_3() -> None:
    gen = CardCaseGenerator()
    cluster = _cluster_with_samples(sample_messages=["I want a refund please"])
    variants = gen.generate_variants_from_cluster(cluster, count=3)
    assert len(variants) == 3


def test_generate_variants_count_5() -> None:
    gen = CardCaseGenerator()
    cluster = _cluster_with_samples(sample_messages=["I want a refund please"])
    variants = gen.generate_variants_from_cluster(cluster, count=5)
    assert len(variants) == 5


def test_generate_variants_count_below_3_raises() -> None:
    gen = CardCaseGenerator()
    cluster = _cluster_with_samples(sample_messages=["seed"])
    with pytest.raises(ValueError):
        gen.generate_variants_from_cluster(cluster, count=2)


def test_generate_variants_count_above_5_raises() -> None:
    gen = CardCaseGenerator()
    cluster = _cluster_with_samples(sample_messages=["seed"])
    with pytest.raises(ValueError):
        gen.generate_variants_from_cluster(cluster, count=6)


# ---------------------------------------------------------------------------
# Metadata on each variant
# ---------------------------------------------------------------------------


def test_generate_variants_source_field_tags_cluster() -> None:
    gen = CardCaseGenerator()
    cluster = _cluster_with_samples(
        cluster_id="fc_xyz", sample_messages=["help me please"]
    )
    variants = gen.generate_variants_from_cluster(cluster)
    assert all(v.source == "failure_cluster:fc_xyz" for v in variants)


def test_generate_variants_ids_are_unique() -> None:
    gen = CardCaseGenerator()
    cluster = _cluster_with_samples(
        cluster_id="cluster_a", sample_messages=["my order is late"]
    )
    variants = gen.generate_variants_from_cluster(cluster, count=5)
    ids = [v.id for v in variants]
    assert len(set(ids)) == 5
    # Deterministic id scheme: fc_<cluster_id>_000 ... fc_<cluster_id>_004
    for i, v in enumerate(variants):
        assert v.id == f"fc_cluster_a_{i:03d}"


def test_generate_variants_returns_generated_case_instances() -> None:
    gen = CardCaseGenerator()
    cluster = _cluster_with_samples(sample_messages=["help me"])
    variants = gen.generate_variants_from_cluster(cluster)
    assert all(isinstance(v, GeneratedCase) for v in variants)


# ---------------------------------------------------------------------------
# Determinism / empty cluster
# ---------------------------------------------------------------------------


def test_generate_variants_deterministic_no_llm() -> None:
    gen = CardCaseGenerator()
    cluster = _cluster_with_samples(
        cluster_id="det", sample_messages=["I cannot log in"]
    )
    first = gen.generate_variants_from_cluster(cluster, count=4)
    second = gen.generate_variants_from_cluster(cluster, count=4)

    assert [v.id for v in first] == [v.id for v in second]
    assert [v.user_message for v in first] == [v.user_message for v in second]
    assert [v.source for v in first] == [v.source for v in second]


def test_generate_variants_empty_cluster_still_produces_count_variants() -> None:
    gen = CardCaseGenerator()
    cluster = _cluster_with_samples(cluster_id="empty", sample_messages=[])
    variants = gen.generate_variants_from_cluster(cluster, count=4)
    assert len(variants) == 4
    # Each variant should still carry the cluster source.
    assert all(v.source == "failure_cluster:empty" for v in variants)
    # Variants should still have non-empty user messages (generic phrasing).
    assert all(v.user_message for v in variants)


# ---------------------------------------------------------------------------
# Strict-live guard
# ---------------------------------------------------------------------------


class _DummyRouter:
    """Stand-in for LLMRouter presence; not exercised by strict-live test."""


def test_generate_variants_strict_live_with_llm_router_no_key_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    gen = CardCaseGenerator(llm_router=_DummyRouter())
    cluster = _cluster_with_samples(sample_messages=["seed"])

    with pytest.raises(RuntimeError, match="strict"):
        gen.generate_variants_from_cluster(cluster, strict_live=True)


def test_generate_variants_strict_live_false_no_router_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No router + strict_live=False → never raise, template variants only."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    gen = CardCaseGenerator(llm_router=None)
    cluster = _cluster_with_samples(sample_messages=["seed"])
    variants = gen.generate_variants_from_cluster(cluster, strict_live=False)
    assert len(variants) == 4


def test_generate_variants_strict_live_true_no_router_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """strict_live=True but router is None → no guard triggers."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    gen = CardCaseGenerator(llm_router=None)
    cluster = _cluster_with_samples(sample_messages=["seed"])
    variants = gen.generate_variants_from_cluster(cluster, strict_live=True)
    assert len(variants) == 4


def test_generate_variants_strict_live_with_router_and_key_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    gen = CardCaseGenerator(llm_router=_DummyRouter())
    cluster = _cluster_with_samples(sample_messages=["seed"])
    # Should not raise — template fallback still works when LLM is not called.
    variants = gen.generate_variants_from_cluster(cluster, strict_live=True)
    assert 3 <= len(variants) <= 5
