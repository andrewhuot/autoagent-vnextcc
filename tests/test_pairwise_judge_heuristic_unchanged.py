"""Regression lock for the heuristic pairwise judge (R3.8).

Pins the pre-R3 heuristic behavior so future edits can't drift it silently.
Every branch of PairwiseLLMJudge._heuristic is exercised by one case here.

R3.7 landed the `_heuristic` refactor (extracting the pre-R3 `judge_case`
body into a private method). R3.8 (this file) is the regression pin: each
test targets exactly one decision branch (safety mismatch, reference
overlap, quality tie, quality delta). The confidence constants
(0.98 / 0.9 / 0.6 / 0.82) are load-bearing for downstream consumers and
are asserted exactly, not fuzzily.
"""

from __future__ import annotations

from evals.judges.pairwise_judge import PairwiseJudgeVerdict, PairwiseLLMJudge
from evals.runner import TestCase
from evals.scorer import EvalResult


def _case(
    case_id: str = "c1",
    user_message: str = "hello",
    reference_answer: str = "",
    category: str = "happy_path",
) -> TestCase:
    return TestCase(
        id=case_id,
        category=category,
        user_message=user_message,
        expected_specialist="support",
        expected_behavior="answer",
        reference_answer=reference_answer,
    )


def _eval(
    *,
    safety_passed: bool = True,
    quality_score: float = 0.5,
    case_id: str = "c1",
) -> EvalResult:
    return EvalResult(
        case_id=case_id,
        category="happy_path",
        passed=True,
        quality_score=quality_score,
        safety_passed=safety_passed,
        latency_ms=100.0,
        token_count=50,
    )


def test_heuristic_safety_branch_prefers_safe() -> None:
    """Safety mismatch wins immediately with confidence 0.98."""
    judge = PairwiseLLMJudge()  # no router -> always heuristic
    v = judge.judge_case(
        case=_case(),
        label_a="variant_a",
        label_b="variant_b",
        output_a={"response": "ok"},
        output_b={"response": "ok"},
        eval_a=_eval(safety_passed=True),
        eval_b=_eval(safety_passed=False),
    )
    assert isinstance(v, PairwiseJudgeVerdict)
    assert v.winner == "variant_a"
    assert v.confidence == 0.98


def test_heuristic_safety_branch_prefers_safe_other_side() -> None:
    """Safety mismatch is symmetric: the safe side wins regardless of label."""
    judge = PairwiseLLMJudge()
    v = judge.judge_case(
        case=_case(),
        label_a="variant_a",
        label_b="variant_b",
        output_a={"response": "unsafe"},
        output_b={"response": "ok"},
        eval_a=_eval(safety_passed=False),
        eval_b=_eval(safety_passed=True),
    )
    assert isinstance(v, PairwiseJudgeVerdict)
    assert v.winner == "variant_b"
    assert v.confidence == 0.98


def test_heuristic_reference_overlap_branch() -> None:
    """With a reference answer and divergent overlap (>0.05), overlap wins at 0.9."""
    judge = PairwiseLLMJudge()
    v = judge.judge_case(
        case=_case(reference_answer="the cat sat on the mat"),
        label_a="variant_a",
        label_b="variant_b",
        output_a={"response": "the cat sat on the mat indeed"},
        output_b={"response": "something entirely different"},
        eval_a=_eval(quality_score=0.5),
        eval_b=_eval(quality_score=0.5),
    )
    assert isinstance(v, PairwiseJudgeVerdict)
    assert v.winner == "variant_a"
    assert v.confidence == 0.9


def test_heuristic_quality_tie_branch() -> None:
    """Near-equal quality (within 0.02) w/o safety or reference signal -> tie at 0.6."""
    judge = PairwiseLLMJudge()
    v = judge.judge_case(
        case=_case(reference_answer=""),  # no reference -> skips overlap branch
        label_a="variant_a",
        label_b="variant_b",
        output_a={"response": "x"},
        output_b={"response": "y"},
        eval_a=_eval(quality_score=0.50),
        eval_b=_eval(quality_score=0.51),
    )
    assert isinstance(v, PairwiseJudgeVerdict)
    assert v.winner == "tie"
    assert v.confidence == 0.6


def test_heuristic_quality_dominant_branch() -> None:
    """Clear quality delta (no safety/ref signal) -> higher-quality side wins at 0.82."""
    judge = PairwiseLLMJudge()
    v = judge.judge_case(
        case=_case(reference_answer=""),
        label_a="variant_a",
        label_b="variant_b",
        output_a={"response": "x"},
        output_b={"response": "y"},
        eval_a=_eval(quality_score=0.80),
        eval_b=_eval(quality_score=0.40),
    )
    assert isinstance(v, PairwiseJudgeVerdict)
    assert v.winner == "variant_a"
    assert v.confidence == 0.82


def test_heuristic_zero_arg_constructor_produces_verdict() -> None:
    """Backwards-compat smoke: PairwiseLLMJudge() (no args) still works and
    delegates to heuristic."""
    judge = PairwiseLLMJudge()
    v = judge.judge_case(
        case=_case(),
        label_a="variant_a",
        label_b="variant_b",
        output_a={"response": "a"},
        output_b={"response": "b"},
        eval_a=_eval(),
        eval_b=_eval(),
    )
    assert isinstance(v, PairwiseJudgeVerdict)
    assert v.winner in ("variant_a", "variant_b", "tie")
