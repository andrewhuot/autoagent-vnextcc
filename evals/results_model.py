"""Structured eval results model for storage, querying, and exploration."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from evals.runner import TestCase
from evals.scorer import CompositeScore, CompositeScorer, EvalResult


@dataclass
class Annotation:
    """Human annotation on a result example."""

    author: str
    timestamp: str
    type: str
    content: str
    score_override: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize one annotation."""
        return {
            "author": self.author,
            "timestamp": self.timestamp,
            "type": self.type,
            "content": self.content,
            "score_override": self.score_override,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Annotation:
        """Rehydrate one annotation from storage."""
        score_override = payload.get("score_override")
        return cls(
            author=str(payload.get("author", "")),
            timestamp=str(payload.get("timestamp", "")),
            type=str(payload.get("type", "comment")),
            content=str(payload.get("content", "")),
            score_override=float(score_override) if score_override is not None else None,
        )


@dataclass
class GraderScore:
    """Structured score plus lightweight reasoning for one metric."""

    value: float
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize one grader score."""
        return {"value": self.value, "reasoning": self.reasoning}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> GraderScore:
        """Rehydrate one grader score."""
        return cls(
            value=float(payload.get("value", 0.0)),
            reasoning=str(payload.get("reasoning", "")),
        )


@dataclass
class MetricSummary:
    """Aggregate statistics for one metric across the run."""

    mean: float
    median: float
    std: float
    min: float
    max: float
    histogram: list[int]

    def to_dict(self) -> dict[str, Any]:
        """Serialize one metric summary."""
        return {
            "mean": self.mean,
            "median": self.median,
            "std": self.std,
            "min": self.min,
            "max": self.max,
            "histogram": self.histogram,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> MetricSummary:
        """Rehydrate one metric summary."""
        return cls(
            mean=float(payload.get("mean", 0.0)),
            median=float(payload.get("median", 0.0)),
            std=float(payload.get("std", 0.0)),
            min=float(payload.get("min", 0.0)),
            max=float(payload.get("max", 0.0)),
            histogram=[int(item) for item in list(payload.get("histogram", []) or [])],
        )


@dataclass
class ResultSummary:
    """Aggregate run-level summary."""

    total: int
    passed: int
    failed: int
    metrics: dict[str, MetricSummary] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the summary block."""
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "metrics": {key: value.to_dict() for key, value in self.metrics.items()},
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ResultSummary:
        """Rehydrate a summary block."""
        return cls(
            total=int(payload.get("total", 0)),
            passed=int(payload.get("passed", 0)),
            failed=int(payload.get("failed", 0)),
            metrics={
                str(key): MetricSummary.from_dict(dict(value))
                for key, value in (payload.get("metrics", {}) or {}).items()
                if isinstance(value, dict)
            },
        )


@dataclass
class ExampleResult:
    """One structured example result ready for exploration and annotation."""

    example_id: str
    input: dict[str, Any]
    expected: dict[str, Any] | None
    actual: dict[str, Any]
    scores: dict[str, GraderScore]
    passed: bool
    failure_reasons: list[str]
    component_attributions: list[dict[str, Any]] = field(default_factory=list)
    annotations: list[Annotation] = field(default_factory=list)
    category: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        """Serialize one example result."""
        return {
            "example_id": self.example_id,
            "input": self.input,
            "expected": self.expected,
            "actual": self.actual,
            "scores": {key: value.to_dict() for key, value in self.scores.items()},
            "passed": self.passed,
            "failure_reasons": self.failure_reasons,
            "component_attributions": self.component_attributions,
            "annotations": [annotation.to_dict() for annotation in self.annotations],
            "category": self.category,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ExampleResult:
        """Rehydrate one example result."""
        return cls(
            example_id=str(payload.get("example_id", "")),
            input=dict(payload.get("input", {}) or {}),
            expected=dict(payload.get("expected", {}) or {}) if payload.get("expected") is not None else None,
            actual=dict(payload.get("actual", {}) or {}),
            scores={
                str(key): GraderScore.from_dict(dict(value))
                for key, value in (payload.get("scores", {}) or {}).items()
                if isinstance(value, dict)
            },
            passed=bool(payload.get("passed", False)),
            failure_reasons=[str(item) for item in list(payload.get("failure_reasons", []) or [])],
            component_attributions=[
                dict(item)
                for item in list(payload.get("component_attributions", []) or [])
                if isinstance(item, dict)
            ],
            annotations=[
                Annotation.from_dict(dict(item))
                for item in list(payload.get("annotations", []) or [])
                if isinstance(item, dict)
            ],
            category=str(payload.get("category", "unknown")),
        )


@dataclass
class EvalResultSet:
    """Complete structured results from one eval run."""

    run_id: str
    timestamp: str
    mode: str
    config_snapshot: dict[str, Any]
    summary: ResultSummary
    examples: list[ExampleResult]

    def to_dict(self) -> dict[str, Any]:
        """Serialize the full result set."""
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "mode": self.mode,
            "config_snapshot": self.config_snapshot,
            "summary": self.summary.to_dict(),
            "examples": [example.to_dict() for example in self.examples],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> EvalResultSet:
        """Rehydrate a stored result set."""
        return cls(
            run_id=str(payload.get("run_id", "")),
            timestamp=str(payload.get("timestamp", "")),
            mode=str(payload.get("mode", "unknown")),
            config_snapshot=dict(payload.get("config_snapshot", {}) or {}),
            summary=ResultSummary.from_dict(dict(payload.get("summary", {}) or {})),
            examples=[
                ExampleResult.from_dict(dict(item))
                for item in list(payload.get("examples", []) or [])
                if isinstance(item, dict)
            ],
        )

    @classmethod
    def from_score(
        cls,
        *,
        run_id: str,
        score: CompositeScore,
        cases: list[TestCase],
        mode: str,
        config_snapshot: dict[str, Any],
        timestamp: str | None = None,
    ) -> EvalResultSet:
        """Build a full structured result set from a composite score and source cases."""
        case_lookup = {case.id: case for case in cases}
        examples = [
            _example_result_from_eval(result, case_lookup.get(result.case_id))
            for result in score.results
        ]
        summary = _summary_from_examples(examples)
        return cls(
            run_id=run_id,
            timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
            mode=mode,
            config_snapshot=config_snapshot,
            summary=summary,
            examples=examples,
        )


def _example_result_from_eval(result: EvalResult, case: TestCase | None) -> ExampleResult:
    """Convert one EvalResult into the structured explorer model."""
    actual = dict(result.actual_output or {})
    if "response" not in actual and result.details:
        actual["details"] = result.details

    expected = dict(result.expected_payload or {})
    if case is not None:
      if not expected:
        expected = {
            "expected_specialist": case.expected_specialist,
            "expected_behavior": case.expected_behavior,
            "expected_keywords": list(case.expected_keywords),
            "expected_tool": case.expected_tool,
            "reference_answer": case.reference_answer,
        }
    elif not expected:
        expected = None

    input_payload = dict(result.input_payload or {})
    if case is not None and not input_payload:
        input_payload = {"user_message": case.user_message}

    scores = {
        "quality": GraderScore(value=result.quality_score, reasoning=result.details),
        "safety": GraderScore(value=1.0 if result.safety_passed else 0.0, reasoning="Safety pass/fail"),
        "latency": GraderScore(value=result.latency_ms, reasoning="Lower is better"),
        "token_count": GraderScore(value=float(result.token_count), reasoning="Lower is cheaper"),
        "tool_use_accuracy": GraderScore(value=result.tool_use_accuracy, reasoning="Expected tool alignment"),
        "composite": GraderScore(value=_per_case_composite(result), reasoning="Weighted per-case composite"),
    }
    for metric_name, metric_value in result.custom_scores.items():
        scores[metric_name] = GraderScore(value=metric_value, reasoning="Custom eval metric")

    return ExampleResult(
        example_id=result.case_id,
        input=input_payload,
        expected=expected,
        actual=actual,
        scores=scores,
        passed=result.passed,
        failure_reasons=list(result.failure_reasons or []),
        component_attributions=list(result.component_attributions or []),
        annotations=[],
        category=result.category,
    )


def _summary_from_examples(examples: list[ExampleResult]) -> ResultSummary:
    """Aggregate metric summaries from all example results."""
    metrics: dict[str, list[float]] = {}
    passed = 0
    for example in examples:
        if example.passed:
            passed += 1
        for metric_name, metric_value in example.scores.items():
            metrics.setdefault(metric_name, []).append(metric_value.value)

    return ResultSummary(
        total=len(examples),
        passed=passed,
        failed=max(0, len(examples) - passed),
        metrics={name: _metric_summary(values) for name, values in metrics.items()},
    )


def _metric_summary(values: list[float]) -> MetricSummary:
    """Compute summary statistics and a compact histogram for one metric."""
    if not values:
        return MetricSummary(mean=0.0, median=0.0, std=0.0, min=0.0, max=0.0, histogram=[0] * 10)
    if len(values) == 1:
        value = float(values[0])
        histogram = [0] * 10
        histogram[min(9, max(0, int(value * 10)))] = 1
        return MetricSummary(
            mean=round(value, 4),
            median=round(value, 4),
            std=0.0,
            min=round(value, 4),
            max=round(value, 4),
            histogram=histogram,
        )

    min_value = min(values)
    max_value = max(values)
    histogram = _histogram(values, buckets=10, min_value=min_value, max_value=max_value)
    return MetricSummary(
        mean=round(statistics.fmean(values), 4),
        median=round(statistics.median(values), 4),
        std=round(statistics.pstdev(values), 4),
        min=round(min_value, 4),
        max=round(max_value, 4),
        histogram=histogram,
    )


def _histogram(values: list[float], *, buckets: int, min_value: float, max_value: float) -> list[int]:
    """Build a fixed-width histogram over the observed value range."""
    histogram = [0] * buckets
    if max_value == min_value:
        histogram[0] = len(values)
        return histogram
    width = (max_value - min_value) / buckets
    for value in values:
        bucket = int((value - min_value) / width)
        if bucket >= buckets:
            bucket = buckets - 1
        histogram[bucket] += 1
    return histogram


def _per_case_composite(result: EvalResult) -> float:
    """Recompute the scorer's weighted composite for a single case."""
    latency_score = max(
        0.0,
        min(1.0, 1.0 - (result.latency_ms / CompositeScorer.MAX_LATENCY_MS)),
    )
    cost_score = max(
        0.0,
        min(1.0, 1.0 - (result.token_count / CompositeScorer.MAX_TOKENS)),
    )
    composite = (
        CompositeScorer.QUALITY_WEIGHT * result.quality_score
        + CompositeScorer.SAFETY_WEIGHT * (1.0 if result.safety_passed else 0.0)
        + CompositeScorer.LATENCY_WEIGHT * latency_score
        + CompositeScorer.COST_WEIGHT * cost_score
    )
    return round(composite, 4)
