"""Comprehensive tests for the Context Engineering Studio."""

from __future__ import annotations

import time

import pytest

from context.analyzer import (
    ContextAnalysis,
    ContextAnalyzer,
    ContextCorrelation,
    ContextSnapshot,
    GrowthPattern,
)
from context.metrics import ContextMetrics
from context.simulator import (
    CompactionSimulator,
    CompactionStrategy,
    SimulationResult,
    SimulationStep,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(
    event_type: str = "model_call",
    tokens_in: int = 100,
    tokens_out: int = 50,
    error_message: str | None = None,
    agent_path: str = "root/support",
    trace_id: str = "trace-1",
    tokens_available: int = 128_000,
) -> dict:
    """Build a minimal trace event dict for testing."""
    evt: dict = {
        "event_type": event_type,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "agent_path": agent_path,
        "trace_id": trace_id,
        "metadata": {"tokens_available": tokens_available},
    }
    if error_message:
        evt["error_message"] = error_message
    return evt


def _make_snapshots(token_sequence: list[int], available: int = 128_000) -> list[ContextSnapshot]:
    """Build a list of snapshots with the given token_used values."""
    return [
        ContextSnapshot(
            turn_number=i,
            tokens_used=t,
            tokens_available=available,
            event_type="model_call",
            agent_path="root",
        )
        for i, t in enumerate(token_sequence)
    ]


# ---------------------------------------------------------------------------
# ContextSnapshot
# ---------------------------------------------------------------------------

class TestContextSnapshot:
    def test_creation(self):
        s = ContextSnapshot(0, 500, 1000, "model_call", "root")
        assert s.turn_number == 0
        assert s.tokens_used == 500
        assert s.tokens_available == 1000

    def test_utilization(self):
        s = ContextSnapshot(0, 300, 1000, "model_call", "root")
        assert s.utilization == pytest.approx(0.3)

    def test_utilization_full(self):
        s = ContextSnapshot(0, 1000, 1000, "model_call", "root")
        assert s.utilization == pytest.approx(1.0)

    def test_utilization_div_by_zero(self):
        s = ContextSnapshot(0, 100, 0, "model_call", "root")
        assert s.utilization == 0.0

    def test_utilization_zero_tokens(self):
        s = ContextSnapshot(0, 0, 1000, "model_call", "root")
        assert s.utilization == 0.0

    def test_default_metadata(self):
        s = ContextSnapshot(0, 0, 0, "x", "y")
        assert s.metadata == {}


# ---------------------------------------------------------------------------
# ContextAnalyzer — measure_utilization
# ---------------------------------------------------------------------------

class TestMeasureUtilization:
    def test_basic(self):
        events = [_make_event(tokens_in=100, tokens_out=50)]
        analyzer = ContextAnalyzer()
        snaps = analyzer.measure_utilization(events)
        assert len(snaps) == 1
        assert snaps[0].tokens_used == 150  # cumulative

    def test_cumulative(self):
        events = [
            _make_event(tokens_in=100, tokens_out=50),
            _make_event(tokens_in=200, tokens_out=100),
        ]
        analyzer = ContextAnalyzer()
        snaps = analyzer.measure_utilization(events)
        assert snaps[0].tokens_used == 150
        assert snaps[1].tokens_used == 450

    def test_empty_events(self):
        analyzer = ContextAnalyzer()
        snaps = analyzer.measure_utilization([])
        assert snaps == []


# ---------------------------------------------------------------------------
# ContextAnalyzer — detect_growth_pattern
# ---------------------------------------------------------------------------

class TestDetectGrowthPattern:
    def test_stable(self):
        snaps = _make_snapshots([100, 100, 101, 100, 100])
        analyzer = ContextAnalyzer()
        gp = analyzer.detect_growth_pattern(snaps)
        assert gp.pattern_type == "stable"
        assert gp.compaction_events == 0

    def test_linear(self):
        snaps = _make_snapshots([100, 200, 300, 400, 500])
        analyzer = ContextAnalyzer()
        gp = analyzer.detect_growth_pattern(snaps)
        assert gp.pattern_type == "linear"
        assert gp.slope == pytest.approx(100.0)

    def test_exponential(self):
        # Second half grows much faster than first half.
        snaps = _make_snapshots([100, 150, 200, 250, 400, 800, 2000])
        analyzer = ContextAnalyzer()
        gp = analyzer.detect_growth_pattern(snaps)
        assert gp.pattern_type == "exponential"

    def test_sawtooth(self):
        # A compaction drop of >30%.
        snaps = _make_snapshots([100, 500, 1000, 300, 600, 900])
        analyzer = ContextAnalyzer()
        gp = analyzer.detect_growth_pattern(snaps)
        assert gp.pattern_type == "sawtooth"
        assert gp.compaction_events >= 1

    def test_single_snapshot(self):
        snaps = _make_snapshots([500])
        analyzer = ContextAnalyzer()
        gp = analyzer.detect_growth_pattern(snaps)
        assert gp.pattern_type == "stable"
        assert gp.slope == 0.0

    def test_empty_snapshots(self):
        analyzer = ContextAnalyzer()
        gp = analyzer.detect_growth_pattern([])
        assert gp.pattern_type == "stable"


# ---------------------------------------------------------------------------
# ContextAnalyzer — find_failure_correlations
# ---------------------------------------------------------------------------

class TestFindFailureCorrelations:
    def test_failures_at_high_tokens(self):
        events = [
            _make_event(tokens_in=100, tokens_out=0),
            _make_event(tokens_in=100, tokens_out=0),
            _make_event(tokens_in=100, tokens_out=0, error_message="timeout"),
            _make_event(tokens_in=100, tokens_out=0, error_message="timeout"),
        ]
        analyzer = ContextAnalyzer()
        snaps = analyzer.measure_utilization(events)
        corrs = analyzer.find_failure_correlations(events, snaps)
        assert len(corrs) > 0
        # Failures only in the higher-token turns.
        for c in corrs:
            assert c.sample_size == 4

    def test_no_failures(self):
        events = [_make_event() for _ in range(5)]
        analyzer = ContextAnalyzer()
        snaps = analyzer.measure_utilization(events)
        corrs = analyzer.find_failure_correlations(events, snaps)
        # All correlation strengths should be 0 because no failures.
        for c in corrs:
            assert c.failure_rate_above == 0.0
            assert c.failure_rate_below == 0.0

    def test_all_failures(self):
        events = [_make_event(error_message="err") for _ in range(4)]
        analyzer = ContextAnalyzer()
        snaps = analyzer.measure_utilization(events)
        corrs = analyzer.find_failure_correlations(events, snaps)
        for c in corrs:
            assert c.failure_rate_above == 1.0

    def test_empty_events(self):
        analyzer = ContextAnalyzer()
        corrs = analyzer.find_failure_correlations([], [])
        assert corrs == []


# ---------------------------------------------------------------------------
# ContextAnalyzer — score_handoff
# ---------------------------------------------------------------------------

class TestScoreHandoff:
    def test_perfect_overlap(self):
        analyzer = ContextAnalyzer()
        assert analyzer.score_handoff("the cat sat", "the cat sat") == pytest.approx(1.0)

    def test_partial_overlap(self):
        analyzer = ContextAnalyzer()
        score = analyzer.score_handoff("the cat", "the cat sat on mat")
        assert 0.0 < score < 1.0

    def test_no_overlap(self):
        analyzer = ContextAnalyzer()
        assert analyzer.score_handoff("xyz", "abc def ghi") == pytest.approx(0.0)

    def test_empty_original(self):
        analyzer = ContextAnalyzer()
        assert analyzer.score_handoff("something", "") == 0.0


# ---------------------------------------------------------------------------
# ContextAnalyzer — analyze_trace (integration)
# ---------------------------------------------------------------------------

class TestAnalyzeTrace:
    def test_basic_analysis(self):
        events = [_make_event(tokens_in=100, tokens_out=50) for _ in range(5)]
        analyzer = ContextAnalyzer()
        analysis = analyzer.analyze_trace(events)
        assert analysis.trace_id == "trace-1"
        assert len(analysis.snapshots) == 5
        assert analysis.peak_utilization > 0
        assert analysis.avg_utilization > 0

    def test_empty_trace(self):
        analyzer = ContextAnalyzer()
        analysis = analyzer.analyze_trace([])
        assert analysis.peak_utilization == 0.0
        assert analysis.avg_utilization == 0.0
        assert len(analysis.snapshots) == 0

    def test_to_dict(self):
        events = [_make_event() for _ in range(3)]
        analyzer = ContextAnalyzer()
        analysis = analyzer.analyze_trace(events)
        d = analysis.to_dict()
        assert "trace_id" in d
        assert "growth_pattern" in d
        assert "recommendations" in d
        assert d["snapshot_count"] == 3

    def test_recommendations_high_peak(self):
        # Create events that push cumulative tokens very high relative to available.
        events = [_make_event(tokens_in=50000, tokens_out=50000, tokens_available=128_000) for _ in range(2)]
        analyzer = ContextAnalyzer()
        analysis = analyzer.analyze_trace(events)
        # 200k cumulative vs 128k available => utilization > 1.0 => peak > 0.9
        assert any("90%" in r for r in analysis.recommendations)


# ---------------------------------------------------------------------------
# CompactionSimulator
# ---------------------------------------------------------------------------

class TestCompactionSimulator:
    def test_no_compaction_needed(self):
        snaps = _make_snapshots([100, 200, 300])
        sim = CompactionSimulator()
        strategy = CompactionStrategy("test", "test", max_tokens=10000, compaction_trigger=0.8, retention_ratio=0.5)
        result = sim.simulate(snaps, strategy)
        assert result.total_compactions == 0
        assert result.total_tokens_lost == 0
        assert result.final_tokens == 300

    def test_compaction_triggered(self):
        snaps = _make_snapshots([1000, 5000, 8000, 10000])
        sim = CompactionSimulator()
        strategy = CompactionStrategy("agg", "aggressive", max_tokens=8000, compaction_trigger=0.8, retention_ratio=0.4)
        result = sim.simulate(snaps, strategy)
        assert result.total_compactions >= 1
        assert result.total_tokens_lost > 0

    def test_compare_strategies(self):
        snaps = _make_snapshots([1000, 3000, 6000, 10000, 15000])
        sim = CompactionSimulator()
        strategies = sim.default_strategies()
        results = sim.compare_strategies(snaps, strategies)
        assert len(results) == 3
        names = {r.strategy_name for r in results}
        assert names == {"aggressive", "balanced", "conservative"}

    def test_default_strategies(self):
        strategies = CompactionSimulator.default_strategies()
        assert len(strategies) == 3
        assert strategies[0].name == "aggressive"
        assert strategies[1].name == "balanced"
        assert strategies[2].name == "conservative"
        assert strategies[0].max_tokens == 8000
        assert strategies[1].max_tokens == 16000
        assert strategies[2].max_tokens == 32000

    def test_empty_snapshots(self):
        sim = CompactionSimulator()
        strategy = CompactionStrategy("test", "test", max_tokens=8000, compaction_trigger=0.8, retention_ratio=0.5)
        result = sim.simulate([], strategy)
        assert result.total_compactions == 0
        assert result.steps == []
        assert result.final_tokens == 0

    def test_simulation_result_to_dict(self):
        snaps = _make_snapshots([100, 200])
        sim = CompactionSimulator()
        strategy = CompactionStrategy("test", "test", max_tokens=10000, compaction_trigger=0.8, retention_ratio=0.5)
        result = sim.simulate(snaps, strategy)
        d = result.to_dict()
        assert d["strategy_name"] == "test"
        assert "steps" in d
        assert len(d["steps"]) == 2
        assert "tokens_before" in d["steps"][0]

    def test_aggressive_compacts_more_than_conservative(self):
        snaps = _make_snapshots([1000, 3000, 6000, 10000, 15000, 20000, 25000])
        sim = CompactionSimulator()
        strategies = sim.default_strategies()
        results = sim.compare_strategies(snaps, strategies)
        aggressive = next(r for r in results if r.strategy_name == "aggressive")
        conservative = next(r for r in results if r.strategy_name == "conservative")
        assert aggressive.total_compactions >= conservative.total_compactions


# ---------------------------------------------------------------------------
# ContextMetrics
# ---------------------------------------------------------------------------

class TestContextMetrics:
    def test_utilization_ratio(self):
        snaps = _make_snapshots([500, 1000], available=2000)
        ratio = ContextMetrics.utilization_ratio(snaps)
        # 500/2000 = 0.25, 1000/2000 = 0.5, avg = 0.375
        assert ratio == pytest.approx(0.375)

    def test_utilization_ratio_empty(self):
        assert ContextMetrics.utilization_ratio([]) == 0.0

    def test_compaction_loss_score(self):
        steps = [
            SimulationStep(turn=0, tokens_before=1000, tokens_after=1000, compacted=False, tokens_lost=0),
            SimulationStep(turn=1, tokens_before=2000, tokens_after=800, compacted=True, tokens_lost=1200),
        ]
        result = SimulationResult(
            strategy_name="test",
            steps=steps,
            total_compactions=1,
            total_tokens_lost=1200,
            peak_tokens=2000,
            avg_utilization=0.5,
            final_tokens=800,
        )
        score = ContextMetrics.compaction_loss_score(result)
        assert score == pytest.approx(1200 / 3000)

    def test_compaction_loss_score_no_loss(self):
        steps = [
            SimulationStep(turn=0, tokens_before=500, tokens_after=500, compacted=False, tokens_lost=0),
        ]
        result = SimulationResult("t", steps, 0, 0, 500, 0.5, 500)
        assert ContextMetrics.compaction_loss_score(result) == 0.0

    def test_handoff_fidelity(self):
        score = ContextMetrics.handoff_fidelity("the quick brown", "the quick brown fox jumps")
        assert 0.0 < score < 1.0
        assert score == pytest.approx(3 / 5)

    def test_handoff_fidelity_empty(self):
        assert ContextMetrics.handoff_fidelity("something", "") == 0.0

    def test_memory_staleness(self):
        now = time.time()
        entries = [
            {"created_at": now - 100, "last_accessed": now - 50},
            {"created_at": now - 200, "last_accessed": now - 10},
        ]
        staleness = ContextMetrics.memory_staleness(entries)
        # Average age should be roughly (50 + 10) / 2 = 30 seconds.
        assert 25 < staleness < 35

    def test_memory_staleness_empty(self):
        assert ContextMetrics.memory_staleness([]) == 0.0

    def test_memory_staleness_uses_created_at_fallback(self):
        now = time.time()
        entries = [{"created_at": now - 60}]
        staleness = ContextMetrics.memory_staleness(entries)
        assert 55 < staleness < 65

    def test_aggregate_report_basic(self):
        snaps = _make_snapshots([500, 1000], available=2000)
        report = ContextMetrics.aggregate_report(snaps)
        assert "utilization_ratio" in report
        assert report["snapshot_count"] == 2
        assert "compaction_scores" not in report

    def test_aggregate_report_with_simulations(self):
        snaps = _make_snapshots([500, 1000], available=2000)
        steps = [SimulationStep(0, 500, 500, False, 0)]
        sim_result = SimulationResult("test", steps, 0, 0, 500, 0.25, 500)
        report = ContextMetrics.aggregate_report(snaps, simulation_results=[sim_result])
        assert "compaction_scores" in report
        assert "test" in report["compaction_scores"]

    def test_aggregate_report_with_memory(self):
        snaps = _make_snapshots([500])
        now = time.time()
        entries = [{"created_at": now - 30, "last_accessed": now - 10}]
        report = ContextMetrics.aggregate_report(snaps, memory_entries=entries)
        assert "memory_staleness_seconds" in report
        assert report["memory_entry_count"] == 1


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_single_event_trace(self):
        events = [_make_event()]
        analyzer = ContextAnalyzer()
        analysis = analyzer.analyze_trace(events)
        assert len(analysis.snapshots) == 1
        assert analysis.growth_pattern.pattern_type == "stable"

    def test_context_analysis_to_dict_fields(self):
        analysis = ContextAnalysis(
            trace_id="t1",
            snapshots=[],
            growth_pattern=GrowthPattern("stable", 0.0, 0, 0.0),
            peak_utilization=0.0,
            avg_utilization=0.0,
            context_correlations=[
                ContextCorrelation(1000, 0.5, 0.1, 0.8, 10),
            ],
            recommendations=["test rec"],
        )
        d = analysis.to_dict()
        assert d["trace_id"] == "t1"
        assert len(d["correlations"]) == 1
        assert d["correlations"][0]["threshold_tokens"] == 1000
        assert d["recommendations"] == ["test rec"]

    def test_compaction_loss_score_empty_steps(self):
        result = SimulationResult("empty", [], 0, 0, 0, 0.0, 0)
        assert ContextMetrics.compaction_loss_score(result) == 0.0

    def test_analyzer_with_trace_store_none(self):
        analyzer = ContextAnalyzer(trace_store=None)
        assert analyzer.trace_store is None
