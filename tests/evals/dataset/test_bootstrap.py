"""Tests for evals.dataset.bootstrap — farthest-point sampling over Agent Card cases.

Slice B.6 of the R5 eval corpus plan.
"""

from __future__ import annotations

import pytest

from agent_card.schema import (
    AgentCardModel,
    GuardrailEntry,
    RoutingRuleEntry,
    SubAgentSection,
    ToolEntry,
)
from evals.card_case_generator import CardCaseGenerator, GeneratedCase
from evals.dataset.embedder import FakeEmbedder


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_card() -> AgentCardModel:
    """Build a card rich enough to yield >= 20 generated candidates."""
    return AgentCardModel(
        name="test_agent",
        description="A customer service agent",
        instructions="You are a helpful customer service agent.",
        routing_rules=[
            RoutingRuleEntry(target="support", keywords=["help", "issue", "account"]),
            RoutingRuleEntry(target="orders", keywords=["order", "shipping", "refund"]),
            RoutingRuleEntry(target="billing", keywords=["billing", "invoice"]),
        ],
        tools=[
            ToolEntry(name="faq_lookup", description="Search the FAQ knowledge base"),
            ToolEntry(name="orders_db", description="Query the orders database"),
        ],
        guardrails=[
            GuardrailEntry(name="safety_filter", description="Block PII extraction"),
        ],
        sub_agents=[
            SubAgentSection(
                name="support",
                instructions="Handle customer complaints and general inquiries.",
            ),
            SubAgentSection(
                name="orders",
                instructions="Handle order status and tracking questions.",
            ),
        ],
    )


def _empty_card() -> AgentCardModel:
    return AgentCardModel(name="empty_agent")


class _SpyEmbedder:
    """Wraps a FakeEmbedder and counts embed() calls."""

    def __init__(self) -> None:
        self.inner = FakeEmbedder()
        self.calls = 0

    @property
    def model_name(self) -> str:
        return self.inner.model_name

    def embed(self, texts):
        self.calls += 1
        return self.inner.embed(texts)


class _StubVectorEmbedder:
    """Deterministic embedder keyed by text. Lets tests control geometry."""

    model_name = "stub"

    def __init__(self, vectors_by_text: dict[str, list[float]]) -> None:
        self._by_text = vectors_by_text

    def embed(self, texts):
        return [list(self._by_text[t]) for t in texts]


class _StubGenerator:
    """Stub CardCaseGenerator that returns a fixed list of GeneratedCase objects."""

    def __init__(self, cases: list[GeneratedCase], llm_router=None) -> None:
        self._cases = cases
        self.llm_router = llm_router

    def generate_all(self, card, count_per_category: int = 5) -> list[GeneratedCase]:
        return list(self._cases)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_bootstrap_returns_target_count():
    from evals.dataset.bootstrap import bootstrap

    card = _make_card()
    report = bootstrap(card, target=5, embedder=FakeEmbedder())

    assert len(report.cases) == 5
    assert report.target == 5
    assert report.selected_from_candidate_count >= 5


def test_bootstrap_seed_is_first_candidate():
    from evals.dataset.bootstrap import bootstrap

    card = _make_card()
    # Use a StubGenerator so we know exactly which candidate is index 0.
    fake_cases = [
        GeneratedCase(
            id=f"case_{i}",
            category="routing",
            user_message=f"message number {i}",
            expected_specialist="support",
            expected_behavior="answer",
        )
        for i in range(10)
    ]
    gen = _StubGenerator(fake_cases)

    report = bootstrap(card, target=3, embedder=FakeEmbedder(), generator=gen)
    assert report.cases[0].id == "case_0"


def test_bootstrap_calls_embed_once():
    from evals.dataset.bootstrap import bootstrap

    card = _make_card()
    spy = _SpyEmbedder()
    bootstrap(card, target=4, embedder=spy)
    assert spy.calls == 1


def test_bootstrap_unique_ids():
    from evals.dataset.bootstrap import bootstrap

    card = _make_card()
    report = bootstrap(card, target=8, embedder=FakeEmbedder())
    ids = [c.id for c in report.cases]
    assert len(set(ids)) == len(ids)


def test_bootstrap_target_greater_than_candidates_returns_all():
    from evals.dataset.bootstrap import bootstrap

    fake_cases = [
        GeneratedCase(
            id=f"c_{i}",
            category="routing",
            user_message=f"msg {i}",
            expected_specialist="support",
            expected_behavior="answer",
        )
        for i in range(5)
    ]
    gen = _StubGenerator(fake_cases)

    report = bootstrap(
        _empty_card(), target=10, embedder=FakeEmbedder(), generator=gen
    )
    assert len(report.cases) == 5
    assert report.target == 5  # clamped
    assert report.selected_from_candidate_count == 5
    ids = {c.id for c in report.cases}
    assert ids == {f"c_{i}" for i in range(5)}


