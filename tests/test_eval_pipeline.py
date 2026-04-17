"""Tests for dataset-based eval pipeline, custom evaluators, and significance checks."""

from __future__ import annotations

import csv
import json

import yaml

from evals.runner import EvalRunner
from evals.statistics import paired_significance
from evals.scorer import CompositeScorer, EvalResult


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


def test_eval_runner_loads_yaml_dataset_path(tmp_path) -> None:
    """Build-generated YAML eval files should work when passed as an explicit dataset."""
    dataset = tmp_path / "generated_build.yaml"
    dataset.write_text(
        yaml.safe_dump(
            [
                {
                    "id": "setup-sso",
                    "split": "test",
                    "category": "generated_build",
                    "user_message": "How do I enable SSO on the Team plan?",
                    "expected_specialist": "support",
                    "expected_behavior": "answer",
                    "expected_keywords": ["SSO", "Team plan"],
                    "expected_tool": "search_knowledge_base",
                }
            ],
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    runner = EvalRunner()
    cases = runner.load_dataset_cases(str(dataset), split="test")

    assert len(cases) == 1
    assert cases[0].id == "setup-sso"
    assert cases[0].category == "generated_build"
    assert cases[0].expected_tool == "search_knowledge_base"


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


def test_eval_runner_reuses_cached_result_for_identical_inputs(tmp_path) -> None:
    """Identical eval+config pairs should be served from cache on second run."""
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "case-1",
                        "split": "test",
                        "user_message": "Where is order 123?",
                        "expected_specialist": "orders",
                        "expected_behavior": "answer",
                        "expected_keywords": ["order"],
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    calls = {"count": 0}

    def counting_agent(message: str, config: dict | None = None) -> dict:
        calls["count"] += 1
        return {
            "response": f"Order update for: {message}",
            "specialist_used": "orders",
            "safety_violation": False,
            "latency_ms": 45.0,
            "token_count": 120,
            "tool_calls": [{"tool": "orders_db"}],
        }

    runner = EvalRunner(
        agent_fn=counting_agent,
        cache_db_path=str(tmp_path / "eval_cache.db"),
        cache_enabled=True,
    )

    first = runner.run(config={"policy": "strict"}, dataset_path=str(dataset), split="test")
    assert calls["count"] == 1
    assert first.provenance.get("cache_hit") == "false"

    second = runner.run(config={"policy": "strict"}, dataset_path=str(dataset), split="test")
    assert calls["count"] == 1  # unchanged -> second run reused cache
    assert second.provenance.get("cache_hit") == "true"
    assert second.total_cases == first.total_cases


def test_eval_runner_surfaces_cross_split_contamination(tmp_path) -> None:
    """Cross-split duplicate prompts should be detected and surfaced in warnings."""
    dataset = tmp_path / "dataset.jsonl"
    rows = [
        {
            "id": "train-1",
            "split": "train",
            "user_message": "Reset my password",
            "expected_specialist": "support",
            "expected_behavior": "answer",
        },
        {
            "id": "test-1",
            "split": "test",
            "user_message": "Reset my password",
            "expected_specialist": "support",
            "expected_behavior": "answer",
        },
    ]
    dataset.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    def simple_agent(message: str, config: dict | None = None) -> dict:
        return {
            "response": f"Help for {message}",
            "specialist_used": "support",
            "safety_violation": False,
            "latency_ms": 10.0,
            "token_count": 30,
        }

    runner = EvalRunner(agent_fn=simple_agent, dataset_strict_integrity=False)
    score = runner.run(dataset_path=str(dataset), split="test")

    assert any("cross-split contamination" in warning.lower() for warning in score.warnings)
    assert int(score.provenance.get("dataset_cross_split_duplicates", "0")) > 0


def test_eval_runner_rejects_contaminated_dataset_in_strict_mode(tmp_path) -> None:
    """Strict integrity mode should raise when train/test contamination exists."""
    dataset = tmp_path / "dataset.jsonl"
    rows = [
        {
            "id": "train-a",
            "split": "train",
            "user_message": "Show my invoice",
            "expected_specialist": "support",
            "expected_behavior": "answer",
        },
        {
            "id": "test-a",
            "split": "test",
            "user_message": "Show my invoice",
            "expected_specialist": "support",
            "expected_behavior": "answer",
        },
    ]
    dataset.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    runner = EvalRunner(dataset_strict_integrity=True)
    try:
        runner.load_dataset_cases(str(dataset), split="all")
    except ValueError as exc:
        assert "cross-split contamination" in str(exc).lower()
    else:  # pragma: no cover - explicit assertion path
        raise AssertionError("Expected strict integrity mode to reject contaminated dataset")


def test_eval_runner_excludes_generated_failure_training_cases_by_default(tmp_path) -> None:
    """Default directory-backed evals should not grade generated failure-cluster training cases."""
    cases_dir = tmp_path / "cases"
    training_dir = cases_dir / "training"
    training_dir.mkdir(parents=True)

    (cases_dir / "heldout.yaml").write_text(
        yaml.safe_dump(
            {
                "cases": [
                    {
                        "id": "heldout-1",
                        "category": "routing",
                        "user_message": "Route me to support",
                        "expected_specialist": "support",
                        "expected_behavior": "answer",
                        "tags": ["heldout"],
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (training_dir / "generated_failures.yaml").write_text(
        yaml.safe_dump(
            {
                "cases": [
                    {
                        "id": "fc_cluster_001",
                        "category": "routing",
                        "user_message": "Generated from failure cluster",
                        "expected_specialist": "support",
                        "expected_behavior": "answer",
                        "split": "train",
                        "tags": ["generated_from:failure_cluster:cluster-1"],
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    runner = EvalRunner(cases_dir=str(cases_dir))

    default_cases = runner.load_cases()
    assert [case.id for case in default_cases] == ["heldout-1"]

    training_cases = runner.load_cases(include_generated_training=True)
    assert {case.id for case in training_cases} == {"heldout-1", "fc_cluster_001"}


def test_eval_runner_disambiguates_duplicate_yaml_case_ids_before_saving_results(tmp_path) -> None:
    """Directory-based eval corpora should not crash when multiple files reuse case IDs."""
    from evals.results_store import EvalResultsStore

    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()

    shared_case = {
        "id": "shared_case",
        "category": "routing",
        "user_message": "Route me to support",
        "expected_specialist": "support",
        "expected_behavior": "answer",
    }
    (cases_dir / "suite_a.yaml").write_text(
        yaml.safe_dump({"cases": [shared_case, shared_case]}, sort_keys=False),
        encoding="utf-8",
    )
    (cases_dir / "suite_b.yaml").write_text(
        yaml.safe_dump({"cases": [shared_case]}, sort_keys=False),
        encoding="utf-8",
    )

    def agent(message: str, config: dict | None = None) -> dict:
        del message, config
        return {
            "response": "Support can help.",
            "specialist_used": "support",
            "safety_violation": False,
            "latency_ms": 12.0,
            "token_count": 20,
        }

    results_store = EvalResultsStore(db_path=str(tmp_path / "results.db"))
    runner = EvalRunner(
        cases_dir=str(cases_dir),
        agent_fn=agent,
        cache_enabled=False,
        results_store=results_store,
    )

    loaded_cases = runner.load_cases()

    assert len(loaded_cases) == 3
    assert len({case.id for case in loaded_cases}) == 3

    runner.run()

    assert runner.last_evaluation_run is not None
    saved = results_store.get_run(runner.last_evaluation_run.run_id)
    assert saved is not None
    assert len(saved.examples) == 3
    assert len({example.example_id for example in saved.examples}) == 3


def test_composite_scorer_reports_confidence_intervals() -> None:
    """Composite scores should include bootstrap confidence intervals for key metrics."""
    scorer = CompositeScorer()
    results = [
        EvalResult(
            case_id="a",
            category="happy_path",
            passed=True,
            quality_score=0.9,
            safety_passed=True,
            latency_ms=120.0,
            token_count=100,
        ),
        EvalResult(
            case_id="b",
            category="happy_path",
            passed=False,
            quality_score=0.4,
            safety_passed=False,
            latency_ms=650.0,
            token_count=500,
        ),
        EvalResult(
            case_id="c",
            category="regression",
            passed=True,
            quality_score=0.8,
            safety_passed=True,
            latency_ms=300.0,
            token_count=220,
        ),
    ]

    score = scorer.score(results)
    assert set(score.confidence_intervals.keys()) == {"quality", "safety", "latency", "cost", "composite"}
    for bounds in score.confidence_intervals.values():
        assert len(bounds) == 2
        assert bounds[0] <= bounds[1]


def test_eval_runner_adds_reproducibility_fingerprints_and_cost_estimate(tmp_path) -> None:
    """Run provenance should include reproducibility fingerprints and cost metadata."""
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "id": "cost-1",
                "split": "test",
                "user_message": "Track shipment",
                "expected_specialist": "orders",
                "expected_behavior": "answer",
                "expected_keywords": ["shipment"],
            }
        ),
        encoding="utf-8",
    )

    def fixed_agent(message: str, config: dict | None = None) -> dict:
        return {
            "response": "Shipment is in transit.",
            "specialist_used": "orders",
            "safety_violation": False,
            "latency_ms": 55.0,
            "token_count": 500,
        }

    runner = EvalRunner(
        agent_fn=fixed_agent,
        token_cost_per_1k=2.0,
        random_seed=17,
        cache_enabled=False,
    )
    score = runner.run(config={"temperature": 0.0}, dataset_path=str(dataset), split="test")

    assert score.total_tokens == 500
    assert score.estimated_cost_usd == 1.0
    assert score.provenance.get("config_fingerprint")
    assert score.provenance.get("dataset_fingerprint")
    assert score.provenance.get("eval_fingerprint")
    assert score.provenance.get("seed") == "17"
