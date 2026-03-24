"""Multi-hypothesis search engine for optimization candidates.

Generates, ranks, and evaluates candidate mutations by combining operator
performance history, novelty scoring against past attempts, and risk-adjusted
scoring.  Designed to plug into the existing Optimizer loop as an alternative
to the single-shot Proposer path.
"""

from __future__ import annotations

import hashlib
import logging
import math
import random
import sqlite3
import tempfile
import time
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.types import ArchiveEntry, JudgeVerdict
from observer.opportunities import OptimizationOpportunity
from .experiments import ExperimentCard
from .memory import OptimizationMemory
from .mutations import MutationOperator, MutationRegistry, RiskClass
from .proposer import Proposer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Risk class → numeric score (0–1, higher = riskier)
# ---------------------------------------------------------------------------

_RISK_SCORES: dict[RiskClass, float] = {
    RiskClass.low: 0.1,
    RiskClass.medium: 0.35,
    RiskClass.high: 0.65,
    RiskClass.critical: 0.95,
}


# ---------------------------------------------------------------------------
# Strategy / family enums
# ---------------------------------------------------------------------------


class SearchStrategy(str, Enum):
    """Top-level search strategy selection."""

    SIMPLE = "simple"      # preserve existing deterministic proposer path
    ADAPTIVE = "adaptive"  # HSO + bandit family selection
    FULL = "full"          # HSO + curriculum + Pareto archive


class OperatorFamily(str, Enum):
    """High-level operator families used by HSO."""

    MCTS_EXPLORATION = "mcts_exploration"
    LOCAL_TUNING = "local_tuning"
    DIVERSITY_INJECTION = "diversity_injection"


class BanditPolicy(str, Enum):
    """Bandit policy used for family and arm selection."""

    UCB = "ucb"
    THOMPSON = "thompson"


