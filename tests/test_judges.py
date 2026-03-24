"""Tests for judge implementations (deterministic, rule-based, LLM, audit, calibration, grader stack)."""

from __future__ import annotations

import pytest

from core.types import GraderBundle, GraderSpec, GraderType, JudgeVerdict
from judges.audit_judge import AuditJudge
from judges.calibration import JudgeCalibrationSuite
from judges.deterministic import DeterministicJudge
from judges.grader_stack import GraderStack
from judges.llm_judge import LLMJudge
from judges.rule_based import RuleBasedJudge


# ---------------------------------------------------------------------------
# DeterministicJudge tests
# ---------------------------------------------------------------------------


def test_deterministic_check_regex_match():
    judge = DeterministicJudge()
    verdict = judge.check_regex(r"\bsuccess\b", "The operation was a success")

    assert verdict.passed is True
    assert verdict.score == 1.0
    assert verdict.confidence == 1.0
    assert len(verdict.evidence_spans) > 0
    assert "success" in verdict.evidence_spans


def test_deterministic_check_regex_no_match():
    judge = DeterministicJudge()
    verdict = judge.check_regex(r"\bfailed\b", "The operation completed")

    assert verdict.passed is False
    assert verdict.score == 0.0
    assert len(verdict.failure_reasons) > 0
    assert "Pattern not found" in verdict.failure_reasons[0]


def test_deterministic_check_regex_invalid_pattern():
    judge = DeterministicJudge()
    verdict = judge.check_regex(r"[unclosed", "test text")

    assert verdict.passed is False
    assert verdict.score == 0.0
    assert "Invalid regex pattern" in verdict.failure_reasons[0]


def test_deterministic_check_state_full_match():
    judge = DeterministicJudge()
    expected = {"status": "active", "count": 5}
    actual = {"status": "active", "count": 5, "extra": "ignored"}

    verdict = judge.check_state(expected, actual)

    assert verdict.passed is True
    assert verdict.score == 1.0
    assert len(verdict.evidence_spans) == 2


def test_deterministic_check_state_partial_match():
    judge = DeterministicJudge()
    expected = {"status": "active", "count": 5}
    actual = {"status": "active", "count": 10}

    verdict = judge.check_state(expected, actual)

    assert verdict.passed is False
    assert verdict.score == 0.5  # 1 of 2 matched
    assert len(verdict.failure_reasons) > 0
    assert "count" in verdict.failure_reasons[0]


def test_deterministic_check_state_missing_keys():
    judge = DeterministicJudge()
    expected = {"status": "active", "count": 5}
    actual = {"status": "active"}

    verdict = judge.check_state(expected, actual)

    assert verdict.passed is False
    assert verdict.score == 0.5
    assert "Missing key: count" in verdict.failure_reasons


def test_deterministic_check_invariant_passing():
    judge = DeterministicJudge()

    def always_true(ctx: dict) -> bool:
        return len(ctx) > 0

    verdict = judge.check_invariant(always_true, {"key": "value"})

    assert verdict.passed is True
    assert verdict.score == 1.0
    assert "invariant_passed" in verdict.evidence_spans


def test_deterministic_check_invariant_failing():
    judge = DeterministicJudge()

    def always_false(ctx: dict) -> bool:
        return False

    verdict = judge.check_invariant(always_false, {"key": "value"})

    assert verdict.passed is False
    assert verdict.score == 0.0
    assert "Invariant check returned False" in verdict.failure_reasons


def test_deterministic_check_invariant_exception():
    judge = DeterministicJudge()

    def raises_error(ctx: dict) -> bool:
        raise ValueError("intentional error")

    verdict = judge.check_invariant(raises_error, {})

    assert verdict.passed is False
    assert verdict.score == 0.0
    assert "Invariant raised exception" in verdict.failure_reasons[0]


# ---------------------------------------------------------------------------
# RuleBasedJudge tests
# ---------------------------------------------------------------------------


def test_rule_based_check_format_required_fields_present():
    judge = RuleBasedJudge()
    rules = {"required_fields": ["hello", "world"]}

    verdict = judge.check_format("hello world", rules)

    assert verdict.passed is True
    assert verdict.score == 1.0


