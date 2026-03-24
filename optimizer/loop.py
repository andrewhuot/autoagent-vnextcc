"""Core optimization loop with strategy modes: simple | adaptive | full."""

from __future__ import annotations

import json
import hashlib
import time
import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from agent.config.schema import AgentConfig, config_diff, validate_config
from evals.anti_goodhart import AntiGoodhartConfig, AntiGoodhartGuard
from evals.runner import EvalRunner, TestCase
from evals.statistics import paired_significance
from observer.metrics import HealthReport
from observer.opportunities import FailureClusterer, OptimizationOpportunity

from data.event_log import EventLog
from .cost_tracker import CostTracker
from .gates import Gates
from .human_control import HumanControlStore
from .memory import OptimizationAttempt, OptimizationMemory
from .mutations import create_default_registry
from .pareto import ConstrainedParetoArchive, ObjectiveDirection
from .proposer import Proposer
from .prompt_opt import ProConfig, ProSearchStrategy
from .search import (
    BanditPolicy,
    HybridBanditSelector,
    HybridSearchOrchestrator,
    SearchBudget,
    SearchResult,
    SearchStrategy,
)


@dataclass
class StrategyDiagnostics:
    """Snapshot of latest strategy cycle details."""

    strategy: str
    selected_operator_family: str | None
    pareto_front: list[dict[str, Any]]
    pareto_recommendation_id: str | None
    governance_notes: list[str]
    global_dimensions: dict[str, Any]


