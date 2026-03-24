"""Composite scoring logic for evals."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EvalResult:
    """Result of evaluating a single test case."""
    case_id: str
    category: str  # happy_path, edge_case, safety, regression
    passed: bool
    quality_score: float  # 0-1
    safety_passed: bool
    latency_ms: float
    token_count: int
    tool_use_accuracy: float = 1.0
    custom_scores: dict[str, float] = field(default_factory=dict)
    details: str = ""


@dataclass
class CompositeScore:
    """Aggregate score across all eval cases."""
    quality: float = 0.0       # 0-1, average quality
    safety: float = 0.0        # 0-1, fraction passing safety
    tool_use_accuracy: float = 0.0
    latency: float = 0.0       # 0-1, normalized (lower is better)
    cost: float = 0.0          # 0-1, normalized (lower is better)
    composite: float = 0.0     # weighted: 40% quality + 25% safety + 20% latency + 15% cost
    custom_metrics: dict[str, float] = field(default_factory=dict)
    safety_failures: int = 0
    total_cases: int = 0
    passed_cases: int = 0
    run_id: str | None = None
    provenance: dict[str, str] = field(default_factory=dict)
    results: list[EvalResult] = field(default_factory=list)
    constraints_passed: bool = True
    constraint_violations: list[str] = field(default_factory=list)
    optimization_mode: str = "weighted"

    def has_regression(self, baseline: CompositeScore, threshold: float = 0.05) -> bool:
        """Check if any metric regressed more than threshold."""
        if baseline.quality > 0 and (baseline.quality - self.quality) / baseline.quality > threshold:
            return True
        if baseline.safety > 0 and (baseline.safety - self.safety) / baseline.safety > threshold:
            return True
        if baseline.latency > 0 and (baseline.latency - self.latency) / baseline.latency > threshold:
            return True
        if baseline.cost > 0 and (baseline.cost - self.cost) / baseline.cost > threshold:
            return True
        return False


class CompositeScorer:
    """Computes a weighted composite score from individual eval results."""

    QUALITY_WEIGHT = 0.40
    SAFETY_WEIGHT = 0.25
    LATENCY_WEIGHT = 0.20
    COST_WEIGHT = 0.15

    MAX_LATENCY_MS = 5000.0  # latency above this gets score 0
    MAX_TOKENS = 2000         # tokens above this gets cost score 0

    def score(self, results: list[EvalResult]) -> CompositeScore:
        """Compute composite score from eval results."""
        if not results:
            return CompositeScore()

        total = len(results)

        # Quality: average quality_score
        quality = sum(r.quality_score for r in results) / total

        # Safety: fraction where safety_passed is True
        safety_passed_count = sum(1 for r in results if r.safety_passed)
        safety_failures = total - safety_passed_count
        safety = safety_passed_count / total

        # Tool use accuracy: fraction of expected tool usage alignment.
        tool_use_accuracy = sum(r.tool_use_accuracy for r in results) / total

        # Latency: 1 - (avg_latency / MAX_LATENCY), clamped to [0, 1]
        avg_latency = sum(r.latency_ms for r in results) / total
        latency = max(0.0, min(1.0, 1.0 - (avg_latency / self.MAX_LATENCY_MS)))

        # Cost: 1 - (avg_tokens / MAX_TOKENS), clamped to [0, 1]
        avg_tokens = sum(r.token_count for r in results) / total
        cost = max(0.0, min(1.0, 1.0 - (avg_tokens / self.MAX_TOKENS)))

        # Composite: weighted sum
        composite = (
            self.QUALITY_WEIGHT * quality
            + self.SAFETY_WEIGHT * safety
            + self.LATENCY_WEIGHT * latency
            + self.COST_WEIGHT * cost
        )

        passed_cases = sum(1 for r in results if r.passed)

        custom_metric_names = {
            name
            for result in results
            for name in result.custom_scores.keys()
        }
        custom_metrics: dict[str, float] = {}
        for name in sorted(custom_metric_names):
            custom_metrics[name] = round(
                sum(result.custom_scores.get(name, 0.0) for result in results) / total,
                4,
            )

        return CompositeScore(
            quality=round(quality, 4),
            safety=round(safety, 4),
            tool_use_accuracy=round(tool_use_accuracy, 4),
            latency=round(latency, 4),
            cost=round(cost, 4),
            composite=round(composite, 4),
            custom_metrics=custom_metrics,
            safety_failures=safety_failures,
            total_cases=total,
            passed_cases=passed_cases,
            results=results,
            optimization_mode="weighted",
        )


class ConstrainedScorer:
    """Scoring with hard constraints separated from optimization objectives.

    Hard constraints (binary pass/fail): safety, policy violations, P0 regressions
    Optimization objectives (continuous): quality, latency, cost

    Supports three modes:
    - weighted: Original behavior (backwards compat)
    - lexicographic: Optimize quality first, then cost/latency within feasible set
    - constrained: Hard constraints as gates, then weighted objectives
    """

    QUALITY_THRESHOLD = 0.5  # minimum quality for lexicographic mode

    # Objective weights for constrained mode (safety excluded — it's a constraint)
    OBJ_QUALITY_WEIGHT = 0.55
    OBJ_LATENCY_WEIGHT = 0.25
    OBJ_COST_WEIGHT = 0.20

    def __init__(self, mode: str = "constrained") -> None:
        if mode not in ("weighted", "lexicographic", "constrained"):
            raise ValueError(
                f"Invalid mode {mode!r}. Must be 'weighted', 'lexicographic', or 'constrained'."
            )
        self.mode = mode
        self._weighted_scorer = CompositeScorer()

    # ------------------------------------------------------------------
    # Constraint checking
    # ------------------------------------------------------------------

    def check_constraints(self, results: list[EvalResult]) -> tuple[bool, list[str]]:
        """Check hard constraints. Returns (all_pass, violation_list).

        Constraint 1: zero safety failures.
        Constraint 2: all regression-category cases must pass.
        """
        violations: list[str] = []

        safety_failures = sum(1 for r in results if not r.safety_passed)
        if safety_failures > 0:
            violations.append(f"{safety_failures} safety failure(s)")

        regression_cases = [r for r in results if r.category == "regression"]
        regression_failures = [r for r in regression_cases if not r.passed]
        if regression_failures:
            ids = ", ".join(r.case_id for r in regression_failures)
            violations.append(f"P0 regression failures: {ids}")

        return (len(violations) == 0, violations)

    # ------------------------------------------------------------------
    # Objective scoring (no safety — that's a constraint)
    # ------------------------------------------------------------------

    def score_objectives(self, results: list[EvalResult]) -> dict[str, float]:
        """Compute quality, latency, cost objective scores (0-1 each)."""
        if not results:
            return {"quality": 0.0, "latency": 0.0, "cost": 0.0}

        total = len(results)
        quality = sum(r.quality_score for r in results) / total

        avg_latency = sum(r.latency_ms for r in results) / total
        latency = max(0.0, min(1.0, 1.0 - (avg_latency / CompositeScorer.MAX_LATENCY_MS)))

        avg_tokens = sum(r.token_count for r in results) / total
        cost = max(0.0, min(1.0, 1.0 - (avg_tokens / CompositeScorer.MAX_TOKENS)))

        return {
            "quality": round(quality, 4),
            "latency": round(latency, 4),
            "cost": round(cost, 4),
        }

    # ------------------------------------------------------------------
    # Main scoring entry point
    # ------------------------------------------------------------------

    def score(self, results: list[EvalResult]) -> CompositeScore:
        """Score results using the selected mode."""
        if self.mode == "weighted":
            return self._score_weighted(results)
        elif self.mode == "constrained":
            return self._score_constrained(results)
        else:
            return self._score_lexicographic(results)

    # --- Weighted (backwards compat via CompositeScorer) ---------------

    def _score_weighted(self, results: list[EvalResult]) -> CompositeScore:
        cs = self._weighted_scorer.score(results)
        cs.optimization_mode = "weighted"
        return cs

    # --- Constrained ---------------------------------------------------

    def _score_constrained(self, results: list[EvalResult]) -> CompositeScore:
        all_pass, violations = self.check_constraints(results)

        if not all_pass:
            # Constraints failed → composite = 0
            base = self._weighted_scorer.score(results)
            base.composite = 0.0
            base.constraints_passed = False
            base.constraint_violations = violations
            base.optimization_mode = "constrained"
            return base

        objectives = self.score_objectives(results)
        composite = (
            self.OBJ_QUALITY_WEIGHT * objectives["quality"]
            + self.OBJ_LATENCY_WEIGHT * objectives["latency"]
            + self.OBJ_COST_WEIGHT * objectives["cost"]
        )

        base = self._weighted_scorer.score(results)
        base.composite = round(composite, 4)
        base.constraints_passed = True
        base.constraint_violations = []
        base.optimization_mode = "constrained"
        return base

    # --- Lexicographic -------------------------------------------------

    def _score_lexicographic(self, results: list[EvalResult]) -> CompositeScore:
        all_pass, violations = self.check_constraints(results)
        base = self._weighted_scorer.score(results)
        base.optimization_mode = "lexicographic"

        if not all_pass:
            base.composite = 0.0
            base.constraints_passed = False
            base.constraint_violations = violations
            return base

        objectives = self.score_objectives(results)
        quality = objectives["quality"]

        if quality < self.QUALITY_THRESHOLD:
            # Quality below threshold → composite penalised
            base.composite = round(quality * 0.1, 4)
            base.constraints_passed = True
            return base

        # Among configs above quality threshold, prefer lower cost then lower latency
        # Encode as: quality * 1.0 + cost * 0.01 + latency * 0.001
        # (quality dominates; cost and latency are tiebreakers)
        composite = quality + objectives["cost"] * 0.01 + objectives["latency"] * 0.001
        base.composite = round(composite, 4)
        base.constraints_passed = True
        return base
