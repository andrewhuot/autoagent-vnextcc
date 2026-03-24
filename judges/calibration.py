"""Judge calibration suite — agreement, drift, and bias measurement.

Tracks human judgments alongside automated judge verdicts so we can
detect when a judge drifts out of calibration or exhibits positional
or verbosity bias.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.types import JudgeVerdict


@dataclass
class _CalibrationRecord:
    """Internal record pairing a judge verdict with a human score."""
    case_id: str
    judge_score: float
    human_score: float


class JudgeCalibrationSuite:
    """Calibration tracking and bias detection for automated judges."""

    AGREEMENT_THRESHOLD = 0.1  # judge and human agree if within this delta

    def __init__(self) -> None:
        self._records: list[_CalibrationRecord] = []

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_human_judgment(
        self,
        case_id: str,
        judge_verdict: JudgeVerdict,
        human_score: float,
    ) -> None:
        """Record a paired (judge, human) judgment for later analysis."""
        self._records.append(
            _CalibrationRecord(
                case_id=case_id,
                judge_score=judge_verdict.score,
                human_score=human_score,
            )
        )

    # ------------------------------------------------------------------
    # Agreement metrics
    # ------------------------------------------------------------------

    def agreement_rate(self) -> float:
        """Fraction of cases where judge and human agree within threshold."""
        if not self._records:
            return 0.0
        agreed = sum(
            1 for r in self._records
            if abs(r.judge_score - r.human_score) <= self.AGREEMENT_THRESHOLD
        )
        return agreed / len(self._records)

    def compute_drift(self, window: int = 50) -> float:
        """Difference in agreement rate between recent and historical windows.

        A positive value means recent agreement is LOWER than historical
        (i.e., the judge is drifting away from human consensus).

        Returns 0.0 if there are fewer than *window* records.
        """
        if len(self._records) < window:
            return 0.0

        recent = self._records[-window:]
        historical = self._records[:-window]

        if not historical:
            return 0.0

        recent_agreement = sum(
            1 for r in recent
            if abs(r.judge_score - r.human_score) <= self.AGREEMENT_THRESHOLD
        ) / len(recent)

        historical_agreement = sum(
            1 for r in historical
            if abs(r.judge_score - r.human_score) <= self.AGREEMENT_THRESHOLD
        ) / len(historical)

        return round(historical_agreement - recent_agreement, 4)

    # ------------------------------------------------------------------
    # Bias detection
    # ------------------------------------------------------------------

    def position_bias(
        self,
        verdicts_a: list[JudgeVerdict],
        verdicts_b: list[JudgeVerdict],
    ) -> float:
        """Measure positional bias between two orderings of the same content.

        Computes mean absolute score difference when the same content is
        presented in position A vs position B.  A value close to 0 indicates
        no positional bias.
        """
        if not verdicts_a or not verdicts_b:
            return 0.0
        pairs = min(len(verdicts_a), len(verdicts_b))
        total_diff = sum(
            abs(verdicts_a[i].score - verdicts_b[i].score)
            for i in range(pairs)
        )
        return round(total_diff / pairs, 4)

    def verbosity_bias(
        self,
        short_verdicts: list[JudgeVerdict],
        long_verdicts: list[JudgeVerdict],
    ) -> float:
        """Measure verbosity bias — score difference between short and long responses.

        A positive value means the judge scores longer responses higher
        (verbosity bias).  Negative means it prefers shorter responses.
        """
        if not short_verdicts or not long_verdicts:
            return 0.0
        avg_short = sum(v.score for v in short_verdicts) / len(short_verdicts)
        avg_long = sum(v.score for v in long_verdicts) / len(long_verdicts)
        return round(avg_long - avg_short, 4)

    def disagreement_rate(
        self,
        verdicts_a: list[JudgeVerdict],
        verdicts_b: list[JudgeVerdict],
    ) -> float:
        """Fraction of paired verdicts where pass/fail disagree."""
        if not verdicts_a or not verdicts_b:
            return 0.0
        pairs = min(len(verdicts_a), len(verdicts_b))
        disagreements = sum(
            1 for i in range(pairs)
            if verdicts_a[i].passed != verdicts_b[i].passed
        )
        return round(disagreements / pairs, 4)
