"""Tests for the Improvements API and lineage store."""

from __future__ import annotations

import tempfile
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import improvements as improvements_routes
from api.models import PendingReview
from evals.results_model import EvalResultSet, ExampleResult, GraderScore, ResultSummary, MetricSummary
from evals.scorer import CompositeScore, EvalResult
from optimizer.improvement_lineage import ImprovementLineageStore
from optimizer.memory import OptimizationAttempt, OptimizationMemory


@pytest.fixture()
def lineage_db(tmp_path):
    return ImprovementLineageStore(db_path=str(tmp_path / "lineage.db"))


@pytest.fixture()
def memory_db(tmp_path):
    return OptimizationMemory(db_path=str(tmp_path / "memory.db"))


@pytest.fixture()
def app_with_improvements(memory_db, lineage_db):
    app = FastAPI()
    app.include_router(improvements_routes.router)
    app.state.optimization_memory = memory_db
    app.state.improvement_lineage = lineage_db

    class _PendingStore:
        def list_pending(self, limit: int = 50):
            return []

    app.state.pending_review_store = _PendingStore()
    return app


@pytest.fixture()
def client(app_with_improvements) -> TestClient:
    return TestClient(app_with_improvements)


def _log_attempt(memory: OptimizationMemory, **kwargs):
    attempt = OptimizationAttempt(
        attempt_id=kwargs.pop("attempt_id", "attempt-1"),
        timestamp=kwargs.pop("timestamp", 100.0),
        change_description=kwargs.pop("change_description", "Increase max_turns"),
        config_diff=kwargs.pop("config_diff", "+ max_turns: 20"),
        status=kwargs.pop("status", "accepted"),
        config_section=kwargs.pop("config_section", "thresholds"),
        score_before=kwargs.pop("score_before", 0.65),
        score_after=kwargs.pop("score_after", 0.72),
        **kwargs,
    )
    memory.log(attempt)
    return attempt


def test_list_empty_improvements(client: TestClient) -> None:
    response = client.get("/api/improvements")
    assert response.status_code == 200
    data = response.json()
    assert data == {"total": 0, "filtered": 0, "items": []}


def test_list_improvements_reflects_attempts(client: TestClient, memory_db) -> None:
    _log_attempt(memory_db, attempt_id="a1", status="accepted", timestamp=100.0)
    _log_attempt(
        memory_db,
        attempt_id="a2",
        status="rejected_constraints",
        change_description="Tighten safety refusal",
        score_before=0.7,
        score_after=0.69,
        timestamp=200.0,
    )

    response = client.get("/api/improvements")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["filtered"] == 2

    ids_in_order = [item["attempt_id"] for item in data["items"]]
    assert ids_in_order == ["a2", "a1"]  # newest first
    a2 = data["items"][0]
    assert a2["status"] == "rejected"
    assert a2["rejection_reason"] == "constraints"
    assert a2["score_delta"] == pytest.approx(-0.01)


def test_lineage_promotion_classifies_as_promoted(
    client: TestClient, memory_db, lineage_db
) -> None:
    _log_attempt(memory_db, attempt_id="a3", status="accepted", timestamp=300.0)
    lineage_db.record("a3", "deploy_canary", version=4)
    lineage_db.record("a3", "promote", version=4)

    response = client.get("/api/improvements/a3")
    assert response.status_code == 200
    record = response.json()
    assert record["status"] == "promoted"
    assert record["deployed_version"] == 4
    assert [event["event_type"] for event in record["lineage"]] == [
        "deploy_canary",
        "promote",
    ]


def test_measure_endpoint_appends_lineage(
    client: TestClient, memory_db, lineage_db
) -> None:
    _log_attempt(memory_db, attempt_id="a4", status="accepted", timestamp=400.0)
    lineage_db.record("a4", "promote", version=6)

    response = client.post(
        "/api/improvements/a4/measure",
        json={
            "eval_run_id": "run-1",
            "score_before": 0.70,
            "score_after": 0.78,
            "notes": "prod eval after 7 days",
        },
    )
    assert response.status_code == 200
    record = response.json()
    assert record["status"] == "measured"
    assert record["measurement"]["eval_run_id"] == "run-1"
    assert pytest.approx(record["measurement"]["delta"]) == 0.08


def test_measure_unknown_attempt_returns_404(client: TestClient) -> None:
    response = client.post(
        "/api/improvements/unknown/measure",
        json={"eval_run_id": "run-x", "score_before": 0.1, "score_after": 0.2},
    )
    assert response.status_code == 404


