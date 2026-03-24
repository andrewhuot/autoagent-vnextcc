"""Audit judge — cross-family audit for promotion decisions.

The audit judge uses a DIFFERENT model family than the primary LLM judge
to provide an independent second opinion, reducing single-model bias.
"""

from __future__ import annotations

from typing import Any

from core.types import JudgeVerdict


class AuditJudge:
    """Cross-family audit judge for validating primary verdicts.

    Mock implementation: agrees with primary verdict when its confidence
    exceeds 0.7, disagrees otherwise.  In production this would call a
    different LLM family for independent evaluation.
    """

    def __init__(
        self,
        model_config: dict[str, Any] | None = None,
        judge_id: str = "audit_judge",
    ) -> None:
        # Default to a different model family than the typical primary (openai).
        self.model_config = model_config or {"model": "claude-sonnet-4-20250514", "family": "anthropic"}
        self.judge_id = judge_id

    def audit(
        self,
        task: str,
        response: str,
        primary_verdict: JudgeVerdict,
    ) -> JudgeVerdict:
        """Audit a primary verdict and return an independent assessment.

        Mock logic:
        - If primary confidence > 0.7, agree with the primary verdict.
        - Otherwise, disagree (flag for human review).

        The audit verdict always records the primary judge's ID and score
        in metadata so the disagreement can be analysed later.
        """
        agrees = primary_verdict.confidence > 0.7

        if agrees:
            score = primary_verdict.score
            passed = primary_verdict.passed
            evidence = [f"Audit agrees with {primary_verdict.judge_id}"]
            failures: list[str] = []
            confidence = min(1.0, primary_verdict.confidence + 0.1)
        else:
            # Disagree — lower the score and flag
            score = max(0.0, primary_verdict.score - 0.3)
            passed = False
            evidence = []
            failures = [
                f"Audit disagrees with {primary_verdict.judge_id} "
                f"(primary confidence {primary_verdict.confidence:.2f} <= 0.7)"
            ]
            confidence = 0.6

        return JudgeVerdict(
            score=round(score, 4),
            passed=passed,
            judge_id=self.judge_id,
            evidence_spans=evidence,
            failure_reasons=failures,
            confidence=round(confidence, 4),
            metadata={
                "audit_model_family": self.model_config.get("family", "unknown"),
                "primary_judge_id": primary_verdict.judge_id,
                "primary_score": primary_verdict.score,
                "primary_confidence": primary_verdict.confidence,
                "agreement": agrees,
                "model_config": self.model_config,
            },
        )
