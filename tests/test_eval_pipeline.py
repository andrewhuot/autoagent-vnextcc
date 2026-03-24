"""Tests for dataset-based eval pipeline, custom evaluators, and significance checks."""

from __future__ import annotations

import csv
import json

from evals.runner import EvalRunner
from evals.statistics import paired_significance


def test_eval_runner_loads_jsonl_dataset_with_split(tmp_path) -> None:
    """JSONL datasets should support explicit train/test split selection."""
    dataset = tmp_path / "dataset.jsonl"
    rows = [
        {
            "id": "a",
            "split": "train",
            "user_message": "Where is my order?",
            "expected_specialist": "orders",
            "expected_behavior": "answer",
            "expected_keywords": ["order"],
        },
        {
            "id": "b",
            "split": "test",
            "user_message": "Recommend a keyboard",
            "expected_specialist": "recommendations",
            "expected_behavior": "answer",
            "expected_keywords": ["recommend"],
        },
    ]
    dataset.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    runner = EvalRunner()
    cases = runner.load_dataset_cases(str(dataset), split="test")

    assert len(cases) == 1
    assert cases[0].id == "b"


def test_eval_runner_loads_csv_dataset(tmp_path) -> None:
    """CSV datasets should be supported with expected schema fields."""
    dataset = tmp_path / "dataset.csv"
    with dataset.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "id",
                "split",
                "user_message",
                "expected_specialist",
                "expected_behavior",
                "expected_keywords",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "id": "row-1",
                "split": "test",
                "user_message": "How do I track shipping?",
                "expected_specialist": "orders",
                "expected_behavior": "answer",
                "expected_keywords": "order,shipping",
            }
        )

    runner = EvalRunner()
    cases = runner.load_dataset_cases(str(dataset), split="test")

    assert len(cases) == 1
    assert cases[0].expected_keywords == ["order", "shipping"]


def test_custom_eval_function_is_aggregated(tmp_path) -> None:
    """Custom evaluators should be executed and included in composite output."""
    runner = EvalRunner()

    def response_length_metric(case, agent_result, eval_result):
        return min(1.0, len(agent_result.get("response", "")) / 100.0)

    runner.register_evaluator("response_length", response_length_metric)
    score = runner.run()

    assert "response_length" in score.custom_metrics


def test_paired_significance_requires_real_delta() -> None:
    """Tiny random differences should fail significance while strong lift should pass."""
    baseline = [0.60, 0.61, 0.59, 0.60, 0.61, 0.60, 0.59, 0.60]
    weak_candidate = [0.61, 0.60, 0.60, 0.60, 0.61, 0.60, 0.60, 0.60]
    strong_candidate = [0.74, 0.75, 0.73, 0.74, 0.76, 0.75, 0.73, 0.74]

    weak = paired_significance(baseline, weak_candidate, alpha=0.05, min_effect_size=0.01, iterations=1000)
    strong = paired_significance(baseline, strong_candidate, alpha=0.05, min_effect_size=0.01, iterations=1000)

    assert weak.is_significant is False
    assert strong.is_significant is True
