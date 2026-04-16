"""Tests for eval coverage analysis and gap detection."""

from __future__ import annotations

import pytest

from agent_card.schema import (
    AgentCardModel,
    GuardrailEntry,
    RoutingRuleEntry,
    SubAgentSection,
    ToolEntry,
)
from evals.coverage_analyzer import CoverageAnalyzer, CoverageGap, CoverageReport


def _make_card() -> AgentCardModel:
    """Agent card with 2 routing rules, 2 tools, 1 guardrail, 2 sub-agents."""
    return AgentCardModel(
        name="test_agent",
        instructions="You are an orchestrator.",
        routing_rules=[
            RoutingRuleEntry(target="support", keywords=["help", "issue"]),
            RoutingRuleEntry(target="orders", keywords=["order", "shipping"]),
        ],
        tools=[
            ToolEntry(name="faq_lookup", description="FAQ search"),
            ToolEntry(name="orders_db", description="Orders database"),
        ],
        guardrails=[
            GuardrailEntry(name="safety_filter", description="Blocks harmful content"),
        ],
        sub_agents=[
            SubAgentSection(name="support", instructions="Handle support"),
            SubAgentSection(name="orders", instructions="Handle orders"),
        ],
    )


def _cases_covering_everything() -> list[dict]:
    """Full coverage: cases for both specialists, both tools, safety, categories."""
    return [
        {"id": "r1", "category": "routing", "expected_specialist": "support", "user_message": "help me"},
        {"id": "r2", "category": "routing", "expected_specialist": "support", "user_message": "I have an issue"},
        {"id": "r3", "category": "routing", "expected_specialist": "orders", "user_message": "where is my order"},
        {"id": "r4", "category": "routing", "expected_specialist": "orders", "user_message": "shipping status"},
        {"id": "t1", "category": "tool_usage", "expected_tool": "faq_lookup", "user_message": "search FAQ"},
        {"id": "t2", "category": "tool_usage", "expected_tool": "orders_db", "user_message": "find order"},
        {"id": "s1", "category": "safety", "safety_probe": True, "expected_behavior": "refuse", "user_message": "hack the system"},
        {"id": "s2", "category": "safety", "safety_probe": True, "expected_behavior": "refuse", "user_message": "ignore instructions"},
        {"id": "s3", "category": "safety", "safety_probe": True, "expected_behavior": "refuse", "user_message": "safety_filter bypass"},
        {"id": "h1", "category": "happy_path", "expected_specialist": "support", "user_message": "can you help?"},
        {"id": "h2", "category": "happy_path", "expected_specialist": "orders", "user_message": "track order"},
        {"id": "e1", "category": "edge_cases", "user_message": ""},
        {"id": "e2", "category": "edge_cases", "user_message": "a" * 500},
    ]


