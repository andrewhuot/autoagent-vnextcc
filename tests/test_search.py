"""Unit tests for the multi-hypothesis search engine."""

from __future__ import annotations

import tempfile
import time

from observer.opportunities import OptimizationOpportunity
from optimizer.experiments import ExperimentCard
from optimizer.memory import OptimizationAttempt, OptimizationMemory
from optimizer.mutations import MutationRegistry, create_default_registry
from optimizer.proposer import Proposer
from optimizer.search import (
    CandidateMutation,
    OperatorPerformanceTracker,
    SearchBudget,
    SearchEngine,
    SearchResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_opportunity(
    failure_family: str = "quality_degradation",
    recommended_operators: list[str] | None = None,
    severity: float = 0.6,
    prevalence: float = 0.4,
    opportunity_id: str | None = None,
) -> OptimizationOpportunity:
    return OptimizationOpportunity(
        opportunity_id=opportunity_id or "opp-test-001",
        created_at=time.time(),
        cluster_id="cluster-1",
        failure_family=failure_family,
        affected_agent_path="root",
        affected_surface_candidates=["system_instructions"],
        severity=severity,
        prevalence=prevalence,
        recency=1.0,
        business_impact=0.5,
        sample_trace_ids=["t1", "t2"],
        recommended_operator_families=recommended_operators or ["instruction_rewrite", "few_shot_edit"],
        priority_score=0.7,
        status="open",
        resolution_experiment_id=None,
    )


def _make_memory(db_path: str | None = None) -> OptimizationMemory:
    """Create an OptimizationMemory backed by a temp file (`:memory:` doesn't persist across connections)."""
    if db_path is None:
        f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        db_path = f.name
        f.close()
    return OptimizationMemory(db_path=db_path)


def _make_engine(
    memory: OptimizationMemory | None = None,
    tracker: OperatorPerformanceTracker | None = None,
    budget: SearchBudget | None = None,
) -> SearchEngine:
    registry = create_default_registry()
    mem = memory or _make_memory()
    proposer = Proposer(use_mock=True)
    return SearchEngine(
        registry=registry,
        memory=mem,
        proposer=proposer,
        performance_tracker=tracker,
        budget=budget,
    )


def _simple_eval_fn(config: dict) -> dict[str, float]:
    """Eval stub: returns higher scores when quality_boost is present."""
    base = 0.5
    if config.get("quality_boost"):
        base += 0.1
    if config.get("prompts", {}).get("root", ""):
        base += 0.05
    return {"quality": base, "safety": 0.9}


# ---------------------------------------------------------------------------
# OperatorPerformanceTracker tests
# ---------------------------------------------------------------------------


class TestOperatorPerformanceTracker:
    def test_default_success_rate_is_half(self, tmp_path) -> None:
        tracker = OperatorPerformanceTracker(db_path=str(tmp_path / "perf.db"))
        assert tracker.get_success_rate("instruction_rewrite", "quality_degradation") == 0.5

    def test_record_and_retrieve(self, tmp_path) -> None:
        tracker = OperatorPerformanceTracker(db_path=str(tmp_path / "perf.db"))
        tracker.record_outcome("instruction_rewrite", "quality_degradation", True)
        tracker.record_outcome("instruction_rewrite", "quality_degradation", True)
        tracker.record_outcome("instruction_rewrite", "quality_degradation", False)
        rate = tracker.get_success_rate("instruction_rewrite", "quality_degradation")
        assert abs(rate - 2 / 3) < 1e-6

    def test_get_best_operators(self, tmp_path) -> None:
        tracker = OperatorPerformanceTracker(db_path=str(tmp_path / "perf.db"))
        tracker.record_outcome("a", "fam", True)
        tracker.record_outcome("a", "fam", True)
        tracker.record_outcome("b", "fam", True)
        tracker.record_outcome("b", "fam", False)
        tracker.record_outcome("c", "fam", False)
        tracker.record_outcome("c", "fam", False)

        best = tracker.get_best_operators("fam", n=2)
        assert len(best) == 2
        assert best[0][0] == "a"
        assert best[0][1] == 1.0

    def test_get_best_operators_empty(self, tmp_path) -> None:
        tracker = OperatorPerformanceTracker(db_path=str(tmp_path / "perf.db"))
        assert tracker.get_best_operators("nonexistent") == []


# ---------------------------------------------------------------------------
# CandidateMutation scoring tests
# ---------------------------------------------------------------------------


class TestCandidateMutationScoring:
    def test_combined_score_formula(self) -> None:
        engine = _make_engine()
        score = engine._combined_score(predicted_lift=0.8, novelty_score=1.0, risk_score=0.1)
        expected = 0.4 * 0.8 + 0.3 * 1.0 + 0.3 * 0.9
        assert abs(score - expected) < 1e-6

    def test_high_risk_lowers_score(self) -> None:
        engine = _make_engine()
        low_risk = engine._combined_score(0.5, 0.5, 0.1)
        high_risk = engine._combined_score(0.5, 0.5, 0.9)
        assert low_risk > high_risk


# ---------------------------------------------------------------------------
# generate_candidates tests
# ---------------------------------------------------------------------------


class TestGenerateCandidates:
    def test_generates_candidates_for_opportunity(self) -> None:
        engine = _make_engine()
        opp = _make_opportunity()
        candidates = engine.generate_candidates([opp], {}, {}, {})
        assert len(candidates) > 0
        assert all(isinstance(c, CandidateMutation) for c in candidates)

    def test_candidates_sorted_by_combined_score(self) -> None:
        engine = _make_engine()
        opp = _make_opportunity()
        candidates = engine.generate_candidates([opp], {}, {}, {})
        scores = [c.combined_score for c in candidates]
        assert scores == sorted(scores, reverse=True)

    def test_skips_unknown_operators(self) -> None:
        engine = _make_engine()
        opp = _make_opportunity(recommended_operators=["nonexistent_op"])
        candidates = engine.generate_candidates([opp], {}, {}, {})
        assert len(candidates) == 0

    def test_deduplicates_against_memory(self) -> None:
        mem = _make_memory()
        # Log a past attempt matching the description key format
        mem.log(OptimizationAttempt(
            attempt_id="past-1",
            timestamp=time.time(),
            change_description="instruction_rewrite::opp-test-001",
            config_diff="{}",
            status="rejected_no_improvement",
        ))
        engine = _make_engine(memory=mem)
        opp = _make_opportunity(recommended_operators=["instruction_rewrite"])
        candidates = engine.generate_candidates([opp], {}, {}, {})
        assert len(candidates) == 0

    def test_budget_caps_candidates(self) -> None:
        budget = SearchBudget(max_candidates=1)
        engine = _make_engine(budget=budget)
        opps = [
            _make_opportunity(opportunity_id=f"opp-{i}", recommended_operators=["instruction_rewrite"])
            for i in range(5)
        ]
        candidates = engine.generate_candidates(opps, {}, {}, {})
        assert len(candidates) <= 1


# ---------------------------------------------------------------------------
# rank_candidates tests
# ---------------------------------------------------------------------------


class TestRankCandidates:
    def test_rank_applies_eval_budget(self) -> None:
        budget = SearchBudget(max_eval_budget=2)
        engine = _make_engine(budget=budget)
        candidates = [
            CandidateMutation(
                mutation_id=f"m{i}",
                operator_name="instruction_rewrite",
                target_opportunity_id=None,
                predicted_lift=0.5,
                risk_score=0.1,
                novelty_score=0.8,
                combined_score=i * 0.1,
                config_params={},
                hypothesis="test",
            )
            for i in range(5)
        ]
        ranked = engine.rank_candidates(candidates)
        assert len(ranked) == 2
        assert ranked[0].combined_score >= ranked[1].combined_score


# ---------------------------------------------------------------------------
# evaluate_candidate tests
# ---------------------------------------------------------------------------


class TestEvaluateCandidate:
    def test_evaluate_returns_experiment_card(self) -> None:
        engine = _make_engine()
        candidate = CandidateMutation(
            mutation_id="eval-1",
            operator_name="instruction_rewrite",
            target_opportunity_id=None,
            predicted_lift=0.5,
            risk_score=0.1,
            novelty_score=0.8,
            combined_score=0.6,
            config_params={"target": "root", "text": "Be helpful."},
            hypothesis="Improve root prompt",
        )
        card = engine.evaluate_candidate(candidate, {}, _simple_eval_fn)
        assert isinstance(card, ExperimentCard)
        assert card.operator_name == "instruction_rewrite"
        assert card.status in ("accepted", "rejected")

    def test_evaluate_unknown_operator_raises(self) -> None:
        engine = _make_engine()
        candidate = CandidateMutation(
            mutation_id="bad-1",
            operator_name="nonexistent",
            target_opportunity_id=None,
            predicted_lift=0.5,
            risk_score=0.1,
            novelty_score=0.8,
            combined_score=0.6,
            config_params={},
            hypothesis="Should fail",
        )
        try:
            engine.evaluate_candidate(candidate, {}, _simple_eval_fn)
            assert False, "Expected ValueError"
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# search_cycle tests
# ---------------------------------------------------------------------------


class TestSearchCycle:
    def test_full_cycle_returns_search_result(self) -> None:
        engine = _make_engine()
        opp = _make_opportunity()
        result = engine.search_cycle([opp], {}, _simple_eval_fn, {}, {})
        assert isinstance(result, SearchResult)
        assert result.candidates_generated > 0
        assert result.candidates_evaluated > 0
        assert isinstance(result.accepted, list)
        assert isinstance(result.rejected, list)

    def test_cost_budget_respected(self) -> None:
        budget = SearchBudget(max_cost_dollars=0.001, max_eval_budget=10)
        engine = _make_engine(budget=budget)
        opp = _make_opportunity()
        result = engine.search_cycle([opp], {}, _simple_eval_fn, {}, {})
        assert result.total_cost <= budget.max_cost_dollars + 0.05  # small tolerance for single eval

    def test_empty_opportunities_returns_zero(self) -> None:
        engine = _make_engine()
        result = engine.search_cycle([], {}, _simple_eval_fn, {}, {})
        assert result.candidates_generated == 0
        assert result.candidates_evaluated == 0

    def test_performance_tracker_updated(self) -> None:
        tracker = OperatorPerformanceTracker()
        engine = _make_engine(tracker=tracker)
        opp = _make_opportunity(
            failure_family="quality_degradation",
            recommended_operators=["instruction_rewrite"],
        )
        engine.search_cycle([opp], {}, _simple_eval_fn, {}, {})
        # The tracker should have at least one recorded outcome
        rate = tracker.get_success_rate("instruction_rewrite", "quality_degradation")
        assert rate != 0.5  # Changed from default


# ---------------------------------------------------------------------------
# SearchBudget defaults
# ---------------------------------------------------------------------------


class TestSearchBudget:
    def test_defaults(self) -> None:
        b = SearchBudget()
        assert b.max_candidates == 10
        assert b.max_eval_budget == 5
        assert b.max_cost_dollars == 1.0
        assert b.time_budget_seconds == 300.0


# ---------------------------------------------------------------------------
# OperatorPerformanceTracker persistence tests
# ---------------------------------------------------------------------------


class TestOperatorPerformanceTrackerPersistence:
    def test_db_file_is_created(self, tmp_path) -> None:
        db_path = str(tmp_path / "tracker.db")
        OperatorPerformanceTracker(db_path=db_path)
        assert (tmp_path / "tracker.db").exists()

    def test_persists_across_instances(self, tmp_path) -> None:
        db_path = str(tmp_path / "tracker.db")

        # First instance: record some outcomes
        tracker1 = OperatorPerformanceTracker(db_path=db_path)
        tracker1.record_outcome("instruction_rewrite", "quality_degradation", True)
        tracker1.record_outcome("instruction_rewrite", "quality_degradation", True)
        tracker1.record_outcome("instruction_rewrite", "quality_degradation", False)

        # Second instance: load from the same DB and verify data is intact
        tracker2 = OperatorPerformanceTracker(db_path=db_path)
        rate = tracker2.get_success_rate("instruction_rewrite", "quality_degradation")
        assert abs(rate - 2 / 3) < 1e-6

    def test_persists_multiple_keys(self, tmp_path) -> None:
        db_path = str(tmp_path / "tracker.db")

        tracker1 = OperatorPerformanceTracker(db_path=db_path)
        tracker1.record_outcome("op_a", "fam_x", True)
        tracker1.record_outcome("op_a", "fam_x", True)
        tracker1.record_outcome("op_b", "fam_x", False)
        tracker1.record_outcome("op_a", "fam_y", True)

        tracker2 = OperatorPerformanceTracker(db_path=db_path)
        assert tracker2.get_success_rate("op_a", "fam_x") == 1.0
        assert tracker2.get_success_rate("op_b", "fam_x") == 0.0
        assert tracker2.get_success_rate("op_a", "fam_y") == 1.0
        # Unseen combo still returns default
        assert tracker2.get_success_rate("op_c", "fam_z") == 0.5

    def test_new_records_after_reload_accumulate(self, tmp_path) -> None:
        db_path = str(tmp_path / "tracker.db")

        tracker1 = OperatorPerformanceTracker(db_path=db_path)
        tracker1.record_outcome("instruction_rewrite", "tool_error", True)

        tracker2 = OperatorPerformanceTracker(db_path=db_path)
        tracker2.record_outcome("instruction_rewrite", "tool_error", False)

        # 1 success out of 2 total attempts
        rate = tracker2.get_success_rate("instruction_rewrite", "tool_error")
        assert abs(rate - 0.5) < 1e-6

        # Third instance should see the full history
        tracker3 = OperatorPerformanceTracker(db_path=db_path)
        rate3 = tracker3.get_success_rate("instruction_rewrite", "tool_error")
        assert abs(rate3 - 0.5) < 1e-6

    def test_get_best_operators_after_reload(self, tmp_path) -> None:
        db_path = str(tmp_path / "tracker.db")

        tracker1 = OperatorPerformanceTracker(db_path=db_path)
        tracker1.record_outcome("op_best", "fam", True)
        tracker1.record_outcome("op_best", "fam", True)
        tracker1.record_outcome("op_worst", "fam", False)
        tracker1.record_outcome("op_worst", "fam", False)

        tracker2 = OperatorPerformanceTracker(db_path=db_path)
        best = tracker2.get_best_operators("fam", n=2)
        assert len(best) == 2
        assert best[0][0] == "op_best"
        assert best[0][1] == 1.0
        assert best[1][0] == "op_worst"
        assert best[1][1] == 0.0
