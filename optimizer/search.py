"""Multi-hypothesis search engine for optimization candidates.

Generates, ranks, and evaluates candidate mutations by combining operator
performance history, novelty scoring against past attempts, and risk-adjusted
scoring.  Designed to plug into the existing Optimizer loop as an alternative
to the single-shot Proposer path.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import time
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

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
# Data classes
# ---------------------------------------------------------------------------


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
    ) -> None:
        self.registry = registry
        self.memory = memory
        self.proposer = proposer
        self.tracker = performance_tracker or OperatorPerformanceTracker()
        self.budget = budget or SearchBudget()

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
        """Compute a simple mean composite from a scores dict."""
        if not scores:
            return 0.0
        return sum(scores.values()) / len(scores)

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
