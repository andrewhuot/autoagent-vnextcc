"""Tests for P0 truth-surface alignment wiring changes.

Verifies that:
1. search_strategy is passed from config to Optimizer
2. drift_threshold is passed from config to DriftMonitor
3. score_handoff() is wired into analyze_trace() for handoff events
4. Autofix apply response does not contain misleading empty fields
5. Context report endpoint returns honest status
"""

from __future__ import annotations

import pytest

from context.analyzer import ContextAnalyzer, HandoffScore
from judges.drift_monitor import DriftMonitor
from optimizer.loop import Optimizer
from optimizer.search import SearchStrategy


# ---------------------------------------------------------------------------
# 1. search_strategy passthrough
# ---------------------------------------------------------------------------


class TestSearchStrategyWiring:
    """Verify Optimizer receives and applies search_strategy from config."""

    def test_optimizer_accepts_search_strategy_simple(self):
        from evals.runner import EvalRunner

        opt = Optimizer(eval_runner=EvalRunner(), search_strategy="simple")
        assert opt.search_strategy == SearchStrategy.SIMPLE

    def test_optimizer_accepts_search_strategy_adaptive(self):
        from evals.runner import EvalRunner

        opt = Optimizer(eval_runner=EvalRunner(), search_strategy="adaptive")
        assert opt.search_strategy == SearchStrategy.ADAPTIVE

    def test_optimizer_accepts_search_strategy_full(self):
        from evals.runner import EvalRunner

        opt = Optimizer(eval_runner=EvalRunner(), search_strategy="full")
        assert opt.search_strategy == SearchStrategy.FULL

    def test_optimizer_defaults_to_simple_on_invalid(self):
        from evals.runner import EvalRunner

        opt = Optimizer(eval_runner=EvalRunner(), search_strategy="nonexistent")
        assert opt.search_strategy == SearchStrategy.SIMPLE

    def test_config_search_strategy_field_exists(self):
        """Verify OptimizerRuntimeConfig exposes search_strategy."""
        from agent.config.runtime import OptimizerRuntimeConfig

        config = OptimizerRuntimeConfig()
        assert config.search_strategy == "simple"

        config = OptimizerRuntimeConfig(search_strategy="full")
        assert config.search_strategy == "full"


# ---------------------------------------------------------------------------
# 2. drift_threshold passthrough
# ---------------------------------------------------------------------------


class TestDriftThresholdWiring:
    """Verify DriftMonitor receives and uses configured threshold."""

    def test_default_threshold(self):
        monitor = DriftMonitor()
        assert monitor.drift_threshold == 0.1

    def test_custom_threshold(self):
        monitor = DriftMonitor(drift_threshold=0.12)
        assert monitor.drift_threshold == 0.12

    def test_threshold_used_in_drift_check(self):
        """With a high threshold, drift that would normally trigger should not."""
        # Create verdicts where recent window has lower agreement (drift of ~0.15)
        historical = [{"score": 1.0, "expected": 1.0, "grader_id": "g1"}] * 100
        # Recent window: only 85% agreement vs 100% historical → drift = 0.15
        recent_agree = [{"score": 1.0, "expected": 1.0, "grader_id": "g1"}] * 42
        recent_disagree = [{"score": 0.5, "expected": 1.0, "grader_id": "g1"}] * 8
        verdicts = historical + recent_agree + recent_disagree

        # With default threshold (0.1), this should alert
        monitor_sensitive = DriftMonitor(drift_threshold=0.1)
        alert = monitor_sensitive.check_agreement_drift(verdicts)
        assert alert is not None

        # With higher threshold (0.2), same drift should NOT alert
        monitor_tolerant = DriftMonitor(drift_threshold=0.2)
        alert = monitor_tolerant.check_agreement_drift(verdicts)
        assert alert is None

    def test_config_drift_threshold_field_exists(self):
        """Verify OptimizerRuntimeConfig exposes drift_threshold."""
        from agent.config.runtime import OptimizerRuntimeConfig

        config = OptimizerRuntimeConfig()
        assert config.drift_threshold == 0.12


# ---------------------------------------------------------------------------
# 3. score_handoff() wired into analyze_trace()
# ---------------------------------------------------------------------------