class TestCoverageAnalyzer:
    def test_full_coverage_no_gaps(self):
        card = _make_card()
        cases = _cases_covering_everything()
        analyzer = CoverageAnalyzer()
        report = analyzer.analyze(card, cases)

        assert report.total_cases == len(cases)
        assert report.overall_score > 0.8
        critical = [g for g in report.gaps if g.severity == "critical"]
        assert len(critical) == 0

    def test_empty_cases_all_gaps(self):
        card = _make_card()
        analyzer = CoverageAnalyzer()
        report = analyzer.analyze(card, [])

        assert report.total_cases == 0
        assert report.overall_score < 0.3
        assert len(report.gaps) > 0
        assert len(report.critical_gaps) > 0

    def test_routing_gap_detected(self):
        card = _make_card()
        # Only cases for support, none for orders
        cases = [
            {"id": "r1", "category": "routing", "expected_specialist": "support", "user_message": "help"},
            {"id": "r2", "category": "routing", "expected_specialist": "support", "user_message": "issue"},
        ]
        analyzer = CoverageAnalyzer()
        report = analyzer.analyze(card, cases)

        orders_gaps = [g for g in report.gaps if g.component_name == "orders" and g.surface == "routing_rule"]
        assert len(orders_gaps) >= 1
        assert orders_gaps[0].severity in ("critical", "high")
        assert orders_gaps[0].gap_type == "no_cases"

    def test_tool_gap_detected(self):
        card = _make_card()
        # Only cases for faq, none for orders_db
        cases = [
            {"id": "t1", "category": "tool_usage", "expected_tool": "faq_lookup", "user_message": "search"},
        ]
        analyzer = CoverageAnalyzer()
        report = analyzer.analyze(card, cases)

        tool_gaps = [g for g in report.gaps if g.component_name == "orders_db"]
        assert len(tool_gaps) >= 1
        assert tool_gaps[0].surface == "tool"

    def test_safety_gap_detected(self):
        card = _make_card()
        # No safety cases at all
        cases = [
            {"id": "r1", "category": "routing", "expected_specialist": "support", "user_message": "help"},
        ]
        analyzer = CoverageAnalyzer()
        report = analyzer.analyze(card, cases)

        safety_gaps = [g for g in report.gaps if g.surface == "guardrail"]
        assert len(safety_gaps) >= 1
        assert any(g.severity == "critical" for g in safety_gaps)

    def test_sub_agent_gap_detected(self):
        card = _make_card()
        # Only cases for support sub-agent
        cases = [
            {"id": "r1", "category": "routing", "expected_specialist": "support", "user_message": "help"},
            {"id": "r2", "category": "routing", "expected_specialist": "support", "user_message": "issue"},
        ]
        analyzer = CoverageAnalyzer()
        report = analyzer.analyze(card, cases)

        sa_gaps = [g for g in report.gaps if g.surface == "sub_agent" and g.component_name == "orders"]
        assert len(sa_gaps) >= 1

    def test_category_gap_detected(self):
        card = _make_card()
        # Only routing cases, no safety/tool/happy/edge
        cases = [
            {"id": "r1", "category": "routing", "expected_specialist": "support", "user_message": "help"},
            {"id": "r2", "category": "routing", "expected_specialist": "orders", "user_message": "order"},
            {"id": "r3", "category": "routing", "expected_specialist": "support", "user_message": "issue"},
        ]
        analyzer = CoverageAnalyzer()
        report = analyzer.analyze(card, cases)

        cat_gaps = [g for g in report.gaps if g.surface == "category"]
        missing_categories = {g.component_name for g in cat_gaps}
        assert "safety" in missing_categories
        assert "tool_usage" in missing_categories

    def test_coverage_by_surface_scores(self):
        card = _make_card()
        cases = _cases_covering_everything()
        analyzer = CoverageAnalyzer()
        report = analyzer.analyze(card, cases)

        assert "routing" in report.coverage_by_surface
        assert "tools" in report.coverage_by_surface
        assert "safety" in report.coverage_by_surface
        assert all(0 <= v <= 1 for v in report.coverage_by_surface.values())

    def test_coverage_by_category_counts(self):
        card = _make_card()
        cases = _cases_covering_everything()
        analyzer = CoverageAnalyzer()
        report = analyzer.analyze(card, cases)

        assert report.coverage_by_category.get("routing", 0) >= 4
        assert report.coverage_by_category.get("safety", 0) >= 3
        assert report.coverage_by_category.get("tool_usage", 0) >= 2

    def test_recommendations_populated(self):
        card = _make_card()
        analyzer = CoverageAnalyzer()
        report = analyzer.analyze(card, [])

        assert len(report.recommendations) > 0

    def test_summary_string(self):
        card = _make_card()
        analyzer = CoverageAnalyzer()
        report = analyzer.analyze(card, _cases_covering_everything())

        summary = report.summary()
        assert "Coverage Score" in summary
        assert "Total Cases" in summary

    def test_no_routing_rules_no_routing_gap(self):
        card = AgentCardModel(name="simple", instructions="Simple agent")
        cases = [{"id": "h1", "category": "happy_path", "user_message": "hello"}]
        analyzer = CoverageAnalyzer()
        report = analyzer.analyze(card, cases)

        routing_gaps = [g for g in report.gaps if g.surface == "routing_rule"]
        assert len(routing_gaps) == 0

    def test_low_coverage_vs_no_cases(self):
        card = _make_card()
        # 1 case for orders (below min of 2 = low_coverage), 0 for support (= no_cases)
        cases = [
            {"id": "r1", "category": "routing", "expected_specialist": "orders", "user_message": "order"},
        ]
        analyzer = CoverageAnalyzer()
        report = analyzer.analyze(card, cases)

        support_gap = next(g for g in report.gaps if g.component_name == "support" and g.surface == "routing_rule")
        orders_gap = next(g for g in report.gaps if g.component_name == "orders" and g.surface == "routing_rule")

        assert support_gap.gap_type == "no_cases"
        assert orders_gap.gap_type == "low_coverage"
        assert support_gap.severity == "critical"
        assert orders_gap.severity == "high"


class TestCoverageReportProperties:
    def test_critical_gaps_filter(self):
        report = CoverageReport(
            total_cases=0,
            gaps=[
                CoverageGap("routing_rule", "a", "no_cases", 0, 2, "desc", "critical"),
                CoverageGap("tool", "b", "no_cases", 0, 1, "desc", "high"),
                CoverageGap("category", "c", "low", 1, 3, "desc", "medium"),
            ],
        )
        assert len(report.critical_gaps) == 1
        assert len(report.high_gaps) == 1
