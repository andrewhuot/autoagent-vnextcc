"""Core optimization loop with strategy modes: simple | adaptive | full."""

from __future__ import annotations

import json
import hashlib
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from agent_card.schema import AgentCardModel
    from evals.card_case_generator import CardCaseGenerator
    from evals.coverage_analyzer import CoverageAnalyzer
    from optimizer.improvement_lineage import ImprovementLineageStore

logger = logging.getLogger(__name__)

from agent.config.schema import AgentConfig, config_diff, validate_config
from evals.anti_goodhart import AntiGoodhartConfig, AntiGoodhartGuard
from evals.runner import EvalRunner
from evals.statistics import paired_significance
from observer.metrics import HealthReport
from observer.opportunities import FailureClusterer, OptimizationOpportunity

from data.event_log import EventLog
from .adversarial import AdversarialSimulator
from .cost_tracker import CostTracker
from .gates import Gates, RejectionReason, RejectionRecord, rejection_from_status
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
from .skill_engine import SkillEngine
from .skill_autolearner import SkillAutoLearner


def _top_strategy_explanation() -> "StrategyExplanation | None":
    """Return the top-ranked StrategyExplanation from the proposer's
    last ranking, or None if no ranking has happened yet.

    Read from the proposer's module-level ``_LAST_EXPLANATION`` slot,
    populated as a side effect of each ``Proposer.propose(...)`` call.
    Index 0 is the entry that was applied this cycle, so we pass it
    straight to the ``OptimizationAttempt`` calibration fields.

    The import is local to dodge any circular-import surprises and to
    keep rebind-via-``monkeypatch.setattr(prop_mod, "_LAST_EXPLANATION", ...)``
    semantics working in tests.
    """
    from .proposer import _LAST_EXPLANATION
    if not _LAST_EXPLANATION:
        return None
    return _LAST_EXPLANATION[0]


def _patch_bundle_touches_surface(patch_bundle: dict[str, Any], surface: str) -> bool:
    """Return whether a typed patch declares an operation on an immutable surface."""
    surface_lower = surface.strip().lower()
    for operation in patch_bundle.get("operations", []) or []:
        if not isinstance(operation, dict):
            continue
        component = operation.get("component", {})
        if not isinstance(component, dict):
            continue
        component_type = str(component.get("component_type", "")).lower()
        component_name = str(component.get("name", "")).lower()
        component_path = str(component.get("path", "")).lower()
        if surface_lower in {component_type, component_name} or surface_lower in component_path:
            return True
    return False