def test_rule_based_check_format_required_fields_missing():
    judge = RuleBasedJudge()
    rules = {"required_fields": ["hello", "missing"]}

    verdict = judge.check_format("hello world", rules)

    assert verdict.passed is False
    assert verdict.score == 0.5
    assert "Missing required field: 'missing'" in verdict.failure_reasons


def test_rule_based_check_format_max_length_pass():
    judge = RuleBasedJudge()
    rules = {"max_length": 20}

    verdict = judge.check_format("short text", rules)

    assert verdict.passed is True
    assert verdict.score == 1.0


def test_rule_based_check_format_max_length_fail():
    judge = RuleBasedJudge()
    rules = {"max_length": 5}

    verdict = judge.check_format("this is too long", rules)

    assert verdict.passed is False
    assert "exceeds max_length" in verdict.failure_reasons[0]


def test_rule_based_check_format_min_length_pass():
    judge = RuleBasedJudge()
    rules = {"min_length": 5}

    verdict = judge.check_format("long enough text", rules)

    assert verdict.passed is True
    assert verdict.score == 1.0


def test_rule_based_check_format_min_length_fail():
    judge = RuleBasedJudge()
    rules = {"min_length": 100}

    verdict = judge.check_format("short", rules)

    assert verdict.passed is False
    assert "below min_length" in verdict.failure_reasons[0]


def test_rule_based_check_format_banned_words_pass():
    judge = RuleBasedJudge()
    rules = {"banned_words": ["forbidden", "illegal"]}

    verdict = judge.check_format("this is clean text", rules)

    assert verdict.passed is True
    assert verdict.score == 1.0


def test_rule_based_check_format_banned_words_fail():
    judge = RuleBasedJudge()
    rules = {"banned_words": ["forbidden", "illegal"]}

    verdict = judge.check_format("this contains forbidden word", rules)

    assert verdict.passed is False
    assert "Banned word found: 'forbidden'" in verdict.failure_reasons


def test_rule_based_check_required_fields_all_present():
    judge = RuleBasedJudge()
    data = {"name": "Alice", "age": 30, "city": "NYC"}
    required = ["name", "age"]

    verdict = judge.check_required_fields(data, required)

    assert verdict.passed is True
    assert verdict.score == 1.0
    assert len(verdict.evidence_spans) == 2


def test_rule_based_check_required_fields_some_missing():
    judge = RuleBasedJudge()
    data = {"name": "Alice"}
    required = ["name", "age", "city"]

    verdict = judge.check_required_fields(data, required)

    assert verdict.passed is False
    assert verdict.score == 1.0 / 3.0
    assert len(verdict.failure_reasons) == 2


# ---------------------------------------------------------------------------
# LLMJudge tests
# ---------------------------------------------------------------------------


def test_llm_judge_evaluate_with_reference_high_overlap():
    judge = LLMJudge(judge_id="llm_test")
    task = "What is the capital of France?"
    response = "Paris is the capital of France and its largest city"
    reference = "Paris is the capital of France"

    verdict = judge.evaluate(task, response, reference)

    assert verdict.passed is True
    assert verdict.score >= 0.5
    assert len(verdict.evidence_spans) > 0


def test_llm_judge_evaluate_with_reference_low_overlap():
    judge = LLMJudge(judge_id="llm_test")
    task = "What is the capital of France?"
    response = "I don't know the answer"
    reference = "Paris is the capital of France"

    verdict = judge.evaluate(task, response, reference)

    assert verdict.passed is False
    assert verdict.score < 0.5
    assert len(verdict.failure_reasons) > 0


def test_llm_judge_evaluate_no_reference_long_response():
    judge = LLMJudge(judge_id="llm_test")
    task = "Explain photosynthesis"
    response = "Photosynthesis is the process by which plants convert light energy into chemical energy"

    verdict = judge.evaluate(task, response, reference=None)

    assert verdict.score > 0.0  # heuristic gives some score
    assert verdict.confidence < 1.0  # lower confidence without reference


def test_llm_judge_evaluate_no_reference_short_response():
    judge = LLMJudge(judge_id="llm_test")
    task = "Explain photosynthesis"
    response = "Yes"

    verdict = judge.evaluate(task, response, reference=None)

    assert verdict.score < 0.5
    assert any("Response too short" in reason for reason in verdict.failure_reasons)