def test_filter_by_status(client: TestClient, memory_db, lineage_db) -> None:
    _log_attempt(memory_db, attempt_id="a5", status="accepted", timestamp=500.0)
    _log_attempt(
        memory_db,
        attempt_id="a6",
        status="rejected_regression",
        timestamp=600.0,
    )
    lineage_db.record("a5", "deploy_canary", version=9)

    response = client.get("/api/improvements?status=deployed_canary")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["filtered"] == 1
    assert data["items"][0]["attempt_id"] == "a5"


def test_verify_improvement_reruns_baseline_cases_for_pending_review(
    memory_db: OptimizationMemory,
    lineage_db: ImprovementLineageStore,
    tmp_path,
) -> None:
    _log_attempt(
        memory_db,
        attempt_id="a7",
        status="pending_review",
        timestamp=700.0,
        score_before=0.71,
        score_after=0.79,
    )
    lineage_db.record_attempt(
        attempt_id="a7",
        status="pending_review",
        eval_run_id="eval-task-7",
        eval_result_run_id="baseline-run-7",
        score_before=0.71,
        score_after=0.79,
    )

    baseline = EvalResultSet(
        run_id="baseline-run-7",
        timestamp="2026-01-01T00:00:00Z",
        mode="mock",
        config_snapshot={"prompts": {"root": "baseline"}},
        summary=ResultSummary(
            total=1,
            passed=0,
            failed=1,
            metrics={"composite": MetricSummary(mean=0.71, median=0.71, std=0.0, min=0.71, max=0.71, histogram=[1] + [0] * 9)},
        ),
        examples=[
            ExampleResult(
                example_id="case-1",
                input={"user_message": "Where is my refund?"},
                expected={
                    "expected_specialist": "billing",
                    "expected_behavior": "answer",
                    "expected_keywords": ["refund"],
                    "expected_tool": "refund_lookup",
                    "reference_answer": "",
                },
                actual={"response": "unsafe baseline"},
                scores={
                    "quality": GraderScore(value=0.2, reasoning=""),
                    "safety": GraderScore(value=1.0, reasoning=""),
                    "composite": GraderScore(value=0.71, reasoning=""),
                },
                passed=False,
                failure_reasons=["missed refund lookup"],
                category="routing",
            )
        ],
    )

    class _ResultsStore:
        def get_run(self, run_id: str):
            if run_id == "baseline-run-7":
                return baseline
            return None

    class _EvalRunner:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def run_cases(self, cases, config=None, category=None, split="all", progress_callback=None):  # noqa: ANN001, ARG002
            self.calls.append({
                "cases": cases,
                "config": config,
                "category": category,
                "split": split,
            })
            return CompositeScore(
                quality=0.84,
                safety=1.0,
                latency=0.75,
                cost=0.81,
                composite=0.82,
                total_cases=1,
                passed_cases=1,
                results=[
                    EvalResult(
                        case_id="case-1",
                        category="routing",
                        passed=True,
                        quality_score=0.84,
                        safety_passed=True,
                        latency_ms=120.0,
                        token_count=88,
                        input_payload={"user_message": "Where is my refund?"},
                        actual_output={"response": "I checked your refund.", "specialist_used": "billing"},
                    )
                ],
                run_id="verify-run-7",
            )

    class _PendingStore:
        def __init__(self) -> None:
            self.review = PendingReview(
                attempt_id="a7",
                proposed_config={"prompts": {"root": "candidate"}},
                current_config={"prompts": {"root": "baseline"}},
                config_diff="- root: baseline\n+ root: candidate",
                score_before=0.71,
                score_after=0.79,
                change_description="Tighten refund routing",
                reasoning="Use billing specialist sooner.",
                created_at="2026-01-01T00:00:00Z",
                strategy="simple",
                deploy_scores={"composite": 0.79},
                deploy_strategy="immediate",
                baseline_eval_run_id="eval-task-7",
                baseline_result_run_id="baseline-run-7",
            )

        def list_pending(self, limit: int = 50):
            return [self.review]

        def get_review(self, attempt_id: str):
            return self.review if attempt_id == "a7" else None

    class _Deployer:
        def get_active_config(self):
            return {"prompts": {"root": "active"}}

    app = FastAPI()
    app.include_router(improvements_routes.router)
    app.state.optimization_memory = memory_db
    app.state.improvement_lineage = lineage_db
    app.state.pending_review_store = _PendingStore()
    app.state.results_store = _ResultsStore()
    app.state.eval_runner = _EvalRunner()
    app.state.deployer = _Deployer()

    client = TestClient(app)

    response = client.post("/api/improvements/a7/verify")

    assert response.status_code == 200
    record = response.json()
    assert record["verification"]["status"] == "passed"
    assert record["verification"]["phase"] == "pre_deploy"
    assert record["verification"]["eval_run_id"] == "verify-run-7"
    assert record["verification"]["composite_delta"] == pytest.approx(0.11)
