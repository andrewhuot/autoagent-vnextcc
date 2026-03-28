"""Panel judge — multi-judge voting with configurable tie-break strategies.

Aggregates verdicts from a pool of judges using majority vote or score
averaging, computes inter-judge agreement, and applies a tie-break
strategy when scores are too spread out to decide automatically.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from judges.llm_judge import LLMJudge


@dataclass
class PanelVote:
    """A single judge's vote in a panel evaluation.

    Attributes:
        judge_id: Identifier of the judge that produced this vote.
        score: Numeric score in [0, 1].
        confidence: Judge's self-reported confidence in [0, 1].
        reasoning: Free-text explanation of the score.
    """

    judge_id: str
    score: float
    confidence: float
    reasoning: str

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe plain dict."""
        return {
            "judge_id": self.judge_id,
            "score": self.score,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PanelVote:
        """Deserialise from a plain dict."""
        return cls(
            judge_id=data["judge_id"],
            score=data["score"],
            confidence=data["confidence"],
            reasoning=data["reasoning"],
        )


@dataclass
class PanelResult:
    """Aggregated result from a panel of judges.

    Attributes:
        votes: Individual votes from each judge.
        final_score: Aggregated score in [0, 1].
        agreement: Fraction of judges within ±0.2 of the final score.
        tie_broken: True if the tie-break strategy was applied.
    """

    votes: list[PanelVote]
    final_score: float
    agreement: float
    tie_broken: bool

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe plain dict."""
        return {
            "votes": [v.to_dict() for v in self.votes],
            "final_score": self.final_score,
            "agreement": self.agreement,
            "tie_broken": self.tie_broken,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PanelResult:
        """Deserialise from a plain dict."""
        return cls(
            votes=[PanelVote.from_dict(v) for v in data.get("votes", [])],
            final_score=data["final_score"],
            agreement=data["agreement"],
            tie_broken=data["tie_broken"],
        )


class PanelJudge:
    """A composite judge that aggregates verdicts from multiple underlying judges.

    Each judge in the panel independently evaluates the same input/output
    pair, then votes are aggregated according to *tie_break_strategy*.

    Args:
        judge_ids: Ordered list of judge identifiers that form the panel.
            Each identifier maps to an :class:`~judges.llm_judge.LLMJudge`
            instance created internally.
        tie_break_strategy: How to aggregate votes when they diverge.
            One of ``"median"`` (default), ``"mean"``, or
            ``"confidence_weighted"``.
    """

    _AGREEMENT_BAND = 0.2  # votes within this of final_score "agree"

    def __init__(
        self,
        judge_ids: list[str],
        tie_break_strategy: str = "median",
    ) -> None:
        if not judge_ids:
            raise ValueError("PanelJudge requires at least one judge_id.")
        valid_strategies = {"median", "mean", "confidence_weighted"}
        if tie_break_strategy not in valid_strategies:
            raise ValueError(
                f"tie_break_strategy must be one of {valid_strategies}, "
                f"got '{tie_break_strategy}'"
            )
        self.judge_ids = list(judge_ids)
        self.tie_break_strategy = tie_break_strategy
        # Create one LLMJudge per judge_id (mock backend; swap for real judges in prod)
        self._judges: dict[str, LLMJudge] = {
            jid: LLMJudge(judge_id=jid) for jid in judge_ids
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        input_text: str,
        output_text: str,
        criteria: dict,
    ) -> PanelResult:
        """Run all panel judges on the given input/output pair and aggregate.

        Args:
            input_text: The task or question text.
            output_text: The response to evaluate.
            criteria: Evaluation criteria as a dict (e.g. ``{"rubric": "..."}``;
                string values are extracted and passed to each underlying judge).

        Returns:
            A :class:`PanelResult` with individual votes and the aggregated score.
        """
        criteria_list = self._extract_criteria_list(criteria)
        votes: list[PanelVote] = []

        for jid, judge in self._judges.items():
            verdict = judge.evaluate(
                task=input_text,
                response=output_text,
                criteria=criteria_list,
            )
            votes.append(
                PanelVote(
                    judge_id=jid,
                    score=verdict.score,
                    confidence=verdict.confidence,
                    reasoning="; ".join(verdict.evidence_spans) or (
                        "; ".join(verdict.failure_reasons) or "no reasoning"
                    ),
                )
            )

        final_score = self._aggregate_votes(votes)
        agreement = self._compute_agreement(votes)
        tie_broken = self._was_tie_broken(votes)

        return PanelResult(
            votes=votes,
            final_score=round(final_score, 6),
            agreement=round(agreement, 6),
            tie_broken=tie_broken,
        )

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def _aggregate_votes(self, votes: list[PanelVote]) -> float:
        """Aggregate votes according to *tie_break_strategy*.

        Args:
            votes: Non-empty list of :class:`PanelVote`.

        Returns:
            Aggregated score in [0, 1].
        """
        if not votes:
            return 0.0
        scores = [v.score for v in votes]

        if self.tie_break_strategy == "median":
            return statistics.median(scores)

        if self.tie_break_strategy == "mean":
            return sum(scores) / len(scores)

        # confidence_weighted
        total_confidence = sum(v.confidence for v in votes)
        if total_confidence == 0:
            return sum(scores) / len(scores)
        return sum(v.score * v.confidence for v in votes) / total_confidence

    def _compute_agreement(self, votes: list[PanelVote]) -> float:
        """Compute fraction of votes within ±_AGREEMENT_BAND of the final score.

        Args:
            votes: List of :class:`PanelVote`.

        Returns:
            Agreement fraction in [0, 1].  Returns 1.0 for a single-judge panel.
        """
        if len(votes) <= 1:
            return 1.0
        final = self._aggregate_votes(votes)
        agreed = sum(
            1 for v in votes if abs(v.score - final) <= self._AGREEMENT_BAND
        )
        return agreed / len(votes)

    def _was_tie_broken(self, votes: list[PanelVote]) -> bool:
        """Return True if scores were spread enough to require a tie-break.

        A tie-break is considered necessary when the standard deviation of
        scores exceeds 0.2 (i.e. meaningful disagreement among panelists).
        """
        if len(votes) < 2:
            return False
        try:
            return statistics.stdev(v.score for v in votes) > 0.2
        except statistics.StatisticsError:
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_criteria_list(criteria: dict) -> list[str]:
        """Flatten a criteria dict into a list of strings for LLMJudge."""
        items: list[str] = []
        for k, v in criteria.items():
            if isinstance(v, str):
                items.append(f"{k}: {v}")
            elif isinstance(v, list):
                items.extend(str(i) for i in v)
            else:
                items.append(str(v))
        return items