class TestHandoffScoringWiring:
    """Verify score_handoff() is called during analyze_trace() for handoff events."""

    def test_no_handoffs_produces_empty_scores(self):
        """Trace with single agent should have no handoff scores."""
        analyzer = ContextAnalyzer()
        events = [
            {
                "event_type": "model_call",
                "tokens_in": 100,
                "tokens_out": 50,
                "agent_path": "root/agent_a",
                "trace_id": "t1",
                "metadata": {"tokens_available": 128000},
            },
            {
                "event_type": "model_call",
                "tokens_in": 200,
                "tokens_out": 100,
                "agent_path": "root/agent_a",
                "trace_id": "t1",
                "metadata": {"tokens_available": 128000},
            },
        ]
        analysis = analyzer.analyze_trace(events)
        assert analysis.handoff_scores == []
        assert analysis.avg_handoff_fidelity == 0.0

    def test_handoff_with_summary_produces_score(self):
        """Trace with agent transition and handoff_summary should produce a score."""
        analyzer = ContextAnalyzer()
        events = [
            {
                "event_type": "model_call",
                "tokens_in": 100,
                "tokens_out": 50,
                "agent_path": "root/agent_a",
                "trace_id": "t1",
                "content": "The user wants to cancel their order number 12345",
                "metadata": {"tokens_available": 128000},
            },
            {
                "event_type": "model_call",
                "tokens_in": 200,
                "tokens_out": 100,
                "agent_path": "root/agent_b",
                "trace_id": "t1",
                "handoff_summary": "user cancel order 12345",
                "metadata": {"tokens_available": 128000},
            },
        ]
        analysis = analyzer.analyze_trace(events)
        assert len(analysis.handoff_scores) == 1
        score = analysis.handoff_scores[0]
        assert score.from_agent == "root/agent_a"
        assert score.to_agent == "root/agent_b"
        assert score.turn_number == 1
        assert 0.0 < score.fidelity <= 1.0

    def test_handoff_fidelity_in_to_dict(self):
        """Verify handoff data appears in serialized output."""
        analyzer = ContextAnalyzer()
        events = [
            {
                "event_type": "model_call",
                "tokens_in": 100,
                "tokens_out": 50,
                "agent_path": "root/agent_a",
                "trace_id": "t1",
                "content": "hello world test context",
                "metadata": {"tokens_available": 128000},
            },
            {
                "event_type": "model_call",
                "tokens_in": 200,
                "tokens_out": 100,
                "agent_path": "root/agent_b",
                "trace_id": "t1",
                "handoff_summary": "hello world",
                "metadata": {"tokens_available": 128000},
            },
        ]
        analysis = analyzer.analyze_trace(events)
        d = analysis.to_dict()
        assert "handoff_scores" in d
        assert "avg_handoff_fidelity" in d
        assert len(d["handoff_scores"]) == 1
        assert d["avg_handoff_fidelity"] > 0.0

    def test_low_fidelity_generates_recommendation(self):
        """Low handoff fidelity should produce a recommendation."""
        analyzer = ContextAnalyzer()
        events = [
            {
                "event_type": "model_call",
                "tokens_in": 100,
                "tokens_out": 50,
                "agent_path": "root/agent_a",
                "trace_id": "t1",
                "content": "The user has a complex multi-step request involving order cancellation refund and account deletion",
                "metadata": {"tokens_available": 128000},
            },
            {
                "event_type": "model_call",
                "tokens_in": 200,
                "tokens_out": 100,
                "agent_path": "root/agent_b",
                "trace_id": "t1",
                "handoff_summary": "help needed",
                "metadata": {"tokens_available": 128000},
            },
        ]
        analysis = analyzer.analyze_trace(events)
        assert any("handoff fidelity" in r.lower() for r in analysis.recommendations)


# ---------------------------------------------------------------------------
# 4. Autofix apply response honesty
# ---------------------------------------------------------------------------


class TestAutofixResponseHonesty:
    """Verify autofix apply response doesn't contain misleading empty fields."""

    def test_response_has_next_steps(self):
        """The apply endpoint response should guide the user to eval/deploy, not imply they happened."""
        from pathlib import Path
        import re

        route_path = Path(__file__).parent.parent / "api" / "routes" / "autofix.py"
        source = route_path.read_text()

        # The apply endpoint should have next_steps guidance
        assert "next_steps" in source

        # The apply endpoint response should NOT have misleading empty canary/deploy fields
        # (the history serializer may still reference these for reading stored data — that's ok)
        # Extract the apply_proposal function body
        apply_start = source.find("async def apply_proposal")
        apply_end = source.find("\n@router", apply_start + 1)
        apply_body = source[apply_start:apply_end] if apply_end > apply_start else source[apply_start:]

        assert "canary_verdict" not in apply_body
        assert "deploy_message" not in apply_body


# ---------------------------------------------------------------------------
# 5. Context report endpoint honesty
# ---------------------------------------------------------------------------


class TestContextReportHonesty:
    """Verify context report endpoint communicates its status honestly."""

    def test_report_status_is_not_misleading(self):
        """The stub should not claim 'healthy' when it has no data."""
        import ast
        from pathlib import Path

        route_path = Path(__file__).parent.parent / "api" / "routes" / "context.py"
        source = route_path.read_text()

        # Should not claim healthy when no data
        # The status should indicate no_data or similar
        assert '"no_data"' in source or "'no_data'" in source
        # Should have guidance note
        assert "note" in source
