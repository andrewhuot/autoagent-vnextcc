"""Build-time skill-aware optimization engine.

This module integrates build-time skills into the optimization loop. Build-time
skills encode HOW to optimize agents (mutation operators, triggers, eval criteria).

The SkillEngine orchestrates:
1. Skill selection based on diagnosis (failure families, metrics, blame maps)
2. Mutation proposal using skill-encoded strategies
3. Result evaluation against skill-defined criteria
4. Learning from outcomes to improve skill effectiveness

Integration points:
- core.skills.store.SkillStore for skill lookup and persistence
- optimizer.mutations for mutation operators
- observer.opportunities for failure families and blame maps
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from core.skills.store import SkillStore
from core.skills.types import (
    EvalCriterion,
    MutationOperator,
    Skill,
    SkillKind,
)
from optimizer.mutations import (
    MutationRegistry,
    MutationSurface,
    RiskClass,
    create_default_registry,
)


@dataclass
class SkillApplication:
    """Record of a skill application for tracking and learning."""

    skill_id: str
    skill_name: str
    mutation_name: str
    config_before: dict[str, Any]
    config_after: dict[str, Any]
    context: dict[str, Any]


class SkillEngine:
    """Main engine for build-time skill-aware optimization.

    The SkillEngine integrates build-time skills into the optimization loop:
    - Selects relevant skills based on failure patterns and metrics
    - Proposes mutations using skill-encoded strategies
    - Evaluates results against skill-defined success criteria
    - Learns from outcomes to update skill effectiveness metrics

    Thread Safety:
        This class is NOT thread-safe by design. Create one instance per
        optimization session/thread. The underlying SkillStore IS thread-safe.

    Attributes:
        store: The SkillStore for skill lookup and persistence.
        mutation_registry: Registry of available mutation operators.
    """

    def __init__(
        self,
        store: SkillStore,
        mutation_registry: MutationRegistry | None = None,
    ) -> None:
        """Initialize the skill engine.

        Args:
            store: SkillStore instance for skill persistence.
            mutation_registry: Optional custom mutation registry. Defaults to
                the standard registry with all first-party operators.
        """
        self.store = store
        self.mutation_registry = mutation_registry or create_default_registry()
        self._application_history: list[SkillApplication] = []

    # ------------------------------------------------------------------
    # Skill Selection
    # ------------------------------------------------------------------

    def select_skills(
        self,
        failure_family: str | None = None,
        metrics: dict[str, float] | None = None,
        max_skills: int = 5,
    ) -> list[Skill]:
        """Select relevant build-time skills based on diagnosis.

        Uses the SkillStore's recommendation engine to find skills that match:
        - Failure family (from failure clustering)
        - Metric thresholds (from health reports)

        Returns skills ranked by effectiveness (success_rate * avg_improvement).

        Args:
            failure_family: Optional failure family to match (e.g., 'routing_error',
                'hallucination', 'safety_violation').
            metrics: Optional dict of current metrics to check against skill triggers
                (e.g., {'routing_accuracy': 0.6, 'latency_p95': 5.2}).
            max_skills: Maximum number of skills to return.

        Returns:
            List of relevant build-time skills, ranked by effectiveness.
        """
        # Delegate to SkillStore's recommendation engine
        recommended = self.store.recommend(
            failure_family=failure_family,
            metrics=metrics,
            kind=SkillKind.BUILD,
        )

        # Limit to max_skills
        return recommended[:max_skills]

    # ------------------------------------------------------------------
    # Mutation Application
    # ------------------------------------------------------------------

    def apply_skill(
        self,
        skill: Skill,
        config: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Apply a skill's first mutation to the config.

        This method applies the first mutation operator defined in the skill.
        If the skill has multiple mutations, use propose_from_skills() to get
        all mutation variants.

        Args:
            skill: The skill to apply.
            config: Current agent configuration.
            context: Optional context dict for mutation parameters
                (e.g., {'target': 'root', 'text': '...'}).

        Returns:
            New config with the skill's mutation applied.

        Raises:
            ValueError: If skill has no mutations or mutation not found in registry.
        """
        if not skill.mutations:
            raise ValueError(f"Skill '{skill.name}' has no mutations defined")

        mutation_def = skill.mutations[0]
        return self._apply_mutation(skill, mutation_def, config, context or {})

    def propose_from_skills(
        self,
        skills: list[Skill],
        config: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Generate mutation proposals from multiple skills.

        For each skill, applies all of its mutation operators to generate
        candidate configurations. Useful for batch evaluation.

        Args:
            skills: List of skills to generate proposals from.
            config: Current agent configuration.
            context: Optional shared context for all mutations.

        Returns:
            List of mutated configs, one per skill mutation.
        """
        proposals: list[dict[str, Any]] = []
        ctx = context or {}

        for skill in skills:
            for mutation_def in skill.mutations:
                try:
                    mutated = self._apply_mutation(skill, mutation_def, config, ctx)
                    proposals.append(mutated)
                except (ValueError, KeyError) as e:
                    # Skip mutations that fail validation or missing operators
                    # In production, we log this but don't fail the entire batch
                    continue

        return proposals

    def _apply_mutation(
        self,
        skill: Skill,
        mutation_def: MutationOperator,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Internal: apply a single mutation to config.

        Args:
            skill: The skill this mutation belongs to.
            mutation_def: The mutation operator definition from the skill.
            config: Current config.
            context: Mutation parameters.

        Returns:
            New config with mutation applied.

        Raises:
            ValueError: If mutation operator not found in registry.
        """
        # Look up the mutation operator in the registry
        operator = self.mutation_registry.get(mutation_def.name)
        if operator is None:
            raise ValueError(
                f"Mutation '{mutation_def.name}' not found in registry. "
                f"Available: {[op.name for op in self.mutation_registry.list_all()]}"
            )

        # Merge mutation parameters with context
        params = {**mutation_def.parameters, **context}

        # Apply the mutation
        config_before = copy.deepcopy(config)
        config_after = operator.apply(config, params)

        # Record the application
        self._application_history.append(
            SkillApplication(
                skill_id=skill.id,
                skill_name=skill.name,
                mutation_name=mutation_def.name,
                config_before=config_before,
                config_after=config_after,
                context=params,
            )
        )

        return config_after

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate_skill_result(
        self,
        skill: Skill,
        baseline_score: float,
        candidate_score: float,
    ) -> bool:
        """Evaluate whether a skill application succeeded.

        Checks the candidate score against the skill's eval criteria.
        If the skill has multiple criteria, all must pass (AND logic).
        If the skill has no criteria, falls back to simple improvement check.

        Args:
            skill: The skill that was applied.
            baseline_score: Baseline performance score.
            candidate_score: Performance after applying the skill.

        Returns:
            True if the skill application succeeded, False otherwise.
        """
        if not skill.eval_criteria:
            # No criteria defined: default to simple improvement
            return candidate_score > baseline_score

        # Check all criteria (AND logic)
        for criterion in skill.eval_criteria:
            if not self._check_criterion(criterion, baseline_score, candidate_score):
                return False

        return True

    def _check_criterion(
        self,
        criterion: EvalCriterion,
        baseline_score: float,
        candidate_score: float,
    ) -> bool:
        """Check a single eval criterion.

        Args:
            criterion: The evaluation criterion to check.
            baseline_score: Baseline performance.
            candidate_score: Candidate performance.

        Returns:
            True if criterion is satisfied.
        """
        # For simplicity, we assume the metric value is the candidate_score
        # In production, you'd extract criterion.metric from a metrics dict
        value = candidate_score

        # Apply operator
        if criterion.operator == "gt":
            return value > criterion.target
        elif criterion.operator == "gte":
            return value >= criterion.target
        elif criterion.operator == "lt":
            return value < criterion.target
        elif criterion.operator == "lte":
            return value <= criterion.target
        elif criterion.operator == "eq":
            return abs(value - criterion.target) < 1e-6
        else:
            # Unknown operator: default to False
            return False

    # ------------------------------------------------------------------
    # Learning
    # ------------------------------------------------------------------

    def learn_from_outcome(
        self,
        skill: Skill,
        improvement: float,
        success: bool,
    ) -> None:
        """Record outcome and update skill effectiveness metrics.

        This method delegates to the SkillStore's record_outcome(), which:
        - Records the outcome in the skill_outcomes table
        - Recalculates effectiveness metrics (success_rate, avg_improvement, etc.)
        - Updates the skill in the store

        Args:
            skill: The skill that was applied.
            improvement: Performance improvement delta (can be negative).
            success: Whether the skill application succeeded.
        """
        self.store.record_outcome(skill.id, improvement, success)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def get_application_history(self) -> list[SkillApplication]:
        """Return the history of skill applications in this session.

        Returns:
            List of SkillApplication records, in chronological order.
        """
        return list(self._application_history)

    def clear_history(self) -> None:
        """Clear the application history.

        Useful for resetting state between optimization sessions.
        """
        self._application_history.clear()

    def validate_config(self, config: dict[str, Any]) -> bool:
        """Validate a config against all applied mutations.

        Checks that the config satisfies the validators of all mutation
        operators applied in this session.

        Args:
            config: The config to validate.

        Returns:
            True if valid, False otherwise.
        """
        for app in self._application_history:
            operator = self.mutation_registry.get(app.mutation_name)
            if operator is None:
                # Operator no longer in registry
                continue

            if operator.validator is not None:
                if not operator.validator(config):
                    return False

        return True