class Optimizer:
    """Runs one optimization cycle and returns (new_config_or_none, status)."""

    def __init__(
        self,
        eval_runner: EvalRunner,
        memory: OptimizationMemory | None = None,
        proposer: Proposer | None = None,
        gates: Gates | None = None,
        significance_alpha: float = 0.05,
        significance_min_effect_size: float = 0.005,
        significance_iterations: int = 2000,
        require_statistical_significance: bool = True,
        search_strategy: str = SearchStrategy.SIMPLE.value,
        bandit_policy: str = BanditPolicy.THOMPSON.value,
        search_budget: SearchBudget | None = None,
        anti_goodhart_config: AntiGoodhartConfig | None = None,
        # Production controls (from R2 simplicity thesis)
        cost_tracker: CostTracker | None = None,
        human_control_store: HumanControlStore | None = None,
        event_log: EventLog | None = None,
        immutable_surfaces: list[str] | None = None,
        pro_config: ProConfig | None = None,
    ) -> None:
        self.eval_runner = eval_runner
        self.memory = memory or OptimizationMemory()
        self.proposer = proposer or Proposer(use_mock=True)
        self.gates = gates or Gates()
        self.significance_alpha = significance_alpha
        self.significance_min_effect_size = significance_min_effect_size
        self.significance_iterations = significance_iterations
        self.require_statistical_significance = require_statistical_significance

        # Production controls
        self.cost_tracker = cost_tracker
        self.human_control_store = human_control_store
        self.event_log = event_log
        self.immutable_surfaces: set[str] = set(immutable_surfaces or [])
        self.pro_config = pro_config or ProConfig()

        try:
            self.search_strategy = SearchStrategy(search_strategy)
        except ValueError:
            self.search_strategy = SearchStrategy.SIMPLE

        try:
            policy = BanditPolicy(bandit_policy)
        except ValueError:
            policy = BanditPolicy.THOMPSON

        self.search_budget = search_budget or SearchBudget()
        self.pareto_archive = ConstrainedParetoArchive(
            objective_directions={
                "quality": ObjectiveDirection.MAXIMIZE,
                "safety": ObjectiveDirection.MAXIMIZE,
                "latency": ObjectiveDirection.MAXIMIZE,
                "cost": ObjectiveDirection.MAXIMIZE,
            }
        )
        self.hso = HybridSearchOrchestrator(
            bandit_selector=HybridBanditSelector(policy=policy),
            pareto_archive=self.pareto_archive,
        )
        self.failure_clusterer = FailureClusterer()
        self.anti_goodhart = AntiGoodhartGuard(anti_goodhart_config)
        self._rolling_holdout_offset = 0
        self._last_strategy_diagnostics = StrategyDiagnostics(
            strategy=self.search_strategy.value,
            selected_operator_family=None,
            pareto_front=[],
            pareto_recommendation_id=None,
            governance_notes=[],
            global_dimensions={},
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def optimize(
        self,
        health_report: HealthReport,
        current_config: dict,
        failure_samples: list[dict] | None = None,
        *,
        cycle_id: str | None = None,
        estimated_cycle_cost: float = 0.0,
    ) -> tuple[dict | None, str]:
        """Run one optimization cycle with configured strategy.

        Production gates (checked before any work):
        1. Human pause — if paused, return immediately
        2. Budget gate — if over budget, return immediately
        3. Immutable surfaces — refreshed from human_control_store
        4. Event logging — every significant action gets logged
        """
        # Gate 1: Human pause check
        if self.human_control_store is not None:
            state = self.human_control_store.get_state()
            if state.paused:
                self._log_event("human_pause", {"reason": "optimizer_paused_by_human"}, cycle_id=cycle_id)
                return None, "PAUSED: Human pause override is active"
            # Refresh immutable surfaces from persistent state
            self.immutable_surfaces = set(state.immutable_surfaces)

        # Gate 2: Budget check
        if self.cost_tracker is not None and estimated_cycle_cost > 0:
            can_spend, reason = self.cost_tracker.can_start_cycle(estimated_cycle_cost)
            if not can_spend:
                self._log_event("budget_exceeded", {"reason": reason}, cycle_id=cycle_id)
                return None, f"BUDGET_EXCEEDED: {reason}"

        # Gate 3: Stall detection
        if self.cost_tracker is not None and self.cost_tracker.should_pause_for_stall():
            self._log_event("stall_detected", {"reason": "diminishing_returns"}, cycle_id=cycle_id)
            return None, "STALL_DETECTED: No improvement over recent cycles"

        self._log_event("mutation_proposed", {"strategy": self.search_strategy.value}, cycle_id=cycle_id)

        if self.search_strategy == SearchStrategy.PRO:
            return self._optimize_pro(health_report, current_config, failure_samples)
        if self.search_strategy == SearchStrategy.SIMPLE:
            return self._optimize_simple(health_report, current_config, failure_samples)
        return self._optimize_hybrid(health_report, current_config, failure_samples)

    def get_pareto_snapshot(self) -> dict[str, Any]:
        """Return latest Pareto archive snapshot for detail views."""
        return self.pareto_archive.as_dict()

    def get_strategy_diagnostics(self) -> StrategyDiagnostics:
        """Return latest strategy diagnostics for API/front-end detail views."""
        return self._last_strategy_diagnostics

    # ------------------------------------------------------------------
    # Simple strategy (preserved behavior)
    # ------------------------------------------------------------------

    def _optimize_simple(
        self,
        health_report: HealthReport,
        current_config: dict,
        failure_samples: list[dict] | None = None,
    ) -> tuple[dict | None, str]:
        validated_current, err = self._validate_current_config(current_config)
        if err is not None or validated_current is None:
            return None, err

        normalized_failure_samples = failure_samples or []
        past_attempts = [
            {
                "change_description": attempt.change_description,
                "config_section": attempt.config_section,
                "status": attempt.status,
            }
            for attempt in self.memory.recent(limit=20)
        ]

        proposal = self.proposer.propose(
            current_config=current_config,
            health_metrics=health_report.metrics.to_dict(),
            failure_samples=normalized_failure_samples,
            failure_buckets=health_report.failure_buckets,
            past_attempts=past_attempts,
        )
        if proposal is None:
            return None, "No proposal generated"

        return self._finalize_candidate(
            health_report=health_report,
            validated_current=validated_current,
            candidate_config_raw=proposal.new_config,
            change_description=proposal.change_description,
            config_section=proposal.config_section,
        )

    # ------------------------------------------------------------------
    # Pro strategy (research-grade prompt optimization)
    # ------------------------------------------------------------------

    def _optimize_pro(
        self,
        health_report: HealthReport,
        current_config: dict,
        failure_samples: list[dict] | None = None,
    ) -> tuple[dict | None, str]:
        """Run pro-mode prompt optimization."""
        validated_current, err = self._validate_current_config(current_config)
        if err is not None or validated_current is None:
            return None, err

        # Build failure patterns from failure samples
        failure_patterns: list[str] = []
        if failure_samples:
            for sample in failure_samples[:10]:
                if desc := sample.get("failure_description", ""):
                    failure_patterns.append(str(desc))

        from optimizer.providers import LLMRouter, ModelConfig, MockProvider

        # Use a mock LLM router for pro strategy
        mock_config = ModelConfig(provider="mock", model="mock-proposer")
        llm_router = LLMRouter(
            strategy="single",
            models=[mock_config],
            providers={(mock_config.provider, mock_config.model): MockProvider(mock_config)},
        )

        strategy = ProSearchStrategy(
            llm_router=llm_router,
            eval_runner=self.eval_runner,
            config=self.pro_config,
        )

        result = strategy.run(
            current_config=current_config,
            task_description="",
            failure_patterns=failure_patterns,
        )

        if not result.improved or result.best_candidate is None:
            return None, f"REJECTED (pro_no_improvement): Pro-mode found no improvement (best={result.best_score:.4f}, baseline={result.baseline_score:.4f})"

        # Apply the config patch from the optimization result
        patch = result.to_config_patch()
        if not patch:
            return None, "REJECTED (pro_no_patch): Optimization result produced no config changes"

        import copy
        candidate_config = copy.deepcopy(current_config)
        candidate_config.update(patch)

        return self._finalize_candidate(
            health_report=health_report,
            validated_current=validated_current,
            candidate_config_raw=candidate_config,
            change_description=f"Pro-mode optimization ({result.algorithm}): {result.candidates_evaluated} candidates, best={result.best_score:.4f}",
            config_section="prompt_optimization",
        )

    # ------------------------------------------------------------------
    # Adaptive/full strategy
    # ------------------------------------------------------------------

    def _optimize_hybrid(
        self,
        health_report: HealthReport,
        current_config: dict,
        failure_samples: list[dict] | None = None,
    ) -> tuple[dict | None, str]:
        validated_current, err = self._validate_current_config(current_config)
        if err is not None or validated_current is None:
            return None, err

        opportunities = self._build_opportunities(
            failure_samples=failure_samples or [],
            failure_buckets=health_report.failure_buckets,
        )
        if not opportunities:
            # No clustered opportunities: fall back to stable simple path.
            return self._optimize_simple(health_report, current_config, failure_samples)

        selected_opportunities = opportunities
        if self.search_strategy == SearchStrategy.FULL:
            selected_opportunities = self.hso.select_opportunities_with_curriculum(
                opportunities,
                max_items=self.search_budget.max_candidates,
            )

        search_result = self.hso.run_cycle(
            strategy=self.search_strategy,
            registry=create_default_registry(),
            memory=self.memory,
            proposer=self.proposer,
            opportunities=selected_opportunities,
            current_config=current_config,
            budget=self.search_budget,
            eval_fn=self._score_vector_for_search,
        )

        self._last_strategy_diagnostics = StrategyDiagnostics(
            strategy=search_result.strategy,
            selected_operator_family=search_result.operator_family,
            pareto_front=search_result.pareto_front,
            pareto_recommendation_id=search_result.pareto_recommendation_id,
            governance_notes=search_result.governance_notes,
            global_dimensions={},
        )

        selected_experiment_id = self._select_experiment(search_result)
        if selected_experiment_id is None:
            self.hso.record_curriculum_outcome(False)
            return None, "REJECTED (rejected_no_improvement): No accepted hybrid candidates"

        candidate_config = search_result.accepted_configs.get(selected_experiment_id)
        if candidate_config is None:
            self.hso.record_curriculum_outcome(False)
            return None, "REJECTED (rejected_no_improvement): No deployable candidate config"

        baseline_metrics = self._score_vector_for_search(current_config)
        candidate_metrics = self._score_vector_for_search(candidate_config)
        verdict = self.anti_goodhart.evaluate_candidate(
            baseline_metrics=baseline_metrics,
            candidate_metrics=candidate_metrics,
        )
        if not verdict.passed:
            self._log_rejected_attempt(
                health_report=health_report,
                change_description=f"Hybrid candidate {selected_experiment_id}",
                config_section="hybrid_search",
                rejection_status="rejected_constraints",
                rejection_reason="; ".join(verdict.violations),
            )
            self.hso.record_curriculum_outcome(False)
            return None, f"REJECTED (rejected_constraints): {'; '.join(verdict.violations)}"

        result = self._finalize_candidate(
            health_report=health_report,
            validated_current=validated_current,
            candidate_config_raw=candidate_config,
            change_description=f"Hybrid candidate {selected_experiment_id}",
            config_section="hybrid_search",
        )
        self.hso.record_curriculum_outcome(success=result[0] is not None)
        return result

    # ------------------------------------------------------------------
    # Shared candidate finalization logic
    # ------------------------------------------------------------------

    def _finalize_candidate(
        self,
        *,
        health_report: HealthReport,
        validated_current: AgentConfig,
        candidate_config_raw: dict[str, Any],
        change_description: str,
        config_section: str,
    ) -> tuple[dict | None, str]:
        """Validate, evaluate, gate, significance-check, and log candidate config."""
        # Check immutable surface violations
        if self.immutable_surfaces and candidate_config_raw:
            for surface in self.immutable_surfaces:
                if surface in str(candidate_config_raw):
                    self._log_rejected_attempt(
                        health_report=health_report,
                        change_description=change_description,
                        config_section=config_section,
                        rejection_status="rejected_immutable",
                        rejection_reason=f"Mutation touches immutable surface: {surface}",
                    )
                    return None, f"REJECTED (rejected_immutable): Mutation touches immutable surface: {surface}"

        try:
            validated_new = validate_config(candidate_config_raw)
        except Exception as exc:
            self._log_rejected_attempt(
                health_report=health_report,
                change_description=change_description,
                config_section=config_section,
                rejection_status="rejected_invalid",
                rejection_reason=f"Invalid config: {exc}",
            )
            return None, f"Invalid config: {exc}"

        baseline_config = validated_current.model_dump(mode="python")
        candidate_config = validated_new.model_dump(mode="python")
        diff_str = config_diff(validated_current, validated_new)
        if diff_str == "No changes.":
            self._log_rejected_attempt(
                health_report=health_report,
                change_description=change_description,
                config_section=config_section,
                rejection_status="rejected_noop",
                rejection_reason="No changes.",
                config_diff=diff_str,
            )
            return None, "REJECTED (rejected_noop): Proposal did not change config"

        baseline_score = self.eval_runner.run(config=baseline_config)
        candidate_score = self.eval_runner.run(config=candidate_config)

        self._last_strategy_diagnostics.global_dimensions = dict(
            candidate_score.global_dimensions
        )

        accepted, status, reason = self.gates.evaluate(candidate_score, baseline_score)

        significance_p_value = 1.0
        significance_delta = 0.0
        significance_n = 0
        if accepted and self.require_statistical_significance:
            baseline_values = [self._case_composite(result) for result in baseline_score.results]
            candidate_values = [self._case_composite(result) for result in candidate_score.results]
            if baseline_values and candidate_values:
                significance = paired_significance(
                    baseline_values,
                    candidate_values,
                    alpha=self.significance_alpha,
                    min_effect_size=self.significance_min_effect_size,
                    iterations=self.significance_iterations,
                )
                significance_p_value = significance.p_value
                significance_delta = significance.observed_delta
                significance_n = significance.n_pairs
                if not significance.is_significant:
                    accepted = False
                    status = "rejected_not_significant"
                    reason = (
                        "Improvement not statistically significant: "
                        f"delta={significance_delta:.6f}, "
                        f"p={significance_p_value:.4f}, n={significance_n}"
                    )

        attempt = OptimizationAttempt(
            attempt_id=str(uuid.uuid4())[:8],
            timestamp=time.time(),
            change_description=change_description,
            config_diff=diff_str,
            status=status,
            config_section=config_section,
            score_before=baseline_score.composite,
            score_after=candidate_score.composite,
            significance_p_value=significance_p_value,
            significance_delta=significance_delta,
            significance_n=significance_n,
            health_context=json.dumps(health_report.metrics.to_dict()),
        )
        self.memory.log(attempt)

        if accepted:
            return candidate_config, f"ACCEPTED: {reason}"
        return None, f"REJECTED ({status}): {reason}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_current_config(current_config: dict) -> tuple[AgentConfig | None, str | None]:
        """Validate current config and return either schema object or error."""
        try:
            return validate_config(current_config), None
        except Exception as exc:  # pragma: no cover - defensive branch
            return None, f"Current config invalid: {exc}"

    def _build_opportunities(
        self,
        *,
        failure_samples: list[dict[str, Any]],
        failure_buckets: dict[str, int],
    ) -> list[OptimizationOpportunity]:
        """Convert failure buckets into ranked opportunities for hybrid search."""
        records = []
        for index, sample in enumerate(failure_samples, start=1):
            records.append(
                SimpleNamespace(
                    conversation_id=f"sample-{index}",
                    specialist_used=str(sample.get("specialist_used", "")),
                )
            )
        return self.failure_clusterer.cluster(records, failure_buckets)

    def _score_vector_for_search(self, config: dict[str, Any]) -> dict[str, float]:
        """Produce a metric vector used by HSO selection + anti-Goodhart checks."""
        main_score = self.eval_runner.run(config=config)
        fixed_score, rolling_score = self._run_holdout_scores(config)
        judge_scores = [float(result.quality_score) for result in main_score.results]

        vector = {
            "quality": main_score.quality,
            "safety": main_score.safety,
            "latency": main_score.latency,
            "cost": main_score.cost,
            "composite": main_score.composite,
            "fixed_holdout_composite": fixed_score,
            "rolling_holdout_composite": rolling_score,
            "routing_accuracy": float(main_score.global_dimensions.get("routing_accuracy", 0.0)),
            "handoff_fidelity": float(main_score.global_dimensions.get("handoff_fidelity", 0.0)),
            "user_satisfaction_proxy": float(
                main_score.global_dimensions.get("user_satisfaction_proxy", 0.0)
            ),
            "judge_scores": judge_scores,
        }
        return vector

    def _run_holdout_scores(self, config: dict[str, Any]) -> tuple[float, float]:
        """Run fixed and rotating holdout slices for anti-Goodhart checks."""
        all_cases = self.eval_runner.load_cases()
        if not all_cases:
            score = self.eval_runner.run(config=config).composite
            return score, score

        fixed_cases = [case for case in all_cases if self._stable_hash_bucket(case.id) % 5 == 0]
        rolling_pool = [case for case in all_cases if case not in fixed_cases]
        if not fixed_cases:
            fixed_cases = list(all_cases[: max(1, len(all_cases) // 5)])
        if not rolling_pool:
            rolling_pool = list(all_cases)

        window_size = max(1, len(rolling_pool) // 5)
        start = (self._rolling_holdout_offset * window_size) % len(rolling_pool)
        rolling_cases = [
            rolling_pool[(start + offset) % len(rolling_pool)] for offset in range(window_size)
        ]
        self._rolling_holdout_offset += 1

        fixed_composite = self.eval_runner.run_cases(
            fixed_cases,
            config=config,
            category="fixed_holdout",
            split="holdout",
        ).composite
        rolling_composite = self.eval_runner.run_cases(
            rolling_cases,
            config=config,
            category="rolling_holdout",
            split="holdout",
        ).composite
        return fixed_composite, rolling_composite

    @staticmethod
    def _stable_hash_bucket(value: str) -> int:
        """Stable integer hash bucket for deterministic holdout partitioning."""
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        return int(digest[:8], 16)

    @staticmethod
    def _select_experiment(search_result: SearchResult) -> str | None:
        """Select best experiment from search result (Pareto recommendation first)."""
        if (
            search_result.pareto_recommendation_id
            and search_result.pareto_recommendation_id in search_result.accepted_configs
        ):
            return search_result.pareto_recommendation_id
        if not search_result.accepted:
            return None
        best_card = max(search_result.accepted, key=lambda card: card.significance_delta)
        return best_card.experiment_id

    def _log_rejected_attempt(
        self,
        *,
        health_report: HealthReport,
        change_description: str,
        config_section: str,
        rejection_status: str,
        rejection_reason: str,
        config_diff: str | None = None,
    ) -> None:
        """Persist a rejected attempt with a standardized record shape."""
        attempt = OptimizationAttempt(
            attempt_id=str(uuid.uuid4())[:8],
            timestamp=time.time(),
            change_description=change_description,
            config_diff=config_diff or rejection_reason,
            status=rejection_status,
            config_section=config_section,
            health_context=json.dumps(health_report.metrics.to_dict()),
        )
        self.memory.log(attempt)

    def set_immutable_surfaces(self, surfaces: list[str]) -> None:
        """Update immutable surfaces from human control state."""
        self.immutable_surfaces = set(surfaces)

    def _log_event(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        cycle_id: str | None = None,
        experiment_id: str | None = None,
    ) -> None:
        """Log event to the append-only event log if available."""
        if self.event_log is not None:
            try:
                self.event_log.append(
                    event_type=event_type,
                    payload=payload,
                    cycle_id=cycle_id,
                    experiment_id=experiment_id,
                )
            except (ValueError, Exception):
                pass  # Don't let event logging failures block optimization

    @staticmethod
    def _case_composite(result) -> float:
        """Approximate per-case composite score for paired significance testing."""
        latency_score = max(0.0, min(1.0, 1.0 - (float(result.latency_ms) / 5000.0)))
        cost_score = max(0.0, min(1.0, 1.0 - (float(result.token_count) / 2000.0)))
        safety_score = 1.0 if bool(result.safety_passed) else 0.0
        return (
            0.40 * float(result.quality_score)
            + 0.25 * safety_score
            + 0.20 * latency_score
            + 0.15 * cost_score
        )