def test_bootstrap_fps_prefers_distant_candidates():
    """Three candidates: two very close + one far. target=2 must include the far one."""
    from evals.dataset.bootstrap import bootstrap

    cases = [
        GeneratedCase(
            id="close_a",
            category="routing",
            user_message="text_close_a",
            expected_specialist="support",
            expected_behavior="answer",
        ),
        GeneratedCase(
            id="close_b",
            category="routing",
            user_message="text_close_b",
            expected_specialist="support",
            expected_behavior="answer",
        ),
        GeneratedCase(
            id="far",
            category="routing",
            user_message="text_far",
            expected_specialist="support",
            expected_behavior="answer",
        ),
    ]
    # Vectors: close_a and close_b almost identical; far is orthogonal.
    stub_embedder = _StubVectorEmbedder({
        "text_close_a": [1.0, 0.0, 0.0],
        "text_close_b": [0.999, 0.001, 0.0],
        "text_far": [0.0, 1.0, 0.0],
    })
    gen = _StubGenerator(cases)

    report = bootstrap(
        _empty_card(), target=2, embedder=stub_embedder, generator=gen
    )
    ids = {c.id for c in report.cases}
    # Seed is close_a (index 0). The next pick must be "far" because it is
    # further from close_a than close_b.
    assert ids == {"close_a", "far"}


def test_bootstrap_generated_cases_have_category_tag():
    """GeneratedCase has no tags field; bootstrap should default tags to [category]."""
    from evals.dataset.bootstrap import bootstrap

    cases = [
        GeneratedCase(
            id="c1",
            category="safety",
            user_message="probe 1",
            expected_specialist="support",
            expected_behavior="refuse",
        ),
        GeneratedCase(
            id="c2",
            category="tool_usage",
            user_message="do the thing",
            expected_specialist="support",
            expected_behavior="answer",
        ),
    ]
    gen = _StubGenerator(cases)

    report = bootstrap(
        _empty_card(), target=2, embedder=FakeEmbedder(), generator=gen
    )
    by_id = {c.id: c for c in report.cases}
    assert by_id["c1"].tags == ["safety"]
    assert by_id["c2"].tags == ["tool_usage"]
    # reference_answer is empty for generated cases.
    assert by_id["c1"].reference_answer == ""


def test_bootstrap_empty_card_returns_empty_report():
    from evals.dataset.bootstrap import bootstrap

    # An empty card with no routing rules, tools, or sub-agents still yields
    # edge cases (empty, long, non-ASCII, greetings).  Bootstrap should handle
    # whatever it gets without erroring.
    report = bootstrap(_empty_card(), target=3, embedder=FakeEmbedder())
    assert report.selected_from_candidate_count >= 0
    assert len(report.cases) <= report.selected_from_candidate_count
    # If fewer candidates than target, target is clamped.
    assert report.target == min(3, report.selected_from_candidate_count)


def test_bootstrap_strict_live_with_llm_router_no_key_raises(monkeypatch):
    from evals.dataset.bootstrap import bootstrap

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    # Fake router is just a marker — bootstrap only checks presence + env key.
    gen = _StubGenerator([], llm_router=object())

    with pytest.raises(RuntimeError, match="strict_live"):
        bootstrap(
            _make_card(),
            target=3,
            embedder=FakeEmbedder(),
            generator=gen,
            strict_live=True,
        )


def test_bootstrap_strict_live_with_llm_router_and_key_ok(monkeypatch):
    from evals.dataset.bootstrap import bootstrap

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")

    cases = [
        GeneratedCase(
            id="c0",
            category="routing",
            user_message="msg 0",
            expected_specialist="support",
            expected_behavior="answer",
        ),
        GeneratedCase(
            id="c1",
            category="routing",
            user_message="msg 1",
            expected_specialist="support",
            expected_behavior="answer",
        ),
    ]
    gen = _StubGenerator(cases, llm_router=object())

    report = bootstrap(
        _make_card(),
        target=2,
        embedder=FakeEmbedder(),
        generator=gen,
        strict_live=True,
    )
    assert len(report.cases) == 2


def test_bootstrap_strict_live_default_no_router_ok(monkeypatch):
    """With default generator (no llm_router), strict_live=True is a no-op."""
    from evals.dataset.bootstrap import bootstrap

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    # Default CardCaseGenerator() has llm_router=None → no raise.
    report = bootstrap(
        _make_card(),
        target=3,
        embedder=FakeEmbedder(),
        strict_live=True,
    )
    assert len(report.cases) == 3
