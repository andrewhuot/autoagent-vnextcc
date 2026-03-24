"""LLM judge — mock implementation using keyword overlap scoring.

In production this would call an LLM for evaluation.  The mock keeps tests
fast and avoids API dependencies while preserving the full JudgeVerdict
interface.
"""

from __future__ import annotations

import re
from typing import Any

from core.types import JudgeVerdict


class LLMJudge:
    """LLM-based evaluation judge (mock implementation via keyword overlap)."""

    def __init__(
        self,
        model_config: dict[str, Any] | None = None,
        judge_id: str = "llm_judge_primary",
    ) -> None:
        self.model_config = model_config or {"model": "gpt-4o", "family": "openai"}
        self.judge_id = judge_id

    def evaluate(
        self,
        task: str,
        response: str,
        reference: str | None = None,
        criteria: list[str] | None = None,
    ) -> JudgeVerdict:
        """Evaluate *response* against *reference* and optional *criteria*.

        Mock implementation: scores based on word overlap between response
        and reference.  When no reference is provided, falls back to a
        heuristic based on response length and criteria keyword presence.
        """
        if reference:
            return self._score_by_overlap(task, response, reference, criteria)
        return self._score_heuristic(task, response, criteria)

    # ------------------------------------------------------------------
    # Internal scoring strategies
    # ------------------------------------------------------------------

    def _score_by_overlap(
        self,
        task: str,
        response: str,
        reference: str,
        criteria: list[str] | None,
    ) -> JudgeVerdict:
        """Score by word-level overlap between response and reference."""
        ref_words = self._tokenize(reference)
        resp_words = self._tokenize(response)

        if not ref_words:
            return self._make_verdict(0.5, response, criteria, note="empty reference")

        overlap = ref_words & resp_words
        overlap_ratio = len(overlap) / len(ref_words)

        # Criteria bonus: if criteria keywords appear in response, small uplift
        criteria_bonus = 0.0
        if criteria:
            criteria_hits = sum(
                1 for c in criteria if c.lower() in response.lower()
            )
            criteria_bonus = 0.05 * (criteria_hits / len(criteria))

        score = min(1.0, overlap_ratio + criteria_bonus)

        # Extract evidence spans — sentences containing overlapping words
        evidence = self._extract_evidence(response, overlap)

        passed = score >= 0.5
        failures: list[str] = []
        if not passed:
            missing = ref_words - resp_words
            failures.append(
                f"Low overlap ({overlap_ratio:.2f}). Missing key terms: "
                f"{', '.join(sorted(missing)[:10])}"
            )

        return JudgeVerdict(
            score=round(score, 4),
            passed=passed,
            judge_id=self.judge_id,
            evidence_spans=evidence,
            failure_reasons=failures,
            confidence=round(min(1.0, overlap_ratio + 0.1), 4),
            metadata={
                "strategy": "overlap",
                "overlap_ratio": round(overlap_ratio, 4),
                "criteria_bonus": round(criteria_bonus, 4),
                "model_config": self.model_config,
            },
        )

    def _score_heuristic(
        self,
        task: str,
        response: str,
        criteria: list[str] | None,
    ) -> JudgeVerdict:
        """Heuristic fallback when no reference is available."""
        score = 0.0
        evidence: list[str] = []
        failures: list[str] = []

        # Length heuristic: non-trivial responses get base score
        if len(response.strip()) > 20:
            score += 0.4
            evidence.append(f"response length={len(response)}")
        else:
            failures.append(f"Response too short ({len(response)} chars)")

        # Task keyword presence
        task_words = self._tokenize(task)
        resp_words = self._tokenize(response)
        if task_words:
            task_overlap = len(task_words & resp_words) / len(task_words)
            score += 0.3 * task_overlap
            if task_overlap > 0.3:
                evidence.append(f"task_overlap={task_overlap:.2f}")

        # Criteria check
        if criteria:
            criteria_hits = sum(
                1 for c in criteria if c.lower() in response.lower()
            )
            criteria_ratio = criteria_hits / len(criteria)
            score += 0.3 * criteria_ratio
            if criteria_hits > 0:
                evidence.append(f"criteria_hits={criteria_hits}/{len(criteria)}")
        else:
            score += 0.15  # no criteria = neutral

        score = min(1.0, score)
        passed = score >= 0.5

        if not passed:
            failures.append(f"Heuristic score too low: {score:.2f}")

        return JudgeVerdict(
            score=round(score, 4),
            passed=passed,
            judge_id=self.judge_id,
            evidence_spans=evidence,
            failure_reasons=failures,
            confidence=round(score * 0.8, 4),  # lower confidence without reference
            metadata={
                "strategy": "heuristic",
                "model_config": self.model_config,
            },
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        """Split text into lowercase word tokens, filtering short/stop words."""
        words = set(re.findall(r"[a-z0-9]+", text.lower()))
        # Remove very short words that add noise
        return {w for w in words if len(w) > 2}

    @staticmethod
    def _extract_evidence(text: str, overlap_words: set[str]) -> list[str]:
        """Extract sentences from *text* that contain overlapping keywords."""
        if not overlap_words:
            return []
        sentences = re.split(r"[.!?\n]+", text)
        evidence: list[str] = []
        for sentence in sentences:
            stripped = sentence.strip()
            if not stripped:
                continue
            sentence_words = set(re.findall(r"[a-z0-9]+", stripped.lower()))
            if sentence_words & overlap_words:
                evidence.append(stripped[:200])  # cap length
                if len(evidence) >= 5:
                    break
        return evidence

    def _make_verdict(
        self,
        score: float,
        response: str,
        criteria: list[str] | None,
        note: str = "",
    ) -> JudgeVerdict:
        """Build a simple verdict with a note in metadata."""
        return JudgeVerdict(
            score=score,
            passed=score >= 0.5,
            judge_id=self.judge_id,
            evidence_spans=[response[:200]] if response else [],
            confidence=0.5,
            metadata={
                "strategy": "fallback",
                "note": note,
                "model_config": self.model_config,
            },
        )
