"""Training escalation monitor for failure families resistant to prompt fixes.

When prompt-level mutations repeatedly fail to resolve a failure family,
this module recommends escalation to model training (SFT, DPO, RFT)
based on stability, volume, and prompt fix success rate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TrainingMethod(str, Enum):
    """Training methods for escalation beyond prompt optimization."""

    SFT = "sft"
    DPO = "dpo"
    RFT = "rft"


@dataclass
class FailureFamilyStability:
    """Tracks stability of a failure family across optimization cycles.

    A failure family is considered stable when it has been observed for
    enough cycles with sufficient volume, indicating that it is a
    persistent pattern rather than transient noise.
    """

    failure_family: str
    cycle_count: int = 0
    prompt_fix_attempts: int = 0
    prompt_fix_successes: int = 0
    volume: int = 0

    @property
    def is_stable(self) -> bool:
        """A family is stable if observed for >= 5 cycles with >= 20 total occurrences."""
        return self.cycle_count >= 5 and self.volume >= 20

    @property
    def prompt_fix_rate(self) -> float:
        """Success rate of prompt-level fixes for this failure family."""
        return self.prompt_fix_successes / max(self.prompt_fix_attempts, 1)


@dataclass
class TrainingRecommendation:
    """Recommendation to escalate from prompt optimization to model training.

    Generated when a failure family is stable, high-volume, and resistant
    to prompt-level fixes.
    """

    failure_family: str
    recommended_method: TrainingMethod
    confidence: float
    estimated_improvement: float
    dataset_size: int
    reasoning: str


class TrainingEscalationMonitor:
    """Monitor failure families and recommend training escalation when prompt fixes plateau.

    Tracks each failure family's stability across optimization cycles and
    recommends SFT, DPO, or RFT based on the prompt fix success rate:
    - fix_rate < 0.1  -> SFT (fundamental capability gap)
    - fix_rate 0.1-0.3 -> DPO (preference alignment needed)
    - fix_rate 0.3-0.5 -> RFT (reward-guided fine-tuning)
    - fix_rate > 0.5  -> None (prompt fixes are still working)
    """

    def __init__(self) -> None:
        self.families: dict[str, FailureFamilyStability] = {}

    def record_cycle(
        self,
        failure_family: str,
        volume: int,
        prompt_fix_attempted: bool,
        prompt_fix_succeeded: bool,
    ) -> None:
        """Record one optimization cycle's data for a failure family.

        Args:
            failure_family: The failure family identifier.
            volume: Number of occurrences observed in this cycle.
            prompt_fix_attempted: Whether a prompt fix was attempted.
            prompt_fix_succeeded: Whether the prompt fix resolved the issue.
        """
        if failure_family not in self.families:
            self.families[failure_family] = FailureFamilyStability(
                failure_family=failure_family,
            )

        entry = self.families[failure_family]
        entry.cycle_count += 1
        entry.volume += volume
        if prompt_fix_attempted:
            entry.prompt_fix_attempts += 1
            if prompt_fix_succeeded:
                entry.prompt_fix_successes += 1

    def check_escalation(self, failure_family: str) -> TrainingRecommendation | None:
        """Check if a failure family should escalate to model training.

        Returns a TrainingRecommendation if the family is stable, high-volume,
        and has a low prompt fix rate. Returns None if prompt fixes are still
        working (fix_rate > 0.5) or the family is not yet stable.
        """
        entry = self.families.get(failure_family)
        if entry is None:
            return None

        if not entry.is_stable:
            return None

        fix_rate = entry.prompt_fix_rate
        if fix_rate > 0.5:
            return None

        # Select method based on fix rate
        if fix_rate < 0.1:
            method = TrainingMethod.SFT
            confidence = 0.8
            estimated_improvement = 0.3
            reasoning = (
                f"Failure family '{failure_family}' has a prompt fix rate of "
                f"{fix_rate:.2f} across {entry.prompt_fix_attempts} attempts. "
                f"This suggests a fundamental capability gap best addressed by SFT."
            )
        elif fix_rate < 0.3:
            method = TrainingMethod.DPO
            confidence = 0.7
            estimated_improvement = 0.25
            reasoning = (
                f"Failure family '{failure_family}' has a prompt fix rate of "
                f"{fix_rate:.2f} across {entry.prompt_fix_attempts} attempts. "
                f"Partial prompt success suggests preference alignment via DPO."
            )
        else:
            method = TrainingMethod.RFT
            confidence = 0.6
            estimated_improvement = 0.2
            reasoning = (
                f"Failure family '{failure_family}' has a prompt fix rate of "
                f"{fix_rate:.2f} across {entry.prompt_fix_attempts} attempts. "
                f"Moderate prompt success suggests reward-guided fine-tuning via RFT."
            )

        return TrainingRecommendation(
            failure_family=failure_family,
            recommended_method=method,
            confidence=confidence,
            estimated_improvement=estimated_improvement,
            dataset_size=entry.volume,
            reasoning=reasoning,
        )

    def get_all_recommendations(self) -> list[TrainingRecommendation]:
        """Return training recommendations for all tracked failure families.

        Only returns recommendations for families that meet the escalation
        criteria (stable, high-volume, low prompt fix rate).
        """
        recommendations: list[TrainingRecommendation] = []
        for family_name in sorted(self.families.keys()):
            rec = self.check_escalation(family_name)
            if rec is not None:
                recommendations.append(rec)
        return recommendations
