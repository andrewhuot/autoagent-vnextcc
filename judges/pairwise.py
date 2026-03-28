"""Pairwise comparison judge — head-to-head response ranking.

Compares two responses directly to determine which is better according to
the supplied criteria, and extends this to ranking an arbitrary-length
list of responses via repeated pairwise comparisons.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from judges.llm_judge import LLMJudge


@dataclass
class PairwiseComparison:
    """Result of a single head-to-head comparison.

    Attributes:
        response_a: The first response compared.
        response_b: The second response compared.
        winner: ``"a"``, ``"b"``, or ``"tie"``.
        confidence: Confidence in the winner decision, in [0, 1].
        reasoning: Free-text explanation of why the winner was chosen.
    """

    response_a: str
    response_b: str
    winner: str
    confidence: float
    reasoning: str

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe plain dict."""
        return {
            "response_a": self.response_a,
            "response_b": self.response_b,
            "winner": self.winner,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PairwiseComparison:
        """Deserialise from a plain dict."""
        return cls(
            response_a=data["response_a"],
            response_b=data["response_b"],
            winner=data["winner"],
            confidence=data["confidence"],
            reasoning=data["reasoning"],
        )


class PairwiseJudge:
    """Judge that compares responses head-to-head and ranks ordered lists.

    Internally uses an :class:`~judges.llm_judge.LLMJudge` to score each
    response individually against the input and criteria, then derives
    win/lose/tie from the score difference.

    Args:
        judge_id: Identifier for the underlying judge (default ``"pairwise_judge"``).
        tie_threshold: Score delta below which the result is considered a tie
            (default 0.05).
    """

    _DEFAULT_JUDGE_ID = "pairwise_judge"

    def __init__(
        self,
        judge_id: str = _DEFAULT_JUDGE_ID,
        tie_threshold: float = 0.05,
    ) -> None:
        self.judge_id = judge_id
        self.tie_threshold = tie_threshold
        self._judge = LLMJudge(judge_id=judge_id)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compare(
        self,
        input_text: str,
        response_a: str,
        response_b: str,
        criteria: dict,
    ) -> PairwiseComparison:
        """Compare two responses against the same input and criteria.

        Scores both responses independently and derives a winner from the
        score difference.  When the difference falls within *tie_threshold*
        the result is a tie.

        Args:
            input_text: The task or prompt text.
            response_a: First candidate response.
            response_b: Second candidate response.
            criteria: Evaluation criteria dict (values extracted as strings).

        Returns:
            A :class:`PairwiseComparison` with the winner and confidence.
        """
        criteria_list = self._extract_criteria_list(criteria)

        verdict_a = self._judge.evaluate(
            task=input_text, response=response_a, criteria=criteria_list
        )
        verdict_b = self._judge.evaluate(
            task=input_text, response=response_b, criteria=criteria_list
        )

        score_a = verdict_a.score
        score_b = verdict_b.score
        delta = score_a - score_b

        if abs(delta) <= self.tie_threshold:
            winner = "tie"
            confidence = 1.0 - abs(delta) / (self.tie_threshold + 1e-9)
        elif delta > 0:
            winner = "a"
            confidence = min(1.0, abs(delta) / (1.0 - self.tie_threshold + 1e-9))
        else:
            winner = "b"
            confidence = min(1.0, abs(delta) / (1.0 - self.tie_threshold + 1e-9))

        reasoning_parts = []
        if verdict_a.evidence_spans:
            reasoning_parts.append(f"A evidence: {verdict_a.evidence_spans[0]}")
        if verdict_b.evidence_spans:
            reasoning_parts.append(f"B evidence: {verdict_b.evidence_spans[0]}")
        reasoning_parts.append(
            f"Scores — A: {score_a:.4f}, B: {score_b:.4f}; winner: {winner}"
        )
        reasoning = " | ".join(reasoning_parts)

        return PairwiseComparison(
            response_a=response_a,
            response_b=response_b,
            winner=winner,
            confidence=round(confidence, 6),
            reasoning=reasoning,
        )

    def rank(
        self,
        input_text: str,
        responses: list[str],
        criteria: dict,
    ) -> list[tuple[int, float]]:
        """Rank a list of responses from best to worst using pairwise wins.

        Scores every response independently, then returns indices sorted by
        score descending.  When two responses share the same score they are
        further ordered by their original index for stability.

        Args:
            input_text: The task or prompt text.
            responses: Candidate responses to rank (at least one).
            criteria: Evaluation criteria dict.

        Returns:
            List of ``(original_index, score)`` tuples ordered best-first.
            The score is the raw judge score for that response.
        """
        if not responses:
            return []

        criteria_list = self._extract_criteria_list(criteria)
        scored: list[tuple[int, float]] = []

        for idx, response in enumerate(responses):
            verdict = self._judge.evaluate(
                task=input_text, response=response, criteria=criteria_list
            )
            scored.append((idx, verdict.score))

        # Sort by score descending; ties broken by original index ascending
        scored.sort(key=lambda t: (-t[1], t[0]))
        return scored

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