# Operator-family mapping.  Keep this explicit for predictable behavior.
_OPERATOR_TO_FAMILY: dict[str, OperatorFamily] = {
    "routing_edit": OperatorFamily.MCTS_EXPLORATION,
    "model_swap": OperatorFamily.MCTS_EXPLORATION,
    "callback_patch": OperatorFamily.MCTS_EXPLORATION,
    "generation_settings": OperatorFamily.LOCAL_TUNING,
    "tool_description_edit": OperatorFamily.LOCAL_TUNING,
    "context_caching": OperatorFamily.LOCAL_TUNING,
    "memory_policy": OperatorFamily.LOCAL_TUNING,
    "instruction_rewrite": OperatorFamily.DIVERSITY_INJECTION,
    "few_shot_edit": OperatorFamily.DIVERSITY_INJECTION,
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class StructuredCritique:
    """Structured critique output from judge evaluation of a candidate.

    Aggregates evidence spans, failure reasons, judge verdicts, and
    suggested mutation surfaces for the next optimization cycle.
    """

    evidence_spans: list[str]
    failure_reasons: list[str]
    judge_verdicts: list[JudgeVerdict]
    suggested_surfaces: list[str]


@dataclass
class CandidateMutation:
    """A scored candidate mutation ready for evaluation."""

    mutation_id: str
    operator_name: str
    target_opportunity_id: str | None
    predicted_lift: float  # 0–1 estimated improvement
    risk_score: float  # 0–1, derived from operator risk_class
    novelty_score: float  # 0–1, distance from past attempts
    combined_score: float  # weighted: 0.4*lift + 0.3*novelty + 0.3*(1-risk)
    config_params: dict[str, Any]  # parameters for the mutation operator's apply()
    hypothesis: str
    structured_critique: StructuredCritique | None = None
    branch_from_entry_id: str | None = None  # which archive entry to branch from


def compute_bandit_value(
    expected_lift: float,
    business_impact: float,
    uncertainty: float,
    eval_cost: float,
) -> float:
    """Compute contextual bandit value for candidate prioritisation.

    Formula: expected_lift * business_impact * uncertainty / max(eval_cost, 0.01)

    Higher values indicate candidates worth evaluating first: high expected
    improvement on high-impact surfaces with high uncertainty (exploration
    bonus), normalized by evaluation cost.
    """
    return expected_lift * business_impact * uncertainty / max(eval_cost, 0.01)


@dataclass
class SearchBudget:
    """Resource constraints for a single search cycle."""

    max_candidates: int = 10  # max mutations to generate
    max_eval_budget: int = 5  # max to actually evaluate
    max_cost_dollars: float = 1.0
    time_budget_seconds: float = 300.0


@dataclass
class SearchResult:
    """Outcome of a full search cycle."""

    candidates_generated: int
    candidates_evaluated: int
    accepted: list[ExperimentCard]
    rejected: list[ExperimentCard]
    budget_exhausted: bool
    total_cost: float
    strategy: str = SearchStrategy.SIMPLE.value
    operator_family: str | None = None
    pareto_front: list[dict[str, Any]] = field(default_factory=list)
    pareto_recommendation_id: str | None = None
    accepted_configs: dict[str, dict[str, Any]] = field(default_factory=dict)
    governance_notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Operator performance tracker
# ---------------------------------------------------------------------------


class OperatorPerformanceTracker:
    """Track which mutation operators succeed for which failure families.

    Maintains in-memory success/failure counts keyed by
    ``(operator_name, failure_family)`` and persists them to a SQLite
    database so history survives process restarts.
    """

    def __init__(self, db_path: str = ".autoagent/operator_performance.db") -> None:
        self.db_path = db_path
        self._successes: dict[tuple[str, str], int] = defaultdict(int)
        self._totals: dict[tuple[str, str], int] = defaultdict(int)
        self._init_db()
        self._load()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Create the operator_performance table if it doesn't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS operator_performance (
                    operator_name TEXT NOT NULL,
                    failure_family TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    successes INTEGER NOT NULL DEFAULT 0,
                    total_lift REAL NOT NULL DEFAULT 0.0,
                    last_updated REAL NOT NULL DEFAULT 0.0,
                    PRIMARY KEY (operator_name, failure_family)
                )
                """
            )
            conn.commit()

    def _load(self) -> None:
        """Load persisted operator performance data into the in-memory dicts."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT operator_name, failure_family, attempts, successes FROM operator_performance"
            ).fetchall()
        for operator_name, failure_family, attempts, successes in rows:
            key = (operator_name, failure_family)
            self._totals[key] = attempts
            self._successes[key] = successes

    def _persist(self, operator_name: str, failure_family: str) -> None:
        """Write the current in-memory counts for one key back to SQLite."""
        key = (operator_name, failure_family)
        attempts = self._totals[key]
        successes = self._successes[key]
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO operator_performance
                    (operator_name, failure_family, attempts, successes, total_lift, last_updated)
                VALUES (?, ?, ?, ?, 0.0, ?)
                ON CONFLICT(operator_name, failure_family) DO UPDATE SET
                    attempts = excluded.attempts,
                    successes = excluded.successes,
                    last_updated = excluded.last_updated
                """,
                (operator_name, failure_family, attempts, successes, time.time()),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_outcome(self, operator_name: str, failure_family: str, success: bool) -> None:
        """Record the outcome of applying *operator_name* to *failure_family*."""
        key = (operator_name, failure_family)
        self._totals[key] += 1
        if success:
            self._successes[key] += 1
        self._persist(operator_name, failure_family)

    def get_success_rate(self, operator_name: str, failure_family: str) -> float:
        """Return observed success rate, defaulting to 0.5 for unseen combos."""
        key = (operator_name, failure_family)
        total = self._totals.get(key, 0)
        if total == 0:
            return 0.5
        return self._successes.get(key, 0) / total

    def get_best_operators(
        self, failure_family: str, n: int = 3
    ) -> list[tuple[str, float]]:
        """Return top *n* operators for *failure_family*, sorted by success rate descending.

        Only operators that have been observed at least once for this family
        are included.
        """
        rates: list[tuple[str, float]] = []
        seen_operators: set[str] = set()
        for (op_name, ff), _total in self._totals.items():
            if ff != failure_family:
                continue
            if op_name in seen_operators:
                continue
            seen_operators.add(op_name)
            rates.append((op_name, self.get_success_rate(op_name, ff)))
        rates.sort(key=lambda t: t[1], reverse=True)
        return rates[:n]


# ---------------------------------------------------------------------------
# Search engine
# ---------------------------------------------------------------------------


class SearchEngine:
    """Generate, rank, and evaluate candidate mutations across opportunities.

    Integrates the mutation registry, optimization memory, operator
    performance tracker, and an evaluation function to run a complete
    multi-hypothesis search cycle.
    """

    def __init__(
        self,
        registry: MutationRegistry,
        memory: OptimizationMemory,
        proposer: Proposer,
        performance_tracker: OperatorPerformanceTracker | None = None,
        budget: SearchBudget | None = None,
        bandit_selector: HybridBanditSelector | None = None,
        pareto_archive: object | None = None,
    ) -> None:
        self.registry = registry
        self.memory = memory
        self.proposer = proposer
        self.tracker = performance_tracker or OperatorPerformanceTracker()
        self.budget = budget or SearchBudget()
        self.bandit_selector = bandit_selector or HybridBanditSelector()
        self.pareto_archive = pareto_archive

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_candidates(
        self,
        opportunities: list[OptimizationOpportunity],
        current_config: dict[str, Any],
        health_metrics: dict[str, Any],
        failure_buckets: dict[str, int],
    ) -> list[CandidateMutation]:
        """Generate scored candidate mutations from a set of opportunities.

        For each opportunity:
        1. Look up ``recommended_operator_families``.
        2. Resolve each name to a :class:`MutationOperator` via the registry.
        3. Skip combos already attempted (checked against memory).
        4. Build config params appropriate to the opportunity.
        5. Score and return the top N candidates by ``combined_score``.
        """
        past_descriptions = self._past_change_descriptions()
        candidates: list[CandidateMutation] = []

        for opp in opportunities:
            for op_name in opp.recommended_operator_families:
                operator = self.registry.get(op_name)
                if operator is None:
                    logger.debug("Operator '%s' not found in registry, skipping.", op_name)
                    continue
                if not operator.ready:
                    logger.debug("Operator '%s' is not ready, skipping.", op_name)
                    continue

                # Deduplicate against past failed attempts
                description_key = self._description_key(op_name, opp.opportunity_id)
                if self._already_attempted(description_key, past_descriptions):
                    logger.debug(
                        "Operator '%s' already attempted for opportunity '%s', skipping.",
                        op_name,
                        opp.opportunity_id,
                    )
                    continue

                config_params = self._build_config_params(operator, opp, current_config)
                hypothesis = (
                    f"Applying '{op_name}' to address {opp.failure_family} "
                    f"(severity={opp.severity:.2f}, prevalence={opp.prevalence:.2f})"
                )

                predicted_lift = self._predict_lift(op_name, opp)
                risk_score = _RISK_SCORES.get(operator.risk_class, 0.5)
                novelty_score = self._compute_novelty(description_key, past_descriptions)
                combined = self._combined_score(predicted_lift, novelty_score, risk_score)

                candidate = CandidateMutation(
                    mutation_id=uuid.uuid4().hex[:12],
                    operator_name=op_name,
                    target_opportunity_id=opp.opportunity_id,
                    predicted_lift=round(predicted_lift, 4),
                    risk_score=round(risk_score, 4),
                    novelty_score=round(novelty_score, 4),
                    combined_score=round(combined, 4),
                    config_params=config_params,
                    hypothesis=hypothesis,
                )
                candidates.append(candidate)

            if len(candidates) >= self.budget.max_candidates:
                break

        # Final sort and cap
        candidates.sort(key=lambda c: c.combined_score, reverse=True)
        return candidates[: self.budget.max_candidates]

    def rank_candidates(
        self, candidates: list[CandidateMutation]
    ) -> list[CandidateMutation]:
        """Sort candidates by ``combined_score`` descending and apply budget cap."""
        ranked = sorted(candidates, key=lambda c: c.combined_score, reverse=True)
        return ranked[: self.budget.max_eval_budget]

    def evaluate_candidate(
        self,
        candidate: CandidateMutation,
        current_config: dict[str, Any],
        eval_fn: Callable[[dict[str, Any]], dict[str, float]],
    ) -> ExperimentCard:
        """Evaluate a single candidate mutation.

        1. Apply the mutation operator to *current_config*.
        2. Run *eval_fn* on both baseline and candidate configs.
        3. Return an :class:`ExperimentCard` capturing the result.

        ``eval_fn`` must accept a config dict and return a dict of metric
        name → float score.
        """
        operator = self.registry.get(candidate.operator_name)
        if operator is None:
            raise ValueError(f"Unknown operator: {candidate.operator_name}")

        candidate_config = operator.apply(current_config, candidate.config_params)

        baseline_scores = eval_fn(current_config)
        candidate_scores = eval_fn(candidate_config)

        baseline_composite = self._composite(baseline_scores)
        candidate_composite = self._composite(candidate_scores)
        delta = candidate_composite - baseline_composite
        accepted = delta > 0

        status = "accepted" if accepted else "rejected"
        now = time.time()

        card = ExperimentCard(
            experiment_id=uuid.uuid4().hex[:16],
            created_at=now,
            hypothesis=candidate.hypothesis,
            touched_surfaces=[operator.surface.value],
            touched_agents=[],
            diff_summary=f"operator={candidate.operator_name}, params={candidate.config_params}",
            eval_set_versions={},
            replay_set_hash="",
            baseline_sha=self._config_sha(current_config),
            candidate_sha=self._config_sha(candidate_config),
            risk_class=operator.risk_class.value,
            deployment_policy="canary" if operator.supports_autodeploy else "pr_only",
            rollback_handle=operator.rollback_strategy,
            total_experiment_cost=operator.estimated_eval_cost,
            status=status,
            result_summary=f"delta={delta:+.4f} (baseline={baseline_composite:.4f}, candidate={candidate_composite:.4f})",
            operator_name=candidate.operator_name,
            baseline_scores=baseline_scores,
            candidate_scores=candidate_scores,
            significance_p_value=1.0,
            significance_delta=delta,
        )
        return card

    def search_cycle(
        self,
        opportunities: list[OptimizationOpportunity],
        current_config: dict[str, Any],
        eval_fn: Callable[[dict[str, Any]], dict[str, float]],
        health_metrics: dict[str, Any],
        failure_buckets: dict[str, int],
    ) -> SearchResult:
        """Run a full search cycle: generate, rank, evaluate, record outcomes.

        Returns a :class:`SearchResult` summarising accepted/rejected
        experiments and budget consumption.
        """
        start = time.monotonic()
        total_cost = 0.0

        # 1. Generate
        candidates = self.generate_candidates(
            opportunities, current_config, health_metrics, failure_buckets
        )
        candidates_generated = len(candidates)

        # 2. Rank
        top_candidates = self.rank_candidates(candidates)

        # 3. Evaluate
        accepted: list[ExperimentCard] = []
        rejected: list[ExperimentCard] = []
        evaluated = 0
        budget_exhausted = False

        for candidate in top_candidates:
            # Check time budget
            elapsed = time.monotonic() - start
            if elapsed >= self.budget.time_budget_seconds:
                budget_exhausted = True
                logger.info("Time budget exhausted after %.1fs.", elapsed)
                break

            # Check cost budget
            operator = self.registry.get(candidate.operator_name)
            est_cost = operator.estimated_eval_cost if operator else 0.0
            if total_cost + est_cost > self.budget.max_cost_dollars:
                budget_exhausted = True
                logger.info(
                    "Cost budget exhausted: $%.4f + $%.4f > $%.2f.",
                    total_cost,
                    est_cost,
                    self.budget.max_cost_dollars,
                )
                break

            try:
                card = self.evaluate_candidate(candidate, current_config, eval_fn)
            except Exception:
                logger.exception(
                    "Evaluation failed for candidate %s.", candidate.mutation_id
                )
                continue

            evaluated += 1
            total_cost += card.total_experiment_cost

            # Record outcome in performance tracker
            is_accepted = card.status == "accepted"
            failure_family = self._opportunity_failure_family(
                candidate.target_opportunity_id, opportunities
            )
            if failure_family:
                self.tracker.record_outcome(
                    candidate.operator_name, failure_family, is_accepted
                )

            if is_accepted:
                accepted.append(card)
            else:
                rejected.append(card)

        return SearchResult(
            candidates_generated=candidates_generated,
            candidates_evaluated=evaluated,
            accepted=accepted,
            rejected=rejected,
            budget_exhausted=budget_exhausted,
            total_cost=round(total_cost, 6),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _past_change_descriptions(self) -> set[str]:
        """Load recent change descriptions from memory for deduplication."""
        attempts = self.memory.recent(limit=50)
        return {a.change_description.lower().strip() for a in attempts}

    @staticmethod
    def _description_key(operator_name: str, opportunity_id: str | None) -> str:
        """Build a stable key for deduplication against past attempts."""
        return f"{operator_name}::{opportunity_id or 'global'}".lower().strip()

    @staticmethod
    def _already_attempted(description_key: str, past_descriptions: set[str]) -> bool:
        """Return True if this operator+opportunity combo appears in past attempts."""
        return description_key in past_descriptions

    def _predict_lift(
        self, operator_name: str, opportunity: OptimizationOpportunity
    ) -> float:
        """Estimate predicted improvement from performance tracker and opportunity severity."""
        success_rate = self.tracker.get_success_rate(
            operator_name, opportunity.failure_family
        )
        # Blend success rate with opportunity severity — high-severity issues
        # offer more room for improvement.
        return min(1.0, success_rate * 0.6 + opportunity.severity * 0.4)

    @staticmethod
    def _compute_novelty(description_key: str, past_descriptions: set[str]) -> float:
        """Compute novelty score (0–1) based on similarity to past attempts.

        Returns 1.0 when the candidate is completely novel, lower when similar
        descriptions exist.
        """
        if not past_descriptions:
            return 1.0

        # Simple token-overlap heuristic.  A production system would use
        # embeddings, but token Jaccard is cheap and deterministic.
        candidate_tokens = set(description_key.split("::"))
        best_overlap = 0.0
        for desc in past_descriptions:
            desc_tokens = set(desc.split("::"))
            if not candidate_tokens or not desc_tokens:
                continue
            intersection = candidate_tokens & desc_tokens
            union = candidate_tokens | desc_tokens
            if union:
                jaccard = len(intersection) / len(union)
                best_overlap = max(best_overlap, jaccard)

        return round(1.0 - best_overlap, 4)

    @staticmethod
    def _combined_score(
        predicted_lift: float, novelty_score: float, risk_score: float
    ) -> float:
        """Weighted combination: 0.4*lift + 0.3*novelty + 0.3*(1-risk)."""
        return 0.4 * predicted_lift + 0.3 * novelty_score + 0.3 * (1.0 - risk_score)

    @staticmethod
    def _composite(scores: dict[str, float]) -> float:
        """Compute composite from score dict, preferring explicit ``composite`` key."""
        if not scores:
            return 0.0
        if "composite" in scores:
            return float(scores["composite"])
        preferred = [k for k in ("quality", "safety", "latency", "cost") if k in scores]
        keys = preferred if preferred else list(scores.keys())
        return sum(float(scores[k]) for k in keys) / len(keys)

    @staticmethod
    def _config_sha(config: dict[str, Any]) -> str:
        """Return a short SHA-256 hex digest of the config for experiment tracking."""
        import json as _json

        raw = _json.dumps(config, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    def _build_config_params(
        self,
        operator: MutationOperator,
        opportunity: OptimizationOpportunity,
        current_config: dict[str, Any],
    ) -> dict[str, Any]:
        """Build operator-specific config params from the opportunity context.

        Each operator surface has a sensible default param set.  The search
        engine does *not* call the LLM here — it relies on heuristics so
        the generate step stays fast and deterministic.
        """
        surface = operator.surface.value
        agent_path = opportunity.affected_agent_path or "root"

        if surface == "instruction":
            existing = current_config.get("prompts", {}).get(agent_path, "")
            suffix = self._failure_family_suffix(opportunity.failure_family)
            return {"target": agent_path, "text": f"{existing} {suffix}".strip()}

        if surface == "few_shot":
            return {
                "target": agent_path,
                "examples": [
                    {
                        "role": "user",
                        "content": f"Example addressing {opportunity.failure_family}",
                    },
                    {
                        "role": "assistant",
                        "content": f"Correct handling of {opportunity.failure_family}",
                    },
                ],
            }

        if surface == "tool_description":
            tool_name = (
                opportunity.affected_surface_candidates[0]
                if opportunity.affected_surface_candidates
                else "default"
            )
            return {"tool_name": tool_name, "updates": {"timeout_ms": 10000}}

        if surface == "model":
            return {"model": "gemini-2.0-flash"}

        if surface == "generation_settings":
            return {"temperature": 0.3, "max_tokens": 1024}

        if surface == "callback":
            return {"callback_name": "safety_filter", "config": {"enabled": True}}

        if surface == "context_caching":
            return {"enabled": True, "threshold_tokens": 500, "ttl_seconds": 600}

        if surface == "memory_policy":
            return {"preload": True, "write_back": True, "max_entries": 100}

        if surface == "routing":
            return {
                "action": "add",
                "rule": {
                    "specialist": agent_path,
                    "keywords": [opportunity.failure_family],
                },
            }

        # Fallback for unknown surfaces
        return {}

    @staticmethod
    def _failure_family_suffix(failure_family: str) -> str:
        """Return a short instruction suffix targeting a specific failure family."""
        suffixes: dict[str, str] = {
            "tool_error": "Verify tool inputs carefully before calling.",
            "routing_failure": "Route the user to the correct specialist.",
            "safety_violation": "Never assist with harmful or dangerous requests.",
            "latency_spike": "Respond concisely to minimize latency.",
            "quality_degradation": "Be thorough and detailed in your responses.",
            "cost_spike": "Be concise to reduce token usage.",
            "hallucination": "Only state facts you are confident about.",
            "transfer_loop": "Avoid transferring the user back and forth.",
        }
        return suffixes.get(failure_family, "Improve response quality.")

    @staticmethod
    def _opportunity_failure_family(
        opportunity_id: str | None,
        opportunities: list[OptimizationOpportunity],
    ) -> str | None:
        """Look up the failure_family for an opportunity by ID."""
        if opportunity_id is None:
            return None
        for opp in opportunities:
            if opp.opportunity_id == opportunity_id:
                return opp.failure_family
        return None

    # ------------------------------------------------------------------
    # HSO-aware cycle methods (used by HybridSearchOrchestrator)
    # ------------------------------------------------------------------

    def hybrid_search_cycle(
        self,
        opportunities: list[OptimizationOpportunity],
        current_config: dict[str, Any],
        eval_fn: Callable[[dict[str, Any]], dict[str, float]],
        health_metrics: dict[str, Any],
        failure_buckets: dict[str, int],
        strategy: SearchStrategy = SearchStrategy.ADAPTIVE,
    ) -> SearchResult:
        """Run adaptive/full HSO cycle with family bandit selection."""
        if strategy == SearchStrategy.SIMPLE:
            return self.search_cycle(
                opportunities=opportunities,
                current_config=current_config,
                eval_fn=eval_fn,
                health_metrics=health_metrics,
                failure_buckets=failure_buckets,
            )

        available_families = self._available_families(opportunities)
        forced_family = (
            self.bandit_selector.select([f.value for f in available_families])
            if available_families
            else None
        )

        filtered_opportunities = opportunities
        if forced_family:
            filtered_opportunities = self._filter_opportunities_by_family(
                opportunities,
                OperatorFamily(forced_family),
            )
            if not filtered_opportunities:
                filtered_opportunities = opportunities

        result = self._run_cycle_core(
            opportunities=filtered_opportunities,
            current_config=current_config,
            eval_fn=eval_fn,
            health_metrics=health_metrics,
            failure_buckets=failure_buckets,
            strategy=strategy,
            forced_family=forced_family,
        )
        result.strategy = strategy.value
        result.operator_family = forced_family

        if strategy == SearchStrategy.FULL and self.pareto_archive is not None:
            snapshot = self.pareto_archive.as_dict()
            result.pareto_front = snapshot.get("frontier", [])
            result.pareto_recommendation_id = snapshot.get("recommended_candidate_id")

        return result

    def _run_cycle_core(
        self,
        *,
        opportunities: list[OptimizationOpportunity],
        current_config: dict[str, Any],
        eval_fn: Callable[[dict[str, Any]], dict[str, float]],
        health_metrics: dict[str, Any],
        failure_buckets: dict[str, int],
        strategy: SearchStrategy,
        forced_family: str | None,
    ) -> SearchResult:
        """Core evaluation loop shared by simple/adaptive/full paths."""
        start = time.monotonic()
        total_cost = 0.0

        candidates = self.generate_candidates(
            opportunities, current_config, health_metrics, failure_buckets
        )
        if forced_family is not None:
            candidates = [
                c for c in candidates
                if self._family_for_operator(c.operator_name).value == forced_family
            ]
        candidates_generated = len(candidates)
        top_candidates = self.rank_candidates(candidates)

        accepted: list[ExperimentCard] = []
        rejected: list[ExperimentCard] = []
        accepted_configs: dict[str, dict[str, Any]] = {}
        evaluated = 0
        budget_exhausted = False

        for candidate in top_candidates:
            elapsed = time.monotonic() - start
            if elapsed >= self.budget.time_budget_seconds:
                budget_exhausted = True
                break

            operator = self.registry.get(candidate.operator_name)
            est_cost = operator.estimated_eval_cost if operator else 0.0
            if total_cost + est_cost > self.budget.max_cost_dollars:
                budget_exhausted = True
                break

            if operator is None:
                continue

            candidate_config = operator.apply(current_config, candidate.config_params)
            card = self.evaluate_candidate(candidate, current_config, eval_fn)

            evaluated += 1
            total_cost += card.total_experiment_cost

            family = self._family_for_operator(candidate.operator_name).value
            reward = max(0.0, card.significance_delta)
            self.bandit_selector.record(family, reward=reward)

            is_accepted = card.status == "accepted"
            failure_family = self._opportunity_failure_family(
                candidate.target_opportunity_id, opportunities
            )
            if failure_family:
                self.tracker.record_outcome(
                    candidate.operator_name, failure_family, is_accepted
                )

            if strategy == SearchStrategy.FULL and self.pareto_archive is not None:
                objectives = self._objectives_for_pareto(card.candidate_scores)
                self.pareto_archive.add_candidate(
                    candidate_id=card.experiment_id,
                    objectives=objectives,
                    constraints_passed=is_accepted,
                    constraint_violations=[] if is_accepted else ["did not improve"],
                    metadata={"operator_name": card.operator_name},
                )

            if is_accepted:
                accepted.append(card)
                accepted_configs[card.experiment_id] = candidate_config
            else:
                rejected.append(card)

        return SearchResult(
            candidates_generated=candidates_generated,
            candidates_evaluated=evaluated,
            accepted=accepted,
            rejected=rejected,
            budget_exhausted=budget_exhausted,
            total_cost=round(total_cost, 6),
            accepted_configs=accepted_configs,
        )

    @staticmethod
    def _family_for_operator(operator_name: str) -> OperatorFamily:
        """Map operator name to family (defaults to diversity injection)."""
        return _OPERATOR_TO_FAMILY.get(operator_name, OperatorFamily.DIVERSITY_INJECTION)

    def _available_families(
        self, opportunities: list[OptimizationOpportunity]
    ) -> list[OperatorFamily]:
        """Compute unique families present in current opportunity set."""
        seen: list[OperatorFamily] = []
        for opp in opportunities:
            for op_name in opp.recommended_operator_families:
                family = self._family_for_operator(op_name)
                if family not in seen:
                    seen.append(family)
        return seen

    def _filter_opportunities_by_family(
        self,
        opportunities: list[OptimizationOpportunity],
        family: OperatorFamily,
    ) -> list[OptimizationOpportunity]:
        """Keep only opportunities that contain operators in a target family."""
        filtered: list[OptimizationOpportunity] = []
        for opp in opportunities:
            names = [
                name for name in opp.recommended_operator_families
                if self._family_for_operator(name) == family
            ]
            if not names:
                continue
            filtered.append(
                OptimizationOpportunity(
                    opportunity_id=opp.opportunity_id,
                    created_at=opp.created_at,
                    cluster_id=opp.cluster_id,
                    failure_family=opp.failure_family,
                    affected_agent_path=opp.affected_agent_path,
                    affected_surface_candidates=list(opp.affected_surface_candidates),
                    severity=opp.severity,
                    prevalence=opp.prevalence,
                    recency=opp.recency,
                    business_impact=opp.business_impact,
                    sample_trace_ids=list(opp.sample_trace_ids),
                    recommended_operator_families=names,
                    priority_score=opp.priority_score,
                    status=opp.status,
                    resolution_experiment_id=opp.resolution_experiment_id,
                )
            )
        return filtered

    @staticmethod
    def _objectives_for_pareto(scores: dict[str, float]) -> dict[str, float]:
        """Extract core objective vector from candidate score payload."""
        return {
            "quality": float(scores.get("quality", 0.0)),
            "safety": float(scores.get("safety", 0.0)),
            "latency": float(scores.get("latency", 0.0)),
            "cost": float(scores.get("cost", 0.0)),
        }


# ---------------------------------------------------------------------------
# Hybrid bandit selector + curriculum + orchestrator
# ---------------------------------------------------------------------------


class HybridBanditSelector:
    """Bandit selector for adaptive operator-family and arm allocation."""

    def __init__(
        self,
        policy: BanditPolicy = BanditPolicy.THOMPSON,
        exploration_weight: float = 1.2,
        seed: int = 7,
    ) -> None:
        self.policy = policy
        self.exploration_weight = exploration_weight
        self._rng = random.Random(seed)
        self._attempts: dict[str, int] = defaultdict(int)
        self._reward_sum: dict[str, float] = defaultdict(float)
        self._successes: dict[str, int] = defaultdict(int)

    def record(self, arm: str, reward: float) -> None:
        """Record reward for one arm."""
        self._attempts[arm] += 1
        reward_value = max(0.0, float(reward))
        self._reward_sum[arm] += reward_value
        if reward_value > 0:
            self._successes[arm] += 1

    def select(self, arms: list[str]) -> str:
        """Select arm using configured bandit policy."""
        if not arms:
            raise ValueError("arms must be non-empty")
        unique = list(dict.fromkeys(arms))

        if self.policy == BanditPolicy.UCB:
            return self._select_ucb(unique)
        return self._select_thompson(unique)

    def _select_ucb(self, arms: list[str]) -> str:
        total_attempts = sum(self._attempts.values()) + 1
        best_arm = arms[0]
        best_score = float("-inf")
        for arm in arms:
            attempts = self._attempts[arm]
            mean_reward = self._reward_sum[arm] / attempts if attempts > 0 else 0.0
            if attempts == 0:
                score = float("inf")
            else:
                score = mean_reward + self.exploration_weight * math.sqrt(
                    math.log(total_attempts) / attempts
                )
            if score > best_score:
                best_score = score
                best_arm = arm
        return best_arm

    def _select_thompson(self, arms: list[str]) -> str:
        best_arm = arms[0]
        best_sample = float("-inf")
        for arm in arms:
            successes = self._successes[arm]
            attempts = self._attempts[arm]
            failures = max(0, attempts - successes)
            sample = self._rng.betavariate(1 + successes, 1 + failures)
            if sample > best_sample:
                best_sample = sample
                best_arm = arm
        return best_arm


class CurriculumStage(str, Enum):
    """Difficulty stage for full strategy curricula."""

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class HybridSearchOrchestrator:
    """Strategy layer that composes bandit selection + curriculum + Pareto archive."""

    def __init__(
        self,
        *,
        bandit_selector: HybridBanditSelector | None = None,
        pareto_archive: object | None = None,
    ) -> None:
        self.bandit_selector = bandit_selector or HybridBanditSelector()
        self.curriculum_stage = CurriculumStage.EASY
        self._consecutive_successes = 0
        self.pareto_archive = pareto_archive

    def select_opportunities_with_curriculum(
        self,
        opportunities: list[OptimizationOpportunity],
        max_items: int,
    ) -> list[OptimizationOpportunity]:
        """Pick opportunities according to current curriculum stage."""
        if not opportunities or max_items <= 0:
            return []
        scored = sorted(opportunities, key=self._difficulty_score)
        stage_filtered: list[OptimizationOpportunity] = []
        remainder: list[OptimizationOpportunity] = []

        if self.curriculum_stage == CurriculumStage.EASY:
            stage_filtered = [i for i in scored if self._difficulty_score(i) <= 0.45]
            remainder = [i for i in scored if i not in stage_filtered]
        elif self.curriculum_stage == CurriculumStage.MEDIUM:
            stage_filtered = [i for i in scored if self._difficulty_score(i) <= 0.75]
            remainder = [i for i in scored if i not in stage_filtered]
        else:
            stage_filtered = scored

        if not stage_filtered:
            stage_filtered = scored
        selected = stage_filtered[:max_items]
        if len(selected) < max_items:
            for item in remainder:
                if item in selected:
                    continue
                selected.append(item)
                if len(selected) >= max_items:
                    break
        return selected

    def record_curriculum_outcome(self, success: bool) -> None:
        """Advance stage after repeated wins on current level."""
        if success:
            self._consecutive_successes += 1
        else:
            self._consecutive_successes = 0
        if self._consecutive_successes < 3:
            return
        self._consecutive_successes = 0
        if self.curriculum_stage == CurriculumStage.EASY:
            self.curriculum_stage = CurriculumStage.MEDIUM
        elif self.curriculum_stage == CurriculumStage.MEDIUM:
            self.curriculum_stage = CurriculumStage.HARD

    def run_cycle(
        self,
        *,
        strategy: SearchStrategy,
        registry: MutationRegistry,
        memory: OptimizationMemory,
        proposer: Proposer,
        opportunities: list[OptimizationOpportunity],
        current_config: dict[str, Any],
        budget: SearchBudget,
        eval_fn: Callable[[dict[str, Any]], dict[str, float]],
    ) -> SearchResult:
        """Run one HSO cycle using an ephemeral SearchEngine."""
        tracker_path = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
        engine = SearchEngine(
            registry=registry,
            memory=memory,
            proposer=proposer,
            performance_tracker=OperatorPerformanceTracker(db_path=tracker_path),
            budget=budget,
            bandit_selector=self.bandit_selector,
            pareto_archive=self.pareto_archive,
        )

        selected_opportunities = opportunities
        if strategy == SearchStrategy.FULL:
            selected_opportunities = self.select_opportunities_with_curriculum(
                opportunities,
                max_items=max(1, budget.max_candidates),
            )

        result = engine.hybrid_search_cycle(
            opportunities=selected_opportunities,
            current_config=current_config,
            eval_fn=eval_fn,
            health_metrics={},
            failure_buckets={},
            strategy=strategy,
        )
        return result

    @staticmethod
    def _difficulty_score(opportunity: OptimizationOpportunity) -> float:
        """Estimate opportunity difficulty from severity and prevalence."""
        return min(1.0, opportunity.severity * 0.6 + opportunity.prevalence * 0.4)


# ---------------------------------------------------------------------------
# Adaptive search engine (bandit + curriculum)
# ---------------------------------------------------------------------------


class AdaptiveSearchEngine(SearchEngine):
    """Enhanced search engine with bandit selection and curriculum learning.

    search_strategy: "simple" | "adaptive" | "full"
    - simple: original failure-bucket proposer (fast, predictable)
    - adaptive: HSO with bandit selection (smarter, more eval cost)
    - full: HSO + curriculum + Pareto archive (maximum optimization, maximum cost)
    """

    _VALID_STRATEGIES = {"simple", "adaptive", "full"}

    def __init__(
        self,
        registry: MutationRegistry,
        memory: OptimizationMemory,
        proposer: Proposer,
        performance_tracker: OperatorPerformanceTracker | None = None,
        budget: SearchBudget | None = None,
        search_strategy: str = "simple",
        bandit_policy: str = "ucb1",
    ) -> None:
        super().__init__(registry, memory, proposer, performance_tracker, budget)
        if search_strategy not in self._VALID_STRATEGIES:
            raise ValueError(
                f"Invalid search_strategy '{search_strategy}'. "
                f"Must be one of: {self._VALID_STRATEGIES}"
            )
        self.search_strategy = search_strategy

        if search_strategy in ("adaptive", "full"):
            from .bandit import BanditPolicy, BanditSelector

            policy = BanditPolicy(bandit_policy)
            self.bandit: BanditSelector | None = BanditSelector(policy=policy)
        else:
            self.bandit = None

        if search_strategy == "full":
            from .curriculum import CurriculumScheduler

            self.curriculum: CurriculumScheduler | None = CurriculumScheduler()
        else:
            self.curriculum = None

    # ------------------------------------------------------------------
    # Overridden public API
    # ------------------------------------------------------------------

    def generate_candidates(
        self,
        opportunities: list[OptimizationOpportunity],
        current_config: dict[str, Any],
        health_metrics: dict[str, Any],
        failure_buckets: dict[str, int],
    ) -> list[CandidateMutation]:
        """Generate candidates with bandit-guided selection."""
        if self.search_strategy == "simple":
            return super().generate_candidates(
                opportunities, current_config, health_metrics, failure_buckets
            )

        # For adaptive/full: optionally filter via curriculum, then use bandit to rank
        filtered_opps = list(opportunities)
        if self.curriculum is not None:
            pass_rates = self._estimate_pass_rates(failure_buckets)
            filtered_opps = self.curriculum.filter_opportunities(
                opportunities, pass_rates
            )

        # Build candidate arms for bandit
        candidate_arms: list[tuple[str, str, OptimizationOpportunity]] = []
        for opp in filtered_opps:
            for op_name in opp.recommended_operator_families:
                operator = self.registry.get(op_name)
                if operator is not None and operator.ready:
                    candidate_arms.append((op_name, opp.failure_family, opp))

        if not candidate_arms:
            # Fall back to parent implementation
            return super().generate_candidates(
                opportunities, current_config, health_metrics, failure_buckets
            )

        # Use bandit to rank arms
        arm_tuples = [(op, ff) for op, ff, _ in candidate_arms]
        assert self.bandit is not None
        ranked = self.bandit.rank_candidates(arm_tuples, n=self.budget.max_candidates)

        # Build a lookup from (op, ff) -> opportunity for the ranked arms
        arm_to_opp: dict[tuple[str, str], OptimizationOpportunity] = {}
        for op, ff, opp in candidate_arms:
            key = (op, ff)
            if key not in arm_to_opp:
                arm_to_opp[key] = opp

        # Generate CandidateMutation objects using parent class helpers
        past_descriptions = self._past_change_descriptions()
        candidates: list[CandidateMutation] = []

        for op_name, ff, _bandit_score in ranked:
            opp = arm_to_opp.get((op_name, ff))
            if opp is None:
                continue

            operator = self.registry.get(op_name)
            if operator is None:
                continue

            description_key = self._description_key(op_name, opp.opportunity_id)
            if self._already_attempted(description_key, past_descriptions):
                continue

            config_params = self._build_config_params(operator, opp, current_config)
            hypothesis = (
                f"Applying '{op_name}' to address {opp.failure_family} "
                f"(severity={opp.severity:.2f}, prevalence={opp.prevalence:.2f})"
            )

            predicted_lift = self._predict_lift(op_name, opp)
            risk_score = _RISK_SCORES.get(operator.risk_class, 0.5)
            novelty_score = self._compute_novelty(description_key, past_descriptions)
            combined = self._combined_score(predicted_lift, novelty_score, risk_score)

            candidate = CandidateMutation(
                mutation_id=uuid.uuid4().hex[:12],
                operator_name=op_name,
                target_opportunity_id=opp.opportunity_id,
                predicted_lift=round(predicted_lift, 4),
                risk_score=round(risk_score, 4),
                novelty_score=round(novelty_score, 4),
                combined_score=round(combined, 4),
                config_params=config_params,
                hypothesis=hypothesis,
            )
            candidates.append(candidate)

        # Sort and cap
        candidates.sort(key=lambda c: c.combined_score, reverse=True)
        return candidates[: self.budget.max_candidates]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_pass_rates(failure_buckets: dict[str, int]) -> dict[str, float]:
        """Estimate pass rates from failure bucket counts."""
        total = sum(failure_buckets.values()) or 1
        return {ff: 1.0 - (count / total) for ff, count in failure_buckets.items()}
