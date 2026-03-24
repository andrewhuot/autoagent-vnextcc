"""Bayesian surrogate model for prompt optimization.

kNN-based surrogate with UCB acquisition over (instruction_idx, example_set_idx) space.
No external dependencies (no scipy/sklearn).
"""

from __future__ import annotations

import math


class BayesianSurrogate:
    """kNN-based surrogate model with UCB acquisition for prompt optimization."""

    def __init__(self, exploration_weight: float = 1.0, k: int = 3) -> None:
        self.observations: list[tuple[tuple[int, int], float]] = []
        self.exploration_weight = exploration_weight
        self.k = k

    def observe(self, instruction_idx: int, example_set_idx: int, score: float) -> None:
        """Record an observation."""
        self.observations.append(((instruction_idx, example_set_idx), score))

    def suggest(self, candidates: list[tuple[int, int]]) -> tuple[int, int]:
        """Suggest next candidate to evaluate using UCB acquisition.

        Returns the candidate with the highest UCB score among those not yet
        observed. If no observations exist, returns the first candidate.
        """
        if not candidates:
            raise ValueError("candidates list must not be empty")

        if not self.observations:
            return candidates[0]

        # Filter to untried candidates
        tried = {obs[0] for obs in self.observations}
        untried = [c for c in candidates if c not in tried]

        # If all candidates have been tried, pick from full list by UCB
        pool = untried if untried else candidates

        best_candidate = pool[0]
        best_ucb = self._ucb_score(pool[0])
        for candidate in pool[1:]:
            ucb = self._ucb_score(candidate)
            if ucb > best_ucb:
                best_ucb = ucb
                best_candidate = candidate

        return best_candidate

    def _estimate_score(self, candidate: tuple[int, int]) -> float:
        """Estimate score for a candidate via weighted kNN.

        Uses the top-k most similar observations, weighted by similarity.
        If no similar observations exist, returns 0.0.
        """
        if not self.observations:
            return 0.0

        # Compute (similarity, score) for all observations
        scored = [
            (self._similarity(candidate, obs[0]), obs[1])
            for obs in self.observations
        ]
        # Sort by similarity descending, take top-k
        scored.sort(key=lambda x: x[0], reverse=True)
        top_k = scored[: self.k]

        total_weight = sum(sim for sim, _ in top_k)
        if total_weight == 0.0:
            return 0.0

        weighted_sum = sum(sim * score for sim, score in top_k)
        return weighted_sum / total_weight

    def _ucb_score(self, candidate: tuple[int, int]) -> float:
        """UCB = estimated_score + exploration_weight / sqrt(1 + n_similar).

        n_similar is the count of observations with similarity > 0 to this candidate.
        """
        estimate = self._estimate_score(candidate)
        n_similar = sum(
            1 for obs in self.observations
            if self._similarity(candidate, obs[0]) > 0.0
        )
        exploration_bonus = self.exploration_weight / math.sqrt(1 + n_similar)
        return estimate + exploration_bonus

    def _similarity(self, a: tuple[int, int], b: tuple[int, int]) -> float:
        """Simple similarity metric.

        1.0 if exact match, 0.5 if one index matches, 0.0 if neither matches.
        """
        if a[0] == b[0] and a[1] == b[1]:
            return 1.0
        if a[0] == b[0] or a[1] == b[1]:
            return 0.5
        return 0.0

    def best_observed(self) -> tuple[tuple[int, int], float] | None:
        """Return the best observation so far, or None if no observations."""
        if not self.observations:
            return None
        return max(self.observations, key=lambda x: x[1])
