"""Combined trajectory + outcome evaluation.

Combines :class:`~evals.trajectory.TrajectoryEvaluator` (was the *process*
correct?) with :class:`~evals.outcome.OutcomeEvaluator` (is the *final state*
correct?) and flags discrepancies between the two signals.

Discrepancy taxonomy
--------------------
- ``"good_trajectory_bad_outcome"``   – agent took correct steps but produced
  the wrong end state (e.g., bug in tool implementation).
- ``"bad_trajectory_good_outcome"``   – agent produced the right end state via
  an unexpected or suboptimal path.
- ``None``                            – no discrepancy (both agree, or one
  dimension was not evaluated).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .outcome import OutcomeEvaluator, OutcomeResult
from .trajectory import TrajectoryEvaluator, TrajectoryExpectation, TrajectoryResult


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class CombinedEvalResult:
    """Result of a combined trajectory + outcome evaluation.

    Args:
        trajectory_result: Result from trajectory evaluation, or ``None`` when
            ``eval_mode="outcome_only"``.
        outcome_result: Result from outcome evaluation, or ``None`` when
            ``eval_mode="trajectory_only"``.
        discrepancy: A human-readable label for any detected discrepancy, or
            ``None`` when trajectory and outcome agree.
        combined_score: Weighted average of the available sub-scores (0–1).
        eval_mode: One of ``"trajectory_only"``, ``"outcome_only"``, or
            ``"combined"``.
    """

    trajectory_result: TrajectoryResult | None
    outcome_result: OutcomeResult | None
    discrepancy: str | None
    combined_score: float
    eval_mode: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "trajectory_result": self.trajectory_result.to_dict()
            if self.trajectory_result is not None
            else None,
            "outcome_result": self.outcome_result.to_dict()
            if self.outcome_result is not None
            else None,
            "discrepancy": self.discrepancy,
            "combined_score": self.combined_score,
            "eval_mode": self.eval_mode,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CombinedEvalResult":
        traj_raw = d.get("trajectory_result")
        outcome_raw = d.get("outcome_result")
        return cls(
            trajectory_result=TrajectoryResult.from_dict(traj_raw)
            if traj_raw is not None
            else None,
            outcome_result=OutcomeResult.from_dict(outcome_raw)
            if outcome_raw is not None
            else None,
            discrepancy=d.get("discrepancy"),
            combined_score=float(d.get("combined_score", 0.0)),
            eval_mode=str(d.get("eval_mode", "combined")),
        )


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

# Thresholds for discrepancy detection
_TRAJECTORY_PASS_THRESHOLD = 0.7
_OUTCOME_PASS_THRESHOLD = 0.7

# Weights for combined score
_TRAJECTORY_WEIGHT = 0.4
_OUTCOME_WEIGHT = 0.6


class CombinedEvaluator:
    """Evaluate both trajectory and outcome and surface discrepancies.

    Usage::

        evaluator = CombinedEvaluator()
        result = evaluator.evaluate(
            actual_steps=trace["steps"],
            expected_trajectory=expectation,
            final_state=trace["final_state"],
            expected_state={"order_status": "shipped"},
            mode="combined",
        )
        print(result.combined_score, result.discrepancy)
    """

    def __init__(self) -> None:
        self._trajectory_evaluator = TrajectoryEvaluator()
        self._outcome_evaluator = OutcomeEvaluator()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        actual_steps: list[dict[str, Any]],
        expected_trajectory: TrajectoryExpectation | None,
        final_state: dict[str, Any],
        expected_state: dict[str, Any],
        mode: str = "combined",
    ) -> CombinedEvalResult:
        """Run trajectory and/or outcome evaluation depending on *mode*.

        Args:
            actual_steps: Raw step dicts from the agent run.
            expected_trajectory: The declared trajectory expectation, or
                ``None`` to skip trajectory evaluation.
            final_state: The actual end state produced by the agent.
            expected_state: Key→value pairs the final state must satisfy.
            mode: One of ``"trajectory_only"``, ``"outcome_only"``, or
                ``"combined"``.

        Returns:
            A :class:`CombinedEvalResult` with per-dimension results,
            discrepancy label, and combined score.

        Raises:
            ValueError: When *mode* is not one of the supported values.
        """
        _valid_modes = frozenset({"trajectory_only", "outcome_only", "combined"})
        if mode not in _valid_modes:
            raise ValueError(
                f"mode must be one of {sorted(_valid_modes)}, got {mode!r}"
            )

        traj_result: TrajectoryResult | None = None
        outcome_result: OutcomeResult | None = None

        # --- Trajectory ---
        if mode in ("trajectory_only", "combined"):
            if expected_trajectory is not None:
                traj_result = self._trajectory_evaluator.evaluate(
                    actual_steps, expected_trajectory
                )
            else:
                # Build a trivially-passing result when no expectation provided
                traj_result = TrajectoryResult(
                    score=1.0,
                    matched_steps=0,
                    total_expected=0,
                    total_actual=len(actual_steps),
                    mismatches=[],
                    scoring_mode="in_order_match",
                )

        # --- Outcome ---
        if mode in ("outcome_only", "combined"):
            outcome_result = self._outcome_evaluator.evaluate(final_state, expected_state)

        # --- Combined score ---
        combined_score = self._compute_combined_score(traj_result, outcome_result, mode)

        # --- Discrepancy detection ---
        discrepancy = self._detect_discrepancy(traj_result, outcome_result, mode)

        return CombinedEvalResult(
            trajectory_result=traj_result,
            outcome_result=outcome_result,
            discrepancy=discrepancy,
            combined_score=combined_score,
            eval_mode=mode,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_combined_score(
        traj: TrajectoryResult | None,
        outcome: OutcomeResult | None,
        mode: str,
    ) -> float:
        """Compute a weighted combined score from available sub-results."""
        if mode == "trajectory_only":
            return round(traj.score if traj is not None else 0.0, 4)

        if mode == "outcome_only":
            return round(outcome.score if outcome is not None else 0.0, 4)

        # combined: weighted average of both dimensions
        traj_score = traj.score if traj is not None else 0.0
        outcome_score = outcome.score if outcome is not None else 0.0

        if traj is None and outcome is not None:
            return round(outcome_score, 4)
        if outcome is None and traj is not None:
            return round(traj_score, 4)

        weighted = (
            _TRAJECTORY_WEIGHT * traj_score + _OUTCOME_WEIGHT * outcome_score
        )
        return round(weighted, 4)

    @staticmethod
    def _detect_discrepancy(
        traj: TrajectoryResult | None,
        outcome: OutcomeResult | None,
        mode: str,
    ) -> str | None:
        """Flag discrepancies between trajectory and outcome signals.

        Only meaningful in ``"combined"`` mode — returns ``None`` for single-
        dimension modes or when both dimensions agree.
        """
        if mode != "combined":
            return None
        if traj is None or outcome is None:
            return None

        traj_good = traj.score >= _TRAJECTORY_PASS_THRESHOLD
        outcome_good = outcome.score >= _OUTCOME_PASS_THRESHOLD

        if traj_good and not outcome_good:
            return (
                "good_trajectory_bad_outcome: agent followed the correct process "
                "but the final state does not match expectations — possible tool "
                "implementation bug or stale environment state."
            )

        if not traj_good and outcome_good:
            return (
                "bad_trajectory_good_outcome: agent achieved the correct final "
                "state via an unexpected path — consider whether the trajectory "
                "expectation is overly prescriptive."
            )

        return None
