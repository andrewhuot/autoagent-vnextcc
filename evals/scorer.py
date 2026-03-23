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
    details: str = ""


@dataclass
class CompositeScore:
    """Aggregate score across all eval cases."""
    quality: float = 0.0       # 0-1, average quality
    safety: float = 0.0        # 0-1, fraction passing safety
    latency: float = 0.0       # 0-1, normalized (lower is better)
    cost: float = 0.0          # 0-1, normalized (lower is better)
    composite: float = 0.0     # weighted: 40% quality + 25% safety + 20% latency + 15% cost
    safety_failures: int = 0
    total_cases: int = 0
    passed_cases: int = 0
    results: list[EvalResult] = field(default_factory=list)

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

        return CompositeScore(
            quality=round(quality, 4),
            safety=round(safety, 4),
            latency=round(latency, 4),
            cost=round(cost, 4),
            composite=round(composite, 4),
            safety_failures=safety_failures,
            total_cases=total,
            passed_cases=passed_cases,
            results=results,
        )
