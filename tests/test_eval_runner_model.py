"""Tests that the legacy eval runner now emits canonical eval model objects."""

from __future__ import annotations

from evals.runner import EvalRunner, TestCase as LegacyTestCase


def test_eval_runner_attaches_canonical_eval_model_to_scores() -> None:
    """Explicit runner executions should project into the canonical eval model."""

    def agent(message: str, config: dict | None = None) -> dict:
        del config
        return {
            "response": f"Order update: {message} is currently in transit.",
            "specialist_used": "orders",
            "safety_violation": False,
            "latency_ms": 42.0,
            "token_count": 128,
            "tool_calls": [{"tool": "orders_db"}],
        }

    runner = EvalRunner(agent_fn=agent, cache_enabled=False)
    cases = [
        LegacyTestCase(
            id="case-1",
            category="happy_path",
            user_message="Where is order ORD-42?",
            expected_specialist="orders",
            expected_behavior="answer",
            expected_keywords=["order", "transit"],
            expected_tool="orders_db",
            split="test",
            reference_answer="The order is in transit.",
        )
    ]

    score = runner.run_cases(cases, config={"candidate": "v2"})

    assert score.evaluation is not None
    assert score.evaluation_run is not None
    assert score.run_result is not None
    assert runner.last_dataset is not None
    assert runner.last_evaluation is score.evaluation
    assert runner.last_evaluation_run is score.evaluation_run
    assert score.evaluation.dataset_ref == runner.last_dataset.dataset_id
    assert score.evaluation.dataset_version.startswith("sha256:")
    assert score.run_result.summary_stats["total_examples"] == 1
    assert score.run_result.per_example_results[0]["example_id"] == "case-1"
    grader_ids = {
        result.grader_id
        for result in score.run_result.per_example_results[0]["grader_results"]
    }
    assert {"quality", "safety", "tool_use_accuracy"} <= grader_ids


def test_eval_runner_reports_progress_after_each_case() -> None:
    """Live API tasks should be able to show case-level eval progress."""

    def agent(message: str, config: dict | None = None) -> dict:
        del config
        return {
            "response": f"Handled {message}",
            "specialist_used": "support",
            "safety_violation": False,
            "latency_ms": 10.0,
            "token_count": 32,
            "tool_calls": [],
        }

    runner = EvalRunner(agent_fn=agent, cache_enabled=False)
    cases = [
        LegacyTestCase(
            id=f"case-{index}",
            category="progress",
            user_message=f"Question {index}",
            expected_specialist="support",
            expected_behavior="answer",
            expected_keywords=["Handled"],
        )
        for index in range(1, 4)
    ]
    updates: list[tuple[int, int]] = []

    runner.run_cases(cases, progress_callback=lambda completed, total: updates.append((completed, total)))

    assert updates == [(1, 3), (2, 3), (3, 3)]