def test_llm_judge_evidence_spans_populated():
    judge = LLMJudge(judge_id="llm_test")
    task = "What is the capital?"
    response = "Paris is the capital. It's a beautiful city."
    reference = "Paris is the capital"

    verdict = judge.evaluate(task, response, reference)

    assert len(verdict.evidence_spans) > 0
    # Evidence should contain overlapping sentences
    assert any("Paris" in span for span in verdict.evidence_spans)


# ---------------------------------------------------------------------------
# AuditJudge tests
# ---------------------------------------------------------------------------


def test_audit_judge_agrees_with_high_confidence_primary():
    audit = AuditJudge(judge_id="audit_test")
    primary = JudgeVerdict(
        score=0.9,
        passed=True,
        judge_id="llm_primary",
        confidence=0.85,
    )

    verdict = audit.audit("task", "response", primary)

    assert verdict.passed is True
    assert verdict.score == 0.9
    assert "Audit agrees" in verdict.evidence_spans[0]
    assert verdict.metadata["agreement"] is True


def test_audit_judge_disagrees_with_low_confidence_primary():
    audit = AuditJudge(judge_id="audit_test")
    primary = JudgeVerdict(
        score=0.8,
        passed=True,
        judge_id="llm_primary",
        confidence=0.6,  # below 0.7 threshold
    )

    verdict = audit.audit("task", "response", primary)

    assert verdict.passed is False
    assert verdict.score < primary.score
    assert len(verdict.failure_reasons) > 0
    assert "Audit disagrees" in verdict.failure_reasons[0]
    assert verdict.metadata["agreement"] is False


def test_audit_judge_metadata_shows_different_model_family():
    audit = AuditJudge(model_config={"model": "claude-sonnet", "family": "anthropic"})
    primary = JudgeVerdict(
        score=0.9,
        passed=True,
        judge_id="llm_primary",
        confidence=0.8,
    )

    verdict = audit.audit("task", "response", primary)

    assert verdict.metadata["audit_model_family"] == "anthropic"
    assert verdict.metadata["primary_judge_id"] == "llm_primary"
    assert verdict.metadata["primary_score"] == 0.9


# ---------------------------------------------------------------------------
# JudgeCalibrationSuite tests
# ---------------------------------------------------------------------------


def test_calibration_suite_record_human_judgment():
    suite = JudgeCalibrationSuite()
    verdict = JudgeVerdict(score=0.8, passed=True, judge_id="test")

    suite.record_human_judgment("case-1", verdict, human_score=0.75)

    assert len(suite._records) == 1
    assert suite._records[0].case_id == "case-1"


def test_calibration_suite_agreement_rate_high():
    suite = JudgeCalibrationSuite()
    for i in range(10):
        verdict = JudgeVerdict(score=0.8, passed=True, judge_id="test")
        suite.record_human_judgment(f"case-{i}", verdict, human_score=0.8)

    rate = suite.agreement_rate()

    assert rate == 1.0  # perfect agreement


def test_calibration_suite_agreement_rate_low():
    suite = JudgeCalibrationSuite()
    for i in range(10):
        verdict = JudgeVerdict(score=0.9, passed=True, judge_id="test")
        suite.record_human_judgment(f"case-{i}", verdict, human_score=0.5)

    rate = suite.agreement_rate()

    assert rate == 0.0  # no agreement (delta > 0.1)


def test_calibration_suite_compute_drift_stable():
    suite = JudgeCalibrationSuite()
    # First 50 records: consistent
    for i in range(100):
        verdict = JudgeVerdict(score=0.8, passed=True, judge_id="test")
        suite.record_human_judgment(f"case-{i}", verdict, human_score=0.8)

    drift = suite.compute_drift(window=50)

    assert drift == 0.0  # no drift


def test_calibration_suite_compute_drift_drifting():
    suite = JudgeCalibrationSuite()
    # First 50: agree
    for i in range(50):
        verdict = JudgeVerdict(score=0.8, passed=True, judge_id="test")
        suite.record_human_judgment(f"case-{i}", verdict, human_score=0.8)
    # Last 50: disagree
    for i in range(50, 100):
        verdict = JudgeVerdict(score=0.9, passed=True, judge_id="test")
        suite.record_human_judgment(f"case-{i}", verdict, human_score=0.5)

    drift = suite.compute_drift(window=50)

    assert drift > 0.5  # significant drift