@dataclass
class StrategyDiagnostics:
    """Snapshot of latest strategy cycle details."""

    strategy: str
    selected_operator_family: str | None
    pareto_front: list[dict[str, Any]]
    pareto_recommendation_id: str | None
    governance_notes: list[str]
    global_dimensions: dict[str, Any]
    skills_applied: list[str] = None  # Skill IDs applied in this cycle
    proposal_reasoning: str | None = None
    proposal_change_description: str | None = None
    proposal_config_section: str | None = None

    def __post_init__(self):
        if self.skills_applied is None:
            self.skills_applied = []


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
        # Skill engine integration
        skill_engine: SkillEngine | None = None,
        use_skills: bool = False,
        skill_selection_strategy: str = "auto",
        skill_max_candidates: int = 5,
        adversarial_simulator: AdversarialSimulator | None = None,
        skill_autolearner: SkillAutoLearner | None = None,
        auto_learn_skills: bool = True,
        significance_min_pairs: int = 5,
        # Phase 5: LLM-driven optimization integration
        failure_analyzer: Any | None = None,
        reflection_engine: Any | None = None,
        agent_card_markdown: str = "",
        # R2: improvement lineage store (observability; never blocks loop).
        lineage_store: "ImprovementLineageStore | None" = None,
        # R3.6: auto-grow eval cases when coverage is low.
        coverage_analyzer: "CoverageAnalyzer | None" = None,
        card_case_generator: "CardCaseGenerator | None" = None,
        agent_card: "AgentCardModel | None" = None,
        auto_grow_cases: bool = True,
    ) -> None:
        self.eval_runner = eval_runner
        self.memory = memory or OptimizationMemory()
        self.proposer = proposer or Proposer()
        self.gates = gates or Gates()
        self.significance_alpha = significance_alpha
        self.significance_min_effect_size = significance_min_effect_size
        self.significance_iterations = significance_iterations
        self.require_statistical_significance = require_statistical_significance
        self.significance_min_pairs = significance_min_pairs

        # Production controls
        self.cost_tracker = cost_tracker
        self.human_control_store = human_control_store
        self.event_log = event_log
        self.immutable_surfaces: set[str] = set(immutable_surfaces or [])
        self.pro_config = pro_config or ProConfig()

        # Skill engine integration
        self.skill_engine = skill_engine
        self.use_skills = use_skills
        self.skill_selection_strategy = skill_selection_strategy
        self.skill_max_candidates = skill_max_candidates
        self._current_cycle_skills: list[Any] = []  # Track skills used in current cycle
        self.adversarial_simulator = adversarial_simulator
        self.skill_autolearner = skill_autolearner
        self.auto_learn_skills = auto_learn_skills
        self.failure_analyzer = failure_analyzer
        self.reflection_engine = reflection_engine
        self.agent_card_markdown = agent_card_markdown
        # R2: optional lineage store for observability. When None, emission
        # helpers are no-ops. When set, store failures are swallowed so
        # lineage issues cannot crash the optimizer loop.
        self.lineage_store = lineage_store

        # R3.6: auto-grow eval cases when any surface is below coverage
        # threshold. All three dependencies must be present for the hook to
        # fire; otherwise it's a silent no-op.
        self.coverage_analyzer = coverage_analyzer
        self.card_case_generator = card_case_generator
        self.agent_card = agent_card
        self.auto_grow_cases = auto_grow_cases

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
        # Bounded ring buffer of structured rejection records (R1.7) so
        # downstream surfaces (e.g. ``agentlab improve list``) can correlate
        # rejected attempts with the OptimizationAttempt rows persisted to
        # memory via the shared ``attempt_id``.
        self._recent_rejections: deque[RejectionRecord] = deque(maxlen=200)
        self._last_strategy_diagnostics = StrategyDiagnostics(
            strategy=self.search_strategy.value,
            selected_operator_family=None,
            pareto_front=[],
            pareto_recommendation_id=None,
            governance_notes=[],
            global_dimensions={},
            skills_applied=[],
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
        self._last_strategy_diagnostics.proposal_reasoning = None
        self._last_strategy_diagnostics.proposal_change_description = None
        self._last_strategy_diagnostics.proposal_config_section = None

        if self.search_strategy == SearchStrategy.PRO:
            return self._optimize_pro(health_report, current_config, failure_samples)
        if self.search_strategy == SearchStrategy.SIMPLE:
            return self._optimize_simple(health_report, current_config, failure_samples)
        return self._optimize_hybrid(health_report, current_config, failure_samples)

    AXIS_INSTRUCTIONS = "instructions"
    AXIS_GUARDRAILS = "guardrails"
    AXIS_CALLBACKS = "callbacks"
    SUPPORTED_AXES: tuple[str, ...] = (AXIS_INSTRUCTIONS, AXIS_GUARDRAILS, AXIS_CALLBACKS)

    def run_axis_cycle(
        self,
        axis: str,
        health_report: HealthReport,
        current_config: dict,
        failure_samples: list[dict] | None = None,
        *,
        cycle_id: str | None = None,
        estimated_cycle_cost: float = 0.0,
    ) -> tuple[dict | None, str, str]:
        """Run one optimization cycle scoped to a single optimization axis.

        This is the axis-scoped entry point used by the V3 coordinator
        workflow where ``instruction_optimizer``, ``guardrail_optimizer``,
        and ``callback_optimizer`` drive change cards individually.

        Backward compatibility: this method is strictly additive. The
        existing :meth:`optimize` full-pass API is unchanged — callers that
        want to run all axes together continue to call it as before. This
        helper simply delegates to :meth:`optimize` and tags the axis on
        the returned diagnostics so the coordinator can match the cycle
        back to the worker that requested it.

        Returns ``(candidate_config_or_none, status, axis)``. ``status``
        mirrors :meth:`optimize`; ``axis`` echoes the (lowercased,
        normalized) axis label for downstream tracking.
        """
        normalized = str(axis or "").strip().lower()
        if normalized not in self.SUPPORTED_AXES:
            return (
                None,
                f"REJECTED (unsupported_axis): {axis!r} is not one of {self.SUPPORTED_AXES}",
                normalized,
            )

        candidate, status = self.optimize(
            health_report=health_report,
            current_config=current_config,
            failure_samples=failure_samples,
            cycle_id=cycle_id,
            estimated_cycle_cost=estimated_cycle_cost,
        )
        self._last_strategy_diagnostics.proposal_config_section = (
            self._last_strategy_diagnostics.proposal_config_section or normalized
        )
        return candidate, status, normalized

    def get_pareto_snapshot(self) -> dict[str, Any]:
        """Return latest Pareto archive snapshot for detail views."""
        return self.pareto_archive.as_dict()

    def get_strategy_diagnostics(self) -> StrategyDiagnostics:
        """Return latest strategy diagnostics for API/front-end detail views."""
        return self._last_strategy_diagnostics

    # ------------------------------------------------------------------
    # R3.6: auto-grow eval cases on low-coverage surfaces
    # ------------------------------------------------------------------

    def _maybe_auto_grow_cases(self) -> int:
        """Return number of cases generated this cycle (0 if skipped).

        Fires only when:
        - ``auto_grow_cases`` flag is True
        - ``coverage_analyzer``, ``card_case_generator``, ``agent_card`` are set
        - ``coverage_analyzer._last_report`` has been populated by a prior
          ``analyze()`` call (first-cycle bootstrap deferred to follow-up)

        Scope note: generated cases are returned and counted but NOT persisted
        into the workspace case file here. Persistence is a separate concern
        deferred to a follow-up change.
        """
        if not (
            self.auto_grow_cases
            and self.coverage_analyzer is not None
            and self.card_case_generator is not None
            and self.agent_card is not None
        ):
            return 0

        report = getattr(self.coverage_analyzer, "_last_report", None)
        if report is None:
            return 0

        try:
            from evals.card_case_generator import grow_cases_for_surface
        except Exception:
            logger.warning("auto case-grow import failed", exc_info=True)
            return 0

        generated_total = 0
        coverage_by_surface = getattr(report, "coverage_by_surface", {}) or {}
        for surface, frac in coverage_by_surface.items():
            try:
                frac_value = float(frac)
            except (TypeError, ValueError):
                continue
            if frac_value >= 0.30:
                continue
            try:
                new_cases = grow_cases_for_surface(
                    self.card_case_generator,
                    self.agent_card,
                    surface,
                )
                generated_total += len(new_cases)
            except Exception:
                logger.warning(
                    "auto case-grow failed for surface %s", surface, exc_info=True
                )

        if generated_total:
            logger.info(
                "auto-grow: generated %d new cases across low-coverage surfaces",
                generated_total,
            )
        return generated_total

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
        self._current_cycle_skills = []  # Reset for new cycle

        # If skills are enabled, try skill-driven optimization first
        if self.use_skills and self.skill_engine is not None:
            skill_result = self._try_skill_driven_optimization(
                health_report=health_report,
                validated_current=validated_current,
                current_config=current_config,
                failure_samples=normalized_failure_samples,
            )
            if skill_result is not None:
                return skill_result
            # Skill optimization failed - clear skills before falling back to proposer
            self._current_cycle_skills = []

        # Fall back to standard proposer-based optimization
        past_attempts = [
            {
                "change_description": attempt.change_description,
                "config_section": attempt.config_section,
                "status": attempt.status,
                "score_before": attempt.score_before,
                "score_after": attempt.score_after,
                "score_delta": attempt.score_after - attempt.score_before
                if attempt.score_after and attempt.score_before else 0,
            }
            for attempt in self.memory.recent(limit=20)
        ]

        # Enrich with reflection context if available
        reflection_context: dict[str, list[str]] | None = None
        if self.reflection_engine is not None:
            try:
                ctx = self.reflection_engine.get_context_for_next_cycle(limit=5)
                reflection_context = {
                    "recent_reflections": [
                        str(r) for r in ctx.get("recent_reflections", [])
                    ],
                    "patterns": ctx.get("patterns", []),
                }
            except Exception:
                pass

        # R3.6: auto-grow cases on low-coverage surfaces before proposing.
        self._maybe_auto_grow_cases()

        proposal = self.proposer.propose(
            current_config=current_config,
            health_metrics=health_report.metrics.to_dict(),
            failure_samples=normalized_failure_samples,
            failure_buckets=health_report.failure_buckets,
            past_attempts=past_attempts,
            project_memory_context=reflection_context,
        )
        if proposal is None:
            return None, "No proposal generated"

        self._last_strategy_diagnostics.proposal_reasoning = proposal.reasoning
        self._last_strategy_diagnostics.proposal_change_description = proposal.change_description
        self._last_strategy_diagnostics.proposal_config_section = proposal.config_section

        return self._finalize_candidate(
            health_report=health_report,
            validated_current=validated_current,
            candidate_config_raw=proposal.new_config,
            change_description=proposal.change_description,
            config_section=proposal.config_section,
            patch_bundle=proposal.patch_bundle,
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
        self._last_strategy_diagnostics.proposal_reasoning = (
            f"Pro-mode search selected {result.algorithm} after evaluating "
            f"{result.candidates_evaluated} candidates."
        )
        self._last_strategy_diagnostics.proposal_change_description = (
            f"Pro-mode optimization ({result.algorithm}): {result.candidates_evaluated} candidates, best={result.best_score:.4f}"
        )
        self._last_strategy_diagnostics.proposal_config_section = "prompt_optimization"

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

        skill_ids = [skill.id for skill in self._current_cycle_skills] if self._current_cycle_skills else []
        self._last_strategy_diagnostics = StrategyDiagnostics(
            strategy=search_result.strategy,
            selected_operator_family=search_result.operator_family,
            pareto_front=search_result.pareto_front,
            pareto_recommendation_id=search_result.pareto_recommendation_id,
            governance_notes=search_result.governance_notes,
            global_dimensions={},
            skills_applied=skill_ids,
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
        patch_bundle: dict[str, Any] | None = None,
    ) -> tuple[dict | None, str]:
        """Validate, evaluate, gate, significance-check, and log candidate config."""
        # Check immutable surface violations
        if self.immutable_surfaces and candidate_config_raw:
            for surface in self.immutable_surfaces:
                if patch_bundle and _patch_bundle_touches_surface(patch_bundle, surface):
                    self._log_rejected_attempt(
                        health_report=health_report,
                        change_description=change_description,
                        config_section=config_section,
                        rejection_status="rejected_immutable",
                        rejection_reason=f"Mutation touches immutable surface: {surface}",
                    )
                    return None, f"REJECTED (rejected_immutable): Mutation touches immutable surface: {surface}"
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
        adversarial_simulation_details = ""
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
                if significance_n < self.significance_min_pairs:
                    reason = (
                        f"{reason}; significance advisory only "
                        f"(n={significance_n} < min_pairs={self.significance_min_pairs})"
                    )
                elif not significance.is_significant:
                    accepted = False
                    status = "rejected_not_significant"
                    reason = (
                        "Improvement not statistically significant: "
                        f"delta={significance_delta:.6f}, "
                        f"p={significance_p_value:.4f}, n={significance_n}"
                    )

        if accepted and self.adversarial_simulator is not None:
            simulation = self.adversarial_simulator.evaluate_candidate(
                baseline_config=baseline_config,
                candidate_config=candidate_config,
            )
            adversarial_simulation_details = simulation.details
            self._log_event(
                "adversarial_simulation",
                {
                    "passed": simulation.passed,
                    "baseline_pass_rate": simulation.baseline_pass_rate,
                    "candidate_pass_rate": simulation.candidate_pass_rate,
                    "delta": simulation.pass_rate_delta,
                    "conversations": simulation.conversations,
                },
            )
            if not simulation.passed:
                accepted = False
                status = "rejected_adversarial"
                reason = f"Adversarial simulation failed: {simulation.details}"

        # Build skills_applied JSON array from current cycle skills
        skills_applied_json = "[]"
        if self._current_cycle_skills:
            skill_ids = [skill.id for skill in self._current_cycle_skills]
            skills_applied_json = json.dumps(skill_ids)

        _exp = _top_strategy_explanation()
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
            health_context=json.dumps(
                {
                    "metrics": health_report.metrics.to_dict(),
                    "adversarial_simulation": adversarial_simulation_details,
                }
            ),
            skills_applied=skills_applied_json,
            patch_bundle=json.dumps(patch_bundle, sort_keys=True, default=str)
            if patch_bundle is not None
            else "",
            predicted_effectiveness=(_exp.effectiveness if _exp is not None else None),
            strategy_surface=(_exp.surface if _exp is not None else None),
            strategy_name=(_exp.strategy if _exp is not None else None),
        )
        self.memory.log(attempt)

        # R2: emit attempt event to lineage store (observability).
        self._emit_attempt_lineage(
            attempt_id=attempt.attempt_id,
            status=attempt.status,
            score_before=attempt.score_before,
            score_after=attempt.score_after,
            eval_run_id=getattr(baseline_score, "run_id", None),
        )

        # R1.7: mirror inline gates-evaluate rejections to the structured
        # ring buffer so they can be surfaced via Optimizer.recent_rejections.
        if not accepted:
            try:
                rejection_reason_enum = rejection_from_status(status)
            except ValueError:
                rejection_reason_enum = RejectionReason.GATE_FAILED
            self._recent_rejections.append(
                RejectionRecord(
                    attempt_id=attempt.attempt_id,
                    reason=rejection_reason_enum,
                    detail=reason,
                    baseline_score=baseline_score.composite,
                    candidate_score=candidate_score.composite,
                    metadata={
                        "config_section": config_section,
                        "status": status,
                    },
                )
            )
            # R2: emit rejection event to lineage store.
            self._emit_rejection_lineage(
                attempt_id=attempt.attempt_id,
                reason=rejection_reason_enum,
                detail=reason,
            )

        # Reflection: analyze why the attempt succeeded or failed
        if self.reflection_engine is not None:
            try:
                reflection = self.reflection_engine.reflect(
                    attempt={
                        "attempt_id": attempt.attempt_id,
                        "status": attempt.status,
                        "change_description": attempt.change_description,
                        "config_section": attempt.config_section,
                        "score_before": attempt.score_before,
                        "score_after": attempt.score_after,
                    },
                    proposal_reasoning=self._last_strategy_diagnostics.proposal_reasoning or "",
                    failure_context=change_description,
                    agent_card_markdown=self.agent_card_markdown,
                )
                self._log_event("reflection_completed", {
                    "attempt_id": attempt.attempt_id,
                    "outcome": reflection.outcome,
                    "score_delta": reflection.score_delta,
                    "confidence": reflection.confidence,
                })
            except Exception:
                pass  # Don't let reflection failures block the loop

        if accepted and self.auto_learn_skills and self.skill_autolearner is not None:
            dominant_failure = self._get_dominant_failure_family(health_report.failure_buckets)
            improvement = candidate_score.composite - baseline_score.composite
            draft_skill_id = self.skill_autolearner.learn_from_accepted_attempt(
                attempt_id=attempt.attempt_id,
                change_description=change_description,
                config_section=config_section,
                config_diff=diff_str,
                improvement=improvement,
                failure_family=dominant_failure,
            )
            if draft_skill_id:
                reason = f"{reason}; draft_skill_created={draft_skill_id}"
                self._log_event(
                    "skill_draft_created",
                    {
                        "attempt_id": attempt.attempt_id,
                        "draft_skill_id": draft_skill_id,
                        "config_section": config_section,
                        "improvement": improvement,
                    },
                )

        if accepted:
            return candidate_config, f"ACCEPTED: {reason}"
        return None, f"REJECTED ({status}): {reason}"

    # ------------------------------------------------------------------
    # Skill-driven optimization
    # ------------------------------------------------------------------

    def _try_skill_driven_optimization(
        self,
        *,
        health_report: HealthReport,
        validated_current: AgentConfig,
        current_config: dict,
        failure_samples: list[dict],
    ) -> tuple[dict | None, str] | None:
        """Attempt skill-driven optimization. Returns None if no skills apply.

        This method:
        1. Identifies the dominant failure family from failure samples
        2. Selects relevant skills based on failure family and metrics
        3. Generates proposals from skills
        4. Evaluates the best proposal
        5. Records outcome for skill learning

        Returns:
            Tuple of (config, status) if skill optimization succeeds, None otherwise.
        """
        if self.skill_engine is None:
            return None

        # Determine dominant failure family
        failure_family = self._get_dominant_failure_family(health_report.failure_buckets)

        # Select relevant skills
        metrics = health_report.metrics.to_dict()
        skills = self.skill_engine.select_skills(
            failure_family=failure_family,
            metrics=metrics,
            max_skills=self.skill_max_candidates,
        )

        if not skills:
            self._log_event("skill_selection", {"failure_family": failure_family, "selected_count": 0})
            return None

        self._current_cycle_skills = skills
        skill_ids = [skill.id for skill in skills]
        self._log_event("skill_selection", {
            "failure_family": failure_family,
            "selected_count": len(skills),
            "skill_ids": skill_ids,
        })

        # Generate proposals from skills
        context = {
            "failure_family": failure_family,
            "metrics": metrics,
            "failure_samples": failure_samples[:5],  # Limit context size
        }

        proposals = self.skill_engine.propose_from_skills(skills, current_config, context)

        if not proposals:
            self._log_event("skill_proposals", {"proposal_count": 0})
            return None

        self._log_event("skill_proposals", {"proposal_count": len(proposals)})

        # Evaluate proposals and pick the best one
        best_config = None
        best_score = -float('inf')
        best_skill_idx = 0

        # Use validated config for baseline evaluation
        baseline_config_dict = validated_current.model_dump(mode="python")
        baseline_score = self.eval_runner.run(config=baseline_config_dict)

        for idx, proposal_config in enumerate(proposals):
            try:
                candidate_score = self.eval_runner.run(config=proposal_config)
                if candidate_score.composite > best_score:
                    best_score = candidate_score.composite
                    best_config = proposal_config
                    best_skill_idx = idx
            except Exception as e:
                # Skip invalid proposals
                continue

        if best_config is None:
            return None

        # Calculate which skill this proposal came from
        # Note: This is a simplification - in reality we'd track per-proposal
        skill_idx = best_skill_idx % len(skills)
        applied_skill = skills[skill_idx]

        # Check if improvement is sufficient
        improvement = best_score - baseline_score.composite
        success = improvement > self.significance_min_effect_size

        # Learn from outcome
        self.skill_engine.learn_from_outcome(applied_skill, improvement, success)

        if not success:
            self._log_event("skill_optimization", {
                "skill_id": applied_skill.id,
                "improvement": improvement,
                "success": False,
            })
            return None

        # Finalize the candidate
        self._log_event("skill_optimization", {
            "skill_id": applied_skill.id,
            "improvement": improvement,
            "success": True,
        })

        # Update diagnostics to include applied skills
        skill_ids = [skill.id for skill in skills]
        self._last_strategy_diagnostics = StrategyDiagnostics(
            strategy=self.search_strategy.value,
            selected_operator_family=None,
            pareto_front=[],
            pareto_recommendation_id=None,
            governance_notes=[],
            global_dimensions={},
            skills_applied=skill_ids,
        )

        return self._finalize_candidate(
            health_report=health_report,
            validated_current=validated_current,
            candidate_config_raw=best_config,
            change_description=f"Skill-driven: {applied_skill.name} (improvement={improvement:.4f})",
            config_section="skill_optimization",
        )

    def _get_dominant_failure_family(self, failure_buckets: dict[str, int]) -> str | None:
        """Extract the dominant failure family from failure buckets.

        Args:
            failure_buckets: Dict mapping failure families to counts.

        Returns:
            The failure family with the highest count, or None if empty.
        """
        if not failure_buckets:
            return None
        return max(failure_buckets.items(), key=lambda x: x[1])[0]

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

    def _emit_attempt_lineage(
        self,
        *,
        attempt_id: str,
        status: str,
        score_before: float | None = None,
        score_after: float | None = None,
        eval_run_id: str | None = None,
    ) -> None:
        """Emit an ``attempt`` event to the lineage store. Guarded: never raises."""
        if self.lineage_store is None:
            return
        try:
            self.lineage_store.record_attempt(
                attempt_id=attempt_id,
                status=status,
                score_before=score_before,
                score_after=score_after,
                eval_run_id=eval_run_id,
            )
        except Exception:
            pass

    def _emit_rejection_lineage(
        self,
        *,
        attempt_id: str,
        reason: RejectionReason,
        detail: str,
    ) -> None:
        """Emit a ``rejection`` event. Guarded: never raises."""
        if self.lineage_store is None:
            return
        try:
            self.lineage_store.record_rejection(
                attempt_id=attempt_id,
                reason=reason.value,
                detail=detail,
            )
        except Exception:
            pass

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
        """Persist a rejected attempt with a standardized record shape.

        Also appends a structured :class:`RejectionRecord` to the bounded
        ``self._recent_rejections`` ring buffer so downstream surfaces can
        correlate it with the persisted ``OptimizationAttempt`` via the
        shared ``attempt_id``.
        """
        # Build skills_applied JSON array from current cycle skills
        skills_applied_json = "[]"
        if self._current_cycle_skills:
            skill_ids = [skill.id for skill in self._current_cycle_skills]
            skills_applied_json = json.dumps(skill_ids)

        # Generate the attempt id once and reuse it for both the persisted
        # OptimizationAttempt and the in-memory RejectionRecord so callers
        # can join them.
        attempt_id = str(uuid.uuid4())[:8]

        _exp = _top_strategy_explanation()
        attempt = OptimizationAttempt(
            attempt_id=attempt_id,
            timestamp=time.time(),
            change_description=change_description,
            config_diff=config_diff or rejection_reason,
            status=rejection_status,
            config_section=config_section,
            health_context=json.dumps(health_report.metrics.to_dict()),
            skills_applied=skills_applied_json,
            predicted_effectiveness=(_exp.effectiveness if _exp is not None else None),
            strategy_surface=(_exp.surface if _exp is not None else None),
            strategy_name=(_exp.strategy if _exp is not None else None),
        )
        self.memory.log(attempt)

        # R2: emit attempt event to lineage store (observability).
        self._emit_attempt_lineage(
            attempt_id=attempt_id,
            status=rejection_status,
        )

        # Mirror to the structured rejection ring buffer (R1.7).
        try:
            reason = rejection_from_status(rejection_status)
        except ValueError:
            # Defensive: not a rejection status — should not happen here,
            # but fall back to GATE_FAILED rather than crashing the loop.
            reason = RejectionReason.GATE_FAILED
        self._recent_rejections.append(
            RejectionRecord(
                attempt_id=attempt_id,
                reason=reason,
                detail=rejection_reason,
                baseline_score=None,
                candidate_score=None,
                metadata={
                    "config_section": config_section,
                    "status": rejection_status,
                },
            )
        )

        # R2: emit rejection event to lineage store.
        self._emit_rejection_lineage(
            attempt_id=attempt_id,
            reason=reason,
            detail=rejection_reason,
        )

    def recent_rejections(
        self, limit: int | None = None
    ) -> list[RejectionRecord]:
        """Return recent structured rejection records, newest first.

        Args:
            limit: Optional cap on the number of records returned. ``None``
                returns all buffered records.
        """
        ordered = list(reversed(self._recent_rejections))
        if limit is None:
            return ordered
        return ordered[:limit]

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
