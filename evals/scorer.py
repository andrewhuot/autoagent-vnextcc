"""Composite scoring logic for evals."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.types import MetricLayer, METRIC_REGISTRY, get_metrics_by_layer


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
    routing_correct: bool = True           # G7: was routed to right specialist
    handoff_context_preserved: bool = True  # G8: key entities survived handoff
    satisfaction_proxy: float = 1.0         # G9: user satisfaction heuristic (0-1)


@dataclass
class DimensionScores:
    """Full 9-dimension evaluation vector (v4 enhanced scoring)."""
    task_success_rate: float = 0.0         # G1
    response_quality: float = 0.0          # G2
    safety_compliance: float = 0.0         # G3
    latency_p50: float = 0.0              # G4a
    latency_p95: float = 0.0              # G4b
    latency_p99: float = 0.0              # G4c
    token_cost: float = 0.0               # G5
    tool_correctness: float = 0.0          # G6
    routing_accuracy: float = 0.0          # G7
    handoff_fidelity: float = 0.0          # G8
    user_satisfaction_proxy: float = 0.0   # G9

    def to_dict(self) -> dict[str, float]:
        """Serialize all dimensions to a dict."""
        return {
            "task_success_rate": self.task_success_rate,
            "response_quality": self.response_quality,
            "safety_compliance": self.safety_compliance,
            "latency_p50": self.latency_p50,
            "latency_p95": self.latency_p95,
            "latency_p99": self.latency_p99,
            "token_cost": self.token_cost,
            "tool_correctness": self.tool_correctness,
            "routing_accuracy": self.routing_accuracy,
            "handoff_fidelity": self.handoff_fidelity,
            "user_satisfaction_proxy": self.user_satisfaction_proxy,
        }

    def to_objective_vector(self) -> list[float]:
        """Return vector for Pareto dominance checks. Higher is better for all."""
        return [
            self.task_success_rate,
            self.response_quality,
            self.safety_compliance,
            self.latency_p50,
            self.latency_p95,
            self.latency_p99,
            self.token_cost,
            self.tool_correctness,
            self.routing_accuracy,
            self.handoff_fidelity,
            self.user_satisfaction_proxy,
        ]


@dataclass
class PerAgentScores:
    """Per-agent evaluation dimensions."""
    agent_path: str
    unit_success: float = 0.0
    tool_precision: float = 0.0
    tool_recall: float = 0.0
    policy_adherence: float = 0.0
    avg_latency_ms: float = 0.0
    escalation_appropriateness: float = 0.0


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
    dimensions: DimensionScores | None = None
    per_agent_scores: list[PerAgentScores] = field(default_factory=list)

    @property
    def global_dimensions(self) -> dict[str, float]:
        """Return 9-dimension global scores as a dict (compatibility alias)."""
        if self.dimensions is not None:
            return self.dimensions.to_dict()
        return {}

    @property
    def per_agent_dimensions(self) -> dict[str, dict[str, float]]:
        """Return per-agent dimension scores as a dict (compatibility alias)."""
        result: dict[str, dict[str, float]] = {}
        for agent in self.per_agent_scores:
            result[agent.agent_path] = {
                "unit_success": agent.unit_success,
                "tool_precision": agent.tool_precision,
                "tool_recall": agent.tool_recall,
                "policy_adherence": agent.policy_adherence,
                "avg_latency_ms": agent.avg_latency_ms,
                "escalation_appropriateness": agent.escalation_appropriateness,
            }
        return result

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


class EnhancedScorer:
    """Computes full 9-dimension scores + per-agent breakdown.

    Wraps ConstrainedScorer -- the 4-dimension composite remains the default view.
    The 9 dimensions are available in CompositeScore.dimensions for detail views.
    """

    MAX_LATENCY_MS = 5000.0  # latency above this gets normalized score 0

    def __init__(self, mode: str = "constrained") -> None:
        self._constrained_scorer = ConstrainedScorer(mode=mode)

    def score(self, results: list[EvalResult]) -> CompositeScore:
        """Score results: standard composite + 9 dimensions + per-agent."""
        composite = self._constrained_scorer.score(results)
        composite.dimensions = self._compute_dimensions(results)
        composite.per_agent_scores = self._compute_per_agent(results)
        return composite

    def _compute_dimensions(self, results: list[EvalResult]) -> DimensionScores:
        """Compute all 9 global dimensions from results."""
        if not results:
            return DimensionScores()

        total = len(results)

        # G1: task_success_rate = fraction passed
        task_success_rate = sum(1 for r in results if r.passed) / total

        # G2: response_quality = mean quality_score
        response_quality = sum(r.quality_score for r in results) / total

        # G3: safety_compliance = fraction safety_passed
        safety_compliance = sum(1 for r in results if r.safety_passed) / total

        # G4: latency percentiles (normalized: higher = better)
        latencies = sorted(r.latency_ms for r in results)
        latency_p50 = self._percentile(latencies, 0.50)
        latency_p95 = self._percentile(latencies, 0.95)
        latency_p99 = self._percentile(latencies, 0.99)
        # Normalize: 1 - (pXX / MAX_LATENCY), clamped to [0, 1]
        norm_p50 = max(0.0, min(1.0, 1.0 - latency_p50 / self.MAX_LATENCY_MS))
        norm_p95 = max(0.0, min(1.0, 1.0 - latency_p95 / self.MAX_LATENCY_MS))
        norm_p99 = max(0.0, min(1.0, 1.0 - latency_p99 / self.MAX_LATENCY_MS))

        # G5: token_cost = normalized (higher = cheaper = better)
        avg_tokens = sum(r.token_count for r in results) / total
        token_cost = max(0.0, min(1.0, 1.0 - avg_tokens / CompositeScorer.MAX_TOKENS))

        # G6: tool_correctness = mean tool_use_accuracy
        tool_correctness = sum(r.tool_use_accuracy for r in results) / total

        # G7: routing_accuracy = fraction where routing_correct is True
        routing_accuracy = sum(1 for r in results if r.routing_correct) / total

        # G8: handoff_fidelity = fraction where handoff_context_preserved is True
        handoff_fidelity = sum(1 for r in results if r.handoff_context_preserved) / total

        # G9: user_satisfaction_proxy = mean satisfaction_proxy
        user_satisfaction_proxy = sum(r.satisfaction_proxy for r in results) / total

        return DimensionScores(
            task_success_rate=round(task_success_rate, 4),
            response_quality=round(response_quality, 4),
            safety_compliance=round(safety_compliance, 4),
            latency_p50=round(norm_p50, 4),
            latency_p95=round(norm_p95, 4),
            latency_p99=round(norm_p99, 4),
            token_cost=round(token_cost, 4),
            tool_correctness=round(tool_correctness, 4),
            routing_accuracy=round(routing_accuracy, 4),
            handoff_fidelity=round(handoff_fidelity, 4),
            user_satisfaction_proxy=round(user_satisfaction_proxy, 4),
        )

    @staticmethod
    def _percentile(sorted_values: list[float], pct: float) -> float:
        """Compute percentile from pre-sorted list using nearest-rank method."""
        if not sorted_values:
            return 0.0
        n = len(sorted_values)
        idx = int(pct * (n - 1))
        return sorted_values[idx]

    def _compute_per_agent(self, results: list[EvalResult]) -> list[PerAgentScores]:
        """Group results by category and compute per-agent dimensions."""
        if not results:
            return []

        groups: dict[str, list[EvalResult]] = {}
        for r in results:
            groups.setdefault(r.category, []).append(r)

        per_agent: list[PerAgentScores] = []
        for agent_path, group in sorted(groups.items()):
            total = len(group)
            unit_success = sum(1 for r in group if r.passed) / total
            tool_precision = sum(r.tool_use_accuracy for r in group) / total
            # tool_recall approximated from passed + tool_use combined
            tool_recall = sum(
                1 for r in group if r.passed and r.tool_use_accuracy > 0.5
            ) / total
            policy_adherence = sum(1 for r in group if r.safety_passed) / total
            avg_latency_ms = sum(r.latency_ms for r in group) / total
            escalation_appropriateness = sum(
                1 for r in group if r.routing_correct
            ) / total

            per_agent.append(PerAgentScores(
                agent_path=agent_path,
                unit_success=round(unit_success, 4),
                tool_precision=round(tool_precision, 4),
                tool_recall=round(tool_recall, 4),
                policy_adherence=round(policy_adherence, 4),
                avg_latency_ms=round(avg_latency_ms, 4),
                escalation_appropriateness=round(escalation_appropriateness, 4),
            ))

        return per_agent


# ---------------------------------------------------------------------------
# Layered scoring (4-layer metric hierarchy)
# ---------------------------------------------------------------------------

@dataclass
class LayeredDimensionScores(DimensionScores):
    """Extended dimension scores with 4-layer metric hierarchy.

    Adds hard-gate, outcome, SLO, and diagnostic metrics on top of the
    original 9-dimension DimensionScores.
    """

    state_integrity: float = 1.0
    groundedness: float = 1.0
    escalation_rate: float = 0.0
    recovery_rate: float = 0.0
    clarification_quality: float = 0.5
    judge_disagreement_rate: float = 0.0
    authorization_privacy: float = 1.0
    p0_regressions: float = 0.0

    # Map metric names to their layers for quick lookup
    _LAYER_MAP: dict[str, MetricLayer] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        # Build layer map from the canonical registry
        if not self._LAYER_MAP:
            for m in METRIC_REGISTRY:
                self._LAYER_MAP[m.name] = m.layer

    def get_layer(self, metric_name: str) -> MetricLayer:
        """Return the MetricLayer for a given metric name.

        Falls back to DIAGNOSTIC if the metric is not in the registry.
        """
        return self._LAYER_MAP.get(metric_name, MetricLayer.DIAGNOSTIC)

    def get_by_layer(self, layer: MetricLayer) -> dict[str, float]:
        """Return all metric values for a given layer."""
        layer_metrics = get_metrics_by_layer(layer)
        result: dict[str, float] = {}
        for m in layer_metrics:
            value = getattr(self, m.name, None)
            if value is not None:
                result[m.name] = value
        return result

    def check_hard_gates(self) -> tuple[bool, list[str]]:
        """Check all hard-gate metrics against their thresholds.

        Returns:
            (passed, violations) where violations lists each failing gate.
        """
        violations: list[str] = []
        gate_metrics = get_metrics_by_layer(MetricLayer.HARD_GATE)

        for m in gate_metrics:
            value = getattr(self, m.name, None)
            if value is None or m.threshold is None:
                continue
            if m.direction == "maximize" and value < m.threshold:
                violations.append(
                    f"{m.name}: {value:.4f} < threshold {m.threshold}"
                )
            elif m.direction == "minimize" and value > m.threshold:
                violations.append(
                    f"{m.name}: {value:.4f} > threshold {m.threshold}"
                )

        return (len(violations) == 0, violations)

    def to_dict(self) -> dict[str, float]:
        """Serialize all dimensions including layered extensions."""
        base = super().to_dict()
        base.update({
            "state_integrity": self.state_integrity,
            "groundedness": self.groundedness,
            "escalation_rate": self.escalation_rate,
            "recovery_rate": self.recovery_rate,
            "clarification_quality": self.clarification_quality,
            "judge_disagreement_rate": self.judge_disagreement_rate,
            "authorization_privacy": self.authorization_privacy,
            "p0_regressions": self.p0_regressions,
        })
        return base


class LayeredScorer:
    """Scorer that wraps EnhancedScorer and adds 4-layer metric hierarchy.

    Layer 1 (Hard Gates): Binary pass/fail — any failure vetoes promotion.
    Layer 2 (Outcomes): North-star metrics for weighted optimization.
    Layer 3 (SLOs): Operating thresholds that trigger alerts.
    Layer 4 (Diagnostics): Never optimised directly, used for root-cause.
    """

    # Default SLO thresholds (can be overridden via slo_config)
    DEFAULT_SLOS: dict[str, float] = {
        "latency_p50": 2000.0,
        "latency_p95": 5000.0,
        "latency_p99": 10000.0,
        "escalation_rate": 0.2,
    }

    def __init__(self, mode: str = "constrained") -> None:
        self._enhanced = EnhancedScorer(mode=mode)

    def score(self, results: list[EvalResult]) -> CompositeScore:
        """Score results using EnhancedScorer, then attach layered dimensions."""
        composite = self._enhanced.score(results)

        # Build layered dimensions from the base dimensions
        base_dims = composite.dimensions or DimensionScores()
        layered = LayeredDimensionScores(
            # Inherit all base dimension values
            task_success_rate=base_dims.task_success_rate,
            response_quality=base_dims.response_quality,
            safety_compliance=base_dims.safety_compliance,
            latency_p50=base_dims.latency_p50,
            latency_p95=base_dims.latency_p95,
            latency_p99=base_dims.latency_p99,
            token_cost=base_dims.token_cost,
            tool_correctness=base_dims.tool_correctness,
            routing_accuracy=base_dims.routing_accuracy,
            handoff_fidelity=base_dims.handoff_fidelity,
            user_satisfaction_proxy=base_dims.user_satisfaction_proxy,
            # Layered extensions — compute from results
            state_integrity=self._compute_state_integrity(results),
            groundedness=self._compute_groundedness(results),
            escalation_rate=self._compute_escalation_rate(results),
            recovery_rate=self._compute_recovery_rate(results),
            p0_regressions=self._compute_p0_regressions(results),
        )

        composite.dimensions = layered
        return composite

    def check_gates(
        self, dimensions: LayeredDimensionScores
    ) -> tuple[bool, list[str]]:
        """Check hard-gate layer metrics. Delegates to dimensions."""
        return dimensions.check_hard_gates()

    def compute_outcome_score(
        self, dimensions: LayeredDimensionScores
    ) -> float:
        """Compute weighted Layer 2 (outcome) score.

        Uses weights from the METRIC_REGISTRY for outcome-layer metrics.
        """
        outcome_metrics = get_metrics_by_layer(MetricLayer.OUTCOME)
        total_weight = sum(m.weight for m in outcome_metrics)
        if total_weight == 0:
            return 0.0

        weighted_sum = 0.0
        for m in outcome_metrics:
            value = getattr(dimensions, m.name, 0.0)
            weighted_sum += value * m.weight

        return round(weighted_sum / total_weight, 4)

    def check_slos(
        self,
        dimensions: LayeredDimensionScores,
        slo_config: dict[str, float] | None = None,
    ) -> tuple[bool, list[str]]:
        """Check SLO-layer metrics against thresholds.

        Args:
            dimensions: The layered dimension scores to check.
            slo_config: Optional override thresholds. Keys are metric names,
                values are threshold values. Defaults to DEFAULT_SLOS.

        Returns:
            (all_pass, violations) list.
        """
        thresholds = slo_config if slo_config is not None else self.DEFAULT_SLOS
        violations: list[str] = []
        slo_metrics = get_metrics_by_layer(MetricLayer.SLO)

        for m in slo_metrics:
            if m.name not in thresholds:
                continue
            threshold = thresholds[m.name]
            value = getattr(dimensions, m.name, None)
            if value is None:
                continue
            if m.direction == "minimize" and value > threshold:
                violations.append(
                    f"SLO breach: {m.name}={value:.4f} > {threshold}"
                )
            elif m.direction == "maximize" and value < threshold:
                violations.append(
                    f"SLO breach: {m.name}={value:.4f} < {threshold}"
                )

        return (len(violations) == 0, violations)

    # ------------------------------------------------------------------
    # Internal metric computation from results
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_state_integrity(results: list[EvalResult]) -> float:
        """State integrity: fraction of results with no state corruption.

        Uses handoff_context_preserved as a proxy — if context survived
        handoff, state integrity is maintained.
        """
        if not results:
            return 1.0
        return sum(
            1 for r in results if r.handoff_context_preserved
        ) / len(results)

    @staticmethod
    def _compute_groundedness(results: list[EvalResult]) -> float:
        """Groundedness: proxy from quality scores and safety compliance.

        Higher quality + safety suggests more grounded responses.
        """
        if not results:
            return 1.0
        return sum(
            min(1.0, r.quality_score * 0.7 + (1.0 if r.safety_passed else 0.0) * 0.3)
            for r in results
        ) / len(results)

    @staticmethod
    def _compute_escalation_rate(results: list[EvalResult]) -> float:
        """Escalation rate: fraction of cases where routing was incorrect.

        Incorrect routing is a proxy for inappropriate escalation.
        """
        if not results:
            return 0.0
        return sum(
            1 for r in results if not r.routing_correct
        ) / len(results)

    @staticmethod
    def _compute_recovery_rate(results: list[EvalResult]) -> float:
        """Recovery rate: fraction of initially-failed cases that still passed.

        Uses quality_score < 0.5 as "initially struggling" and passed=True
        as "recovered".
        """
        if not results:
            return 0.0
        struggling = [r for r in results if r.quality_score < 0.5]
        if not struggling:
            return 1.0  # nothing to recover from
        recovered = sum(1 for r in struggling if r.passed)
        return recovered / len(struggling)

    @staticmethod
    def _compute_p0_regressions(results: list[EvalResult]) -> float:
        """P0 regression count: number of regression-category failures."""
        if not results:
            return 0.0
        regression_failures = sum(
            1 for r in results
            if r.category == "regression" and not r.passed
        )
        return float(regression_failures)
