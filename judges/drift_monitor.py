"""Drift detection — monitor judges for agreement drift and scoring biases.

Runs sliding-window checks over judge verdicts to surface early warnings
when a judge starts disagreeing with its historical baseline or exhibits
positional or verbosity bias.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from judges.calibration import JudgeCalibrationSuite


@dataclass
class DriftAlert:
    """A detected drift or bias event."""

    alert_id: str
    grader_id: str
    alert_type: str  # "agreement_drift" | "position_bias" | "verbosity_bias"
    severity: float  # 0.0–1.0
    window_start: float
    window_end: float
    details: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """Serialize to a plain dict."""
        return {
            "alert_id": self.alert_id,
            "grader_id": self.grader_id,
            "alert_type": self.alert_type,
            "severity": self.severity,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "details": self.details,
            "created_at": self.created_at,
        }


class DriftMonitor:
    """Monitors judge verdicts for drift and bias patterns."""

    def __init__(
        self,
        calibration_suite: JudgeCalibrationSuite | None = None,
        drift_threshold: float = 0.1,
    ) -> None:
        self._calibration_suite = calibration_suite
        self.drift_threshold = drift_threshold

    def check_agreement_drift(
        self,
        verdicts: list[dict],
        window_size: int = 50,
    ) -> DriftAlert | None:
        """Compare recent window agreement vs historical; alert if drift exceeds threshold.

        Each verdict dict must contain at least 'score' (float) and
        'expected' (float) keys.  Agreement means |score - expected| <= 0.1.
        """
        if len(verdicts) < window_size:
            return None

        recent = verdicts[-window_size:]
        historical = verdicts[:-window_size]

        if not historical:
            return None

        def _agreement_rate(window: list[dict]) -> float:
            agreed = sum(
                1 for v in window if abs(v["score"] - v["expected"]) <= 0.1
            )
            return agreed / len(window)

        recent_rate = _agreement_rate(recent)
        historical_rate = _agreement_rate(historical)
        drift = historical_rate - recent_rate

        if drift <= self.drift_threshold:
            return None

        severity = min(drift, 1.0)
        grader_id = verdicts[0].get("grader_id", "unknown")
        now = time.time()

        return DriftAlert(
            alert_id=uuid.uuid4().hex[:12],
            grader_id=grader_id,
            alert_type="agreement_drift",
            severity=severity,
            window_start=now - len(verdicts),
            window_end=now,
            details={
                "historical_agreement": round(historical_rate, 4),
                "recent_agreement": round(recent_rate, 4),
                "drift": round(drift, 4),
            },
        )

    def check_position_bias(
        self,
        verdicts_ab: list[tuple],
        threshold: float = 0.1,
    ) -> DriftAlert | None:
        """Check if score changes when presentation order swaps.

        Each tuple is (score_order_a, score_order_b) for the same content.
        """
        if not verdicts_ab:
            return None

        total_diff = sum(abs(a - b) for a, b in verdicts_ab)
        mean_diff = total_diff / len(verdicts_ab)

        if mean_diff <= threshold:
            return None

        severity = min(mean_diff, 1.0)
        now = time.time()

        return DriftAlert(
            alert_id=uuid.uuid4().hex[:12],
            grader_id="unknown",
            alert_type="position_bias",
            severity=severity,
            window_start=now - len(verdicts_ab),
            window_end=now,
            details={
                "mean_position_diff": round(mean_diff, 4),
                "sample_count": len(verdicts_ab),
            },
        )

    def check_verbosity_bias(
        self,
        short_verdicts: list[float],
        long_verdicts: list[float],
        threshold: float = 0.1,
    ) -> DriftAlert | None:
        """Check if longer responses systematically get higher scores."""
        if not short_verdicts or not long_verdicts:
            return None

        avg_short = sum(short_verdicts) / len(short_verdicts)
        avg_long = sum(long_verdicts) / len(long_verdicts)
        bias = avg_long - avg_short

        if abs(bias) <= threshold:
            return None

        severity = min(abs(bias), 1.0)
        now = time.time()

        return DriftAlert(
            alert_id=uuid.uuid4().hex[:12],
            grader_id="unknown",
            alert_type="verbosity_bias",
            severity=severity,
            window_start=now - max(len(short_verdicts), len(long_verdicts)),
            window_end=now,
            details={
                "avg_short_score": round(avg_short, 4),
                "avg_long_score": round(avg_long, 4),
                "bias": round(bias, 4),
            },
        )

    def run_all_checks(
        self,
        verdicts: list[dict],
        verdicts_ab: list[tuple] | None = None,
        short_verdicts: list[float] | None = None,
        long_verdicts: list[float] | None = None,
    ) -> list[DriftAlert]:
        """Run all applicable checks and return any triggered alerts."""
        alerts: list[DriftAlert] = []

        drift_alert = self.check_agreement_drift(verdicts)
        if drift_alert is not None:
            alerts.append(drift_alert)

        if verdicts_ab is not None:
            pos_alert = self.check_position_bias(verdicts_ab)
            if pos_alert is not None:
                alerts.append(pos_alert)

        if short_verdicts is not None and long_verdicts is not None:
            verb_alert = self.check_verbosity_bias(short_verdicts, long_verdicts)
            if verb_alert is not None:
                alerts.append(verb_alert)

        return alerts
