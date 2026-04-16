"""Accept/reject gates for optimization proposals."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from evals.scorer import CompositeScore


class Gates:
    """Three-stage gate: safety (hard), improvement (soft), regression (soft)."""

    def __init__(self, regression_threshold: float = 0.05) -> None:
        self.regression_threshold = regression_threshold

    def check_safety(self, candidate: CompositeScore) -> tuple[bool, str]:
        """Hard gate: any safety failure = reject."""
        if candidate.safety_failures > 0:
            return False, f"Safety hard gate failed: {candidate.safety_failures} safety failures"
        return True, "Safety gate passed"

    def check_improvement(
        self, candidate: CompositeScore, baseline: CompositeScore
    ) -> tuple[bool, str]:
        """Soft gate: composite score must improve."""
        delta_summary = self._delta_summary(candidate, baseline)
        if candidate.composite <= baseline.composite:
            return (
                False,
                (
                    f"No improvement: candidate={candidate.composite:.4f} <= "
                    f"baseline={baseline.composite:.4f} ({delta_summary})"
                ),
            )
        return (
            True,
            (
                f"Improved: {candidate.composite:.4f} > {baseline.composite:.4f} "
                f"(+{candidate.composite - baseline.composite:.4f}; {delta_summary})"
            ),
        )

    def check_regression(
        self, candidate: CompositeScore, baseline: CompositeScore
    ) -> tuple[bool, str]:
        """Regression gate: no metric drops more than threshold."""
        if candidate.has_regression(baseline, self.regression_threshold):
            details: list[str] = []
            threshold = self.regression_threshold

            if baseline.quality > 0 and (baseline.quality - candidate.quality) / baseline.quality > threshold:
                details.append(
                    f"quality dropped {baseline.quality:.4f} -> {candidate.quality:.4f}"
                )
            if baseline.safety > 0 and (baseline.safety - candidate.safety) / baseline.safety > threshold:
                details.append(
                    f"safety dropped {baseline.safety:.4f} -> {candidate.safety:.4f}"
                )
            if baseline.latency > 0 and (baseline.latency - candidate.latency) / baseline.latency > threshold:
                details.append(
                    f"latency regressed {baseline.latency:.4f} -> {candidate.latency:.4f}"
                )
            if baseline.cost > 0 and (baseline.cost - candidate.cost) / baseline.cost > threshold:
                details.append(
                    f"cost regressed {baseline.cost:.4f} -> {candidate.cost:.4f}"
                )

            return False, f"Regression detected: {'; '.join(details)}"
        return True, "No regression detected"

    def check_constraints(self, candidate: CompositeScore) -> tuple[bool, str]:
        """Hard gate: check constraint violations from ConstrainedScorer.

        If the candidate score carries ``constraints_passed`` / ``constraint_violations``
        metadata (set by :class:`ConstrainedScorer`), use them.  Otherwise fall back to
        the legacy :meth:`check_safety` check for backwards compatibility.
        """
        # Use constraint metadata when available
        if hasattr(candidate, "constraint_violations") and candidate.constraint_violations:
            details = "; ".join(candidate.constraint_violations)
            return False, f"Constraint violations: {details}"
        if hasattr(candidate, "constraints_passed") and not candidate.constraints_passed:
            return False, "Constraint check failed (no details)"
        # Fallback: legacy safety-only check
        return self.check_safety(candidate)

    def evaluate(
        self, candidate: CompositeScore, baseline: CompositeScore
    ) -> tuple[bool, str, str]:
        """Run all gates. Returns (accepted, status_string, reason)."""
        # Constraint gate (hard) — supersedes plain safety check
        ok, msg = self.check_constraints(candidate)
        if not ok:
            return False, "rejected_constraints", msg

        # Improvement gate
        ok, msg = self.check_improvement(candidate, baseline)
        if not ok:
            return False, "rejected_no_improvement", msg

        # Regression gate
        ok, msg = self.check_regression(candidate, baseline)
        if not ok:
            return False, "rejected_regression", msg

        return (
            True,
            "accepted",
            (
                "All gates passed. Composite: "
                f"{baseline.composite:.4f} -> {candidate.composite:.4f} "
                f"({self._delta_summary(candidate, baseline)})"
            ),
        )

    @staticmethod
    def _delta_summary(candidate: CompositeScore, baseline: CompositeScore) -> str:
        """Return a compact per-metric delta summary for operator transparency."""
        return (
            f"quality {candidate.quality - baseline.quality:+.4f}, "
            f"safety {candidate.safety - baseline.safety:+.4f}, "
            f"latency {candidate.latency - baseline.latency:+.4f}, "
            f"cost {candidate.cost - baseline.cost:+.4f}"
        )


class RejectionReason(str, Enum):
    """Structured reason an optimization proposal was rejected."""

    SAFETY_VIOLATION = "safety_violation"
    REGRESSION_DETECTED = "regression_detected"
    NO_SIGNIFICANT_IMPROVEMENT = "no_significant_improvement"
    GATE_FAILED = "gate_failed"
    COVERAGE_INSUFFICIENT = "coverage_insufficient"


@dataclass
class RejectionRecord:
    """Structured record of why a candidate was rejected by the gate evaluator."""

    attempt_id: str
    reason: RejectionReason
    detail: str
    baseline_score: float | None = None
    candidate_score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "reason": self.reason.value,
            "detail": self.detail,
            "baseline_score": self.baseline_score,
            "candidate_score": self.candidate_score,
            "metadata": dict(self.metadata),
        }


def rejection_from_status(status: str) -> RejectionReason:
    """Map a legacy ``Gates.evaluate`` status string to a :class:`RejectionReason`.

    Lets R1.7 callers convert without re-running the gates. Raises ``ValueError``
    for ``"accepted"`` or any other non-rejection status.
    """
    if status == "rejected_constraints":
        return RejectionReason.SAFETY_VIOLATION
    if status == "rejected_regression":
        return RejectionReason.REGRESSION_DETECTED
    if status == "rejected_no_improvement":
        return RejectionReason.NO_SIGNIFICANT_IMPROVEMENT
    if status.startswith("rejected_"):
        return RejectionReason.GATE_FAILED
    raise ValueError(f"Not a rejection status: {status!r}")
