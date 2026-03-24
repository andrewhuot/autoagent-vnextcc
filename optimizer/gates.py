"""Accept/reject gates for optimization proposals."""

from __future__ import annotations

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
        if candidate.composite <= baseline.composite:
            return (
                False,
                f"No improvement: candidate={candidate.composite:.4f} <= baseline={baseline.composite:.4f}",
            )
        return (
            True,
            f"Improved: {candidate.composite:.4f} > {baseline.composite:.4f} (+{candidate.composite - baseline.composite:.4f})",
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
            f"All gates passed. Composite: {baseline.composite:.4f} -> {candidate.composite:.4f}",
        )
