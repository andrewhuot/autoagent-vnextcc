"""Slice B acceptance tests: dedupe removes known duplicates; bootstrap
returns a diverse subset with the correct seed.

Per the R5 master plan acceptance criteria (§3 Slice B, row B.8).
"""

from __future__ import annotations

from agent_card.schema import (
    AgentCardModel,
    RoutingRuleEntry,
    SubAgentSection,
    ToolEntry,
)
from evals.card_case_generator import GeneratedCase
from evals.dataset.bootstrap import bootstrap
from evals.dataset.dedupe import dedupe
from evals.dataset.embedder import FakeEmbedder
from evals.runner import TestCase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _case(id: str, user_message: str, ref: str = "") -> TestCase:
    return TestCase(
        id=id,
        category="support",
        user_message=user_message,
        expected_specialist="support",
        expected_behavior="answer",
        reference_answer=ref,
    )


class _StubGenerator:
    def __init__(self, cases: list[GeneratedCase]) -> None:
        self._cases = cases
        self.llm_router = None

    def generate_all(self, card, count_per_category: int = 5):
        return list(self._cases)


def _rich_card() -> AgentCardModel:
    return AgentCardModel(
        name="rich_agent",
        description="Acceptance-test fixture",
        instructions="Help customers.",
        routing_rules=[
            RoutingRuleEntry(target="support", keywords=["help", "issue", "account"]),
            RoutingRuleEntry(target="orders", keywords=["order", "shipping", "refund"]),
            RoutingRuleEntry(target="billing", keywords=["billing", "invoice"]),
        ],
        tools=[
            ToolEntry(name="faq_lookup", description="Search FAQ"),
            ToolEntry(name="orders_db", description="Query orders"),
            ToolEntry(name="invoice_lookup", description="Look up invoice"),
        ],
        sub_agents=[
            SubAgentSection(
                name="support",
                instructions="Handle complaints, returns, password resets, logins.",
            ),
            SubAgentSection(
                name="orders",
                instructions="Handle order status, tracking, shipping questions.",
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Acceptance tests
# ---------------------------------------------------------------------------


def test_acceptance_dedupe_known_duplicates():
    """20 cases where 5 are exact duplicates of 5 others → kept=15, dropped=5."""
    # 15 unique user messages.
    unique = [
        _case(f"u_{i:02d}", user_message=f"unique question number {i}")
        for i in range(15)
    ]
    # 5 duplicates of the first 5 unique cases (different id, shorter ref
    # so the unique one wins the keeper tiebreak).
    duplicates = [
        _case(
            f"dup_{i:02d}",
            user_message=f"unique question number {i}",
            ref="",
        )
        for i in range(5)
    ]
    # Give uniques a longer reference_answer so they win the keeper pick.
    for i in range(5):
        unique[i] = _case(
            f"u_{i:02d}",
            user_message=f"unique question number {i}",
            ref="this is a longer reference answer that wins the tiebreak",
        )

    cases = unique + duplicates
    assert len(cases) == 20

    report = dedupe(cases, FakeEmbedder(), threshold=0.99)

    assert len(report.kept) == 15
    assert len(report.dropped_ids) == 5
    # Dropped ids are exactly the dup_* set.
    assert set(report.dropped_ids) == {f"dup_{i:02d}" for i in range(5)}


def test_acceptance_bootstrap_selects_diverse_cases():
    """Card producing ~30 candidates; target=10 → 10 unique, seed is candidate[0]."""
    card = _rich_card()

    # Run bootstrap with the real default generator (template-only).  Require
    # at least 30 candidates so the FPS pool is meaningfully larger than the
    # target.  The rich card above generates well over 30 for count=10.
    report = bootstrap(card, target=10, embedder=FakeEmbedder())

    assert len(report.cases) == 10
    assert report.target == 10
    assert report.selected_from_candidate_count >= 30

    # Unique ids.
    ids = [c.id for c in report.cases]
    assert len(set(ids)) == 10

    # Seed is the first candidate deterministically — reproduce by invoking
    # the generator directly with the same inputs bootstrap uses internally.
    from evals.card_case_generator import CardCaseGenerator

    gen = CardCaseGenerator()
    candidates = gen.generate_all(card, count_per_category=max(5, 10))
    assert report.cases[0].id == candidates[0].id


def test_acceptance_bootstrap_target_greater_than_candidates():
    """5 candidates, target=10 → report.cases has 5 entries; target clamps to 5."""
    cases = [
        GeneratedCase(
            id=f"c_{i}",
            category="routing",
            user_message=f"message {i}",
            expected_specialist="support",
            expected_behavior="answer",
        )
        for i in range(5)
    ]
    gen = _StubGenerator(cases)

    report = bootstrap(
        AgentCardModel(name="tiny"),
        target=10,
        embedder=FakeEmbedder(),
        generator=gen,
    )

    assert len(report.cases) == 5
    assert report.target == 5
    assert report.selected_from_candidate_count == 5
    assert {c.id for c in report.cases} == {f"c_{i}" for i in range(5)}