def test_calibration_suite_disagreement_rate():
    suite = JudgeCalibrationSuite()
    verdicts_a = [
        JudgeVerdict(score=0.8, passed=True, judge_id="a"),
        JudgeVerdict(score=0.3, passed=False, judge_id="a"),
    ]
    verdicts_b = [
        JudgeVerdict(score=0.8, passed=True, judge_id="b"),
        JudgeVerdict(score=0.8, passed=True, judge_id="b"),
    ]

    rate = suite.disagreement_rate(verdicts_a, verdicts_b)

    assert rate == 0.5  # 1 of 2 disagree on pass/fail


# ---------------------------------------------------------------------------
# GraderStack tests
# ---------------------------------------------------------------------------


def test_grader_stack_execute_runs_all_graders():
    bundle = GraderBundle(
        bundle_id="test",
        graders=[
            GraderSpec(grader_id="det", grader_type=GraderType.deterministic, weight=1.0),
            GraderSpec(grader_id="rule", grader_type=GraderType.rule_based, weight=1.0),
        ],
    )
    stack = GraderStack(
        bundle=bundle,
        deterministic=DeterministicJudge(),
        rule_based=RuleBasedJudge(),
    )

    verdicts = stack.execute(
        task="test",
        response="This is a valid response",
        context={},
    )

    assert len(verdicts) == 2
    assert verdicts[0].judge_id == "deterministic"
    assert verdicts[1].judge_id == "rule_based"


def test_grader_stack_early_exit_on_required_grader_failure():
    bundle = GraderBundle(
        bundle_id="test",
        graders=[
            GraderSpec(
                grader_id="det",
                grader_type=GraderType.deterministic,
                weight=1.0,
                required=True,
            ),
            GraderSpec(grader_id="rule", grader_type=GraderType.rule_based, weight=1.0),
        ],
    )
    stack = GraderStack(
        bundle=bundle,
        deterministic=DeterministicJudge(),
        rule_based=RuleBasedJudge(),
    )

    # Force deterministic to fail
    verdicts = stack.execute(
        task="test",
        response="response",
        context={"pattern": r"MISSING"},
    )

    assert len(verdicts) == 1  # only deterministic ran
    assert verdicts[0].passed is False


def test_grader_stack_aggregate_computes_weighted_score():
    bundle = GraderBundle(
        bundle_id="test",
        graders=[
            GraderSpec(grader_id="g1", grader_type=GraderType.deterministic, weight=0.3),
            GraderSpec(grader_id="g2", grader_type=GraderType.rule_based, weight=0.7),
        ],
    )
    stack = GraderStack(
        bundle=bundle,
        deterministic=DeterministicJudge(),
        rule_based=RuleBasedJudge(),
    )

    verdicts = [
        JudgeVerdict(score=1.0, passed=True, judge_id="deterministic", confidence=1.0),
        JudgeVerdict(score=0.5, passed=True, judge_id="rule_based", confidence=1.0),
    ]

    aggregate = stack.aggregate(verdicts)

    # 0.3 * 1.0 + 0.7 * 0.5 = 0.65
    assert aggregate.score == pytest.approx(0.65, abs=0.01)
    assert aggregate.passed is True


def test_grader_stack_aggregate_required_failure_overrides():
    bundle = GraderBundle(
        bundle_id="test",
        graders=[
            GraderSpec(
                grader_id="deterministic",  # must match judge_id
                grader_type=GraderType.deterministic,
                weight=0.3,
                required=True,
            ),
            GraderSpec(grader_id="rule_based", grader_type=GraderType.rule_based, weight=0.7),
        ],
    )
    stack = GraderStack(
        bundle=bundle,
        deterministic=DeterministicJudge(),
        rule_based=RuleBasedJudge(),
    )

    verdicts = [
        JudgeVerdict(score=0.0, passed=False, judge_id="deterministic", confidence=1.0),
        JudgeVerdict(score=1.0, passed=True, judge_id="rule_based", confidence=1.0),
    ]

    aggregate = stack.aggregate(verdicts)

    # Score might be > 0.5, but required grader failed
    assert aggregate.passed is False
