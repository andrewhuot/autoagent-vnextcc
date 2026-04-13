"""Tests for optimize API route behavior."""

from __future__ import annotations

import importlib
import importlib.util
import threading
import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from api.routes import config as config_routes
from api.routes import optimize as optimize_routes
from api.tasks import Task, TaskManager
from deployer import Deployer
from evals.scorer import CompositeScore, DimensionScores, EvalResult
from observer.metrics import HealthMetrics, HealthReport
from optimizer.loop import Optimizer
from optimizer.memory import OptimizationAttempt, OptimizationMemory
from optimizer.proposer import Proposal
from optimizer.search import SearchStrategy


class _DummyObserver:
    def observe(self, window: int = 100):  # noqa: ARG002
        return SimpleNamespace(
            needs_optimization=True,
            metrics=SimpleNamespace(to_dict=lambda: {"success_rate": 0.5}),
            failure_buckets={"routing_error": 2},
        )


class _DummyOptimizer:
    def __init__(self) -> None:
        self.search_strategy = SearchStrategy.SIMPLE
        self.search_budget = SimpleNamespace(max_candidates=3, max_eval_budget=2, max_cost_dollars=1.0)
        self.applied_settings: list[tuple[str, int, int, float]] = []
        self.received_current_configs: list[dict] = []

    def optimize(self, report, current_config, failure_samples=None):  # noqa: ANN001, ARG002
        self.received_current_configs.append(current_config)
        self.applied_settings.append(
            (
                self.search_strategy.value,
                self.search_budget.max_candidates,
                self.search_budget.max_eval_budget,
                self.search_budget.max_cost_dollars,
            )
        )
        return None, "No proposal generated"

    def get_strategy_diagnostics(self):
        return SimpleNamespace(
            strategy=self.search_strategy.value,
            selected_operator_family=None,
            pareto_front=[],
            pareto_recommendation_id=None,
            governance_notes=[],
            global_dimensions={},
        )


class _DummyDeployer:
    def __init__(self) -> None:
        self.version_manager = SimpleNamespace(save_version=lambda *args, **kwargs: None)

    def get_active_config(self):
        return {}

    def deploy(self, config, scores):  # noqa: ANN001, ARG002
        return "noop deploy"


class _DummyEvalRunner:
    def run(self, config=None):  # noqa: ANN001, ARG002
        return SimpleNamespace(
            composite=0.75,
            quality=0.8,
            safety=0.95,
            latency=0.7,
            cost=0.6,
            global_dimensions={},
            per_agent_dimensions={},
        )


class _DummyStore:
    def get_failures(self, limit=25):  # noqa: ANN001, ARG002
        return []


class _DummyWsManager:
    async def broadcast(self, payload):  # noqa: ANN001, ARG002
        return None


class _DummyMemory:
    def recent(self, limit=1):  # noqa: ANN001, ARG002
        return []


class _ContextRecordingOptimizer(_DummyOptimizer):
    def __init__(self) -> None:
        super().__init__()
        self.received_reports: list[object] = []
        self.received_failure_samples: list[list[dict]] = []

    def optimize(self, report, current_config, failure_samples=None):  # noqa: ANN001, ARG002
        self.received_reports.append(report)
        self.received_failure_samples.append(list(failure_samples or []))
        return super().optimize(report, current_config, failure_samples=failure_samples)


class _StaticResultsStore:
    def __init__(self, result_set: object) -> None:
        self.result_set = result_set

    def get_run(self, run_id: str) -> object | None:
        if run_id == "run-eval-1234":
            return self.result_set
        return None


class _InMemoryPendingReviewStore:
    def __init__(self) -> None:
        self._reviews: dict[str, object] = {}

    def save_review(self, review) -> None:  # noqa: ANN001
        attempt_id = getattr(review, "attempt_id", None)
        if attempt_id is None and isinstance(review, dict):
            attempt_id = review.get("attempt_id")
        assert attempt_id is not None
        self._reviews[str(attempt_id)] = review

    def list_pending(self, limit: int = 50) -> list[object]:
        reviews = list(self._reviews.values())
        return reviews[:limit]

    def get_review(self, attempt_id: str) -> object | None:
        return self._reviews.get(attempt_id)

    def delete_review(self, attempt_id: str) -> bool:
        return self._reviews.pop(attempt_id, None) is not None


class _RecordingTask(Task):
    __slots__ = ("progress_log",)

    def __init__(self, task_id: str, task_type: str) -> None:
        object.__setattr__(self, "progress_log", [])
        super().__init__(task_id=task_id, task_type=task_type)

    def __setattr__(self, name, value):  # noqa: ANN001
        object.__setattr__(self, name, value)
        if name == "progress":
            progress_log = getattr(self, "progress_log", None)
            if progress_log is not None:
                progress_log.append(value)


class _RecordingTaskManager(TaskManager):
    def create_task(self, task_type, fn):  # noqa: ANN001
        task_id = str(uuid.uuid4())[:12]
        task = _RecordingTask(task_id=task_id, task_type=task_type)

        def _run() -> None:
            try:
                with self._lock:
                    task.status = "running"
                    task.updated_at = datetime.now(timezone.utc)
                result = fn(task)
                with self._lock:
                    task.status = "completed"
                    task.progress = 100
                    if task.result is None:
                        task.result = result
                    task.updated_at = datetime.now(timezone.utc)
            except Exception as exc:  # pragma: no cover - mirrors production manager
                with self._lock:
                    task.status = "failed"
                    task.error = str(exc)
                    task.updated_at = datetime.now(timezone.utc)

        thread = threading.Thread(target=_run, daemon=True)
        task._thread = thread

        with self._lock:
            self._tasks[task_id] = task

        thread.start()
        return task


class _RecordingWsManager:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def broadcast(self, payload):  # noqa: ANN001
        self.messages.append(payload)
        return None


class _RealObserver:
    def observe(self, window: int = 100) -> HealthReport:  # noqa: ARG002
        time.sleep(0.01)
        return HealthReport(
            metrics=HealthMetrics(
                success_rate=0.61,
                avg_latency_ms=410.0,
                error_rate=0.22,
                safety_violation_rate=0.01,
                avg_cost=0.19,
                total_conversations=42,
            ),
            failure_buckets={"routing_error": 4},
            needs_optimization=True,
            reason="error rate too high",
        )


class _PromptBoostProposer:
    def propose(
        self,
        current_config: dict,
        health_metrics: dict,
        failure_samples: list[dict],
        failure_buckets: dict[str, int],
        past_attempts: list[dict],
    ) -> Proposal:
        del health_metrics, failure_samples, failure_buckets, past_attempts
        candidate = deepcopy(current_config)
        candidate["prompts"]["root"] = current_config["prompts"]["root"] + " Validate every answer."
        return Proposal(
            change_description="Strengthen root prompt",
            config_section="prompts",
            new_config=candidate,
            reasoning="Improve routing clarity and answer quality",
        )


class _PromptSensitiveEvalRunner:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run(self, config=None):  # noqa: ANN001
        config_dict = config or {}
        self.calls.append(config_dict)
        time.sleep(0.01)
        prompt = ((config_dict.get("prompts") or {}).get("root") or "")
        improved = "Validate every answer." in prompt
        if improved:
            return self._score(
                quality=0.84,
                safety=1.0,
                latency=0.79,
                cost=0.78,
                composite=0.84,
                quality_values=[0.92, 0.88, 0.83, 0.86, 0.84],
                global_dimensions=DimensionScores(
                    task_success_rate=0.84,
                    response_quality=0.84,
                    safety_compliance=1.0,
                ),
            )
        return self._score(
            quality=0.72,
            safety=1.0,
            latency=0.74,
            cost=0.73,
            composite=0.72,
            quality_values=[0.79, 0.74, 0.70, 0.69, 0.68],
            global_dimensions=DimensionScores(
                task_success_rate=0.72,
                response_quality=0.72,
                safety_compliance=1.0,
            ),
        )

    @staticmethod
    def _score(
        *,
        quality: float,
        safety: float,
        latency: float,
        cost: float,
        composite: float,
        quality_values: list[float],
        global_dimensions: DimensionScores,
    ) -> CompositeScore:
        results = [
            EvalResult(
                case_id=f"case-{index}",
                category="regression",
                passed=value >= 0.7,
                quality_score=value,
                safety_passed=True,
                latency_ms=120.0,
                token_count=180,
            )
            for index, value in enumerate(quality_values, start=1)
        ]
        return CompositeScore(
            quality=quality,
            safety=safety,
            latency=latency,
            cost=cost,
            composite=composite,
            safety_failures=0,
            total_cases=len(results),
            passed_cases=sum(1 for result in results if result.passed),
            results=results,
            dimensions=global_dimensions,
        )


class _RecordingDeployer(Deployer):
    def __init__(self, configs_dir: str) -> None:
        super().__init__(configs_dir=configs_dir, store=None)
        self.deploy_calls: list[dict[str, object]] = []

    def deploy(self, config: dict, scores: dict, *args, **kwargs) -> str:  # noqa: ANN401
        self.deploy_calls.append({"config": config, "scores": scores, "args": args, "kwargs": kwargs})
        return super().deploy(config, scores, *args, **kwargs)


class _FailureStore:
    def get_failures(self, limit=25):  # noqa: ANN001, ARG002
        return []


def _add_task_status_route(test_app: FastAPI) -> None:
    @test_app.get("/api/tasks/{task_id}")
    async def get_task_status(task_id: str) -> dict[str, object]:
        task = test_app.state.task_manager.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
        return task.to_dict()


@pytest.fixture()
def app() -> FastAPI:
    test_app = FastAPI()
    test_app.include_router(optimize_routes.router)
    test_app.state.task_manager = TaskManager()
    test_app.state.ws_manager = _DummyWsManager()
    test_app.state.observer = _DummyObserver()
    test_app.state.optimizer = _DummyOptimizer()
    test_app.state.deployer = _DummyDeployer()
    test_app.state.eval_runner = _DummyEvalRunner()
    test_app.state.conversation_store = _DummyStore()
    test_app.state.optimization_memory = _DummyMemory()
    test_app.state.pending_review_store = _InMemoryPendingReviewStore()
    return test_app


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _pending_review_payload(attempt_id: str = "attempt-pending") -> dict[str, object]:
    return {
        "attempt_id": attempt_id,
        "proposed_config": {
            "model": "gpt-5.4",
            "prompts": {"root": "Resolve support issues safely. Validate every answer."},
        },
        "current_config": {
            "model": "gpt-5.4",
            "prompts": {"root": "Resolve support issues safely."},
        },
        "config_diff": "- root: Resolve support issues safely.\n+ root: Resolve support issues safely. Validate every answer.",
        "score_before": 0.72,
        "score_after": 0.84,
        "change_description": "Strengthen root prompt",
        "reasoning": "Improve routing clarity and answer quality",
        "created_at": "2026-04-01T12:00:00+00:00",
        "strategy": "simple",
        "selected_operator_family": "prompts",
        "governance_notes": ["Protected safety floor at 99%."],
        "deploy_scores": {
            "quality": 0.84,
            "safety": 1.0,
            "latency": 0.79,
            "cost": 0.78,
            "composite": 0.84,
            "global_dimensions": {"task_success_rate": 0.84},
            "per_agent_dimensions": {},
        },
        "deploy_strategy": "immediate",
    }


def test_start_optimization_applies_requested_mode_settings(client: TestClient, app: FastAPI) -> None:
    response = client.post(
        "/api/optimize/run",
        json={
            "window": 50,
            "force": True,
            "mode": "research",
            "objective": "maximize quality",
            "guardrails": ["safety >= 0.99"],
            "research_algorithm": "bayesian",
            "budget_cycles": 12,
            "budget_dollars": 7.5,
        },
    )

    assert response.status_code == 202
    time.sleep(0.2)

    optimizer = app.state.optimizer
    assert optimizer.applied_settings == [("full", 20, 10, 7.5)]
    assert optimizer.search_strategy == SearchStrategy.SIMPLE


def test_start_optimization_uses_selected_agent_config_when_config_path_is_provided(
    client: TestClient,
    app: FastAPI,
    tmp_path,
) -> None:
    config_path = tmp_path / "selected-agent.yaml"
    config_path.write_text("model: selected-model\nprompts:\n  root: Selected config prompt\n", encoding="utf-8")

    response = client.post(
        "/api/optimize/run",
        json={
            "window": 25,
            "force": True,
            "mode": "standard",
            "objective": "",
            "guardrails": [],
            "research_algorithm": "",
            "budget_cycles": 5,
            "budget_dollars": 3.0,
            "config_path": str(config_path),
        },
    )

    assert response.status_code == 202
    time.sleep(0.2)

    optimizer = app.state.optimizer
    assert optimizer.received_current_configs[-1]["model"] == "selected-model"
    assert optimizer.received_current_configs[-1]["prompts"]["root"] == "Selected config prompt"


def test_start_optimization_uses_selected_eval_run_context_over_global_failures(
    tmp_path: Path,
) -> None:
    optimizer = _ContextRecordingOptimizer()
    task_manager = _RecordingTaskManager()

    eval_task = Task(task_id="eval-run-1234", task_type="eval")
    eval_task.status = "completed"
    eval_task.result = {
        "run_id": "run-eval-1234",
        "total_cases": 2,
        "passed_cases": 1,
        "safety_failures": 1,
        "cases": [
            {
                "case_id": "case-1",
                "category": "safety",
                "passed": False,
                "quality_score": 0.2,
                "safety_passed": False,
                "latency_ms": 420.0,
                "token_count": 150,
                "details": "safety check failed",
            },
            {
                "case_id": "case-2",
                "category": "happy_path",
                "passed": True,
                "quality_score": 0.9,
                "safety_passed": True,
                "latency_ms": 120.0,
                "token_count": 90,
                "details": "",
            },
        ],
    }
    task_manager._tasks[eval_task.task_id] = eval_task

    scoped_result_set = SimpleNamespace(
        examples=[
            SimpleNamespace(
                passed=False,
                input={"user_message": "Please review my PRD for unsafe gaps."},
                actual={
                    "response": "Here is unsafe advice.",
                    "specialist_used": "writer",
                    "tool_calls": [],
                    "latency_ms": 420.0,
                    "token_count": 150,
                },
                scores={"safety": SimpleNamespace(value=0.0)},
                failure_reasons=["safety check failed"],
            ),
            SimpleNamespace(
                passed=True,
                input={"user_message": "Summarize this spec."},
                actual={
                    "response": "Summary complete.",
                    "specialist_used": "writer",
                    "tool_calls": [],
                    "latency_ms": 120.0,
                    "token_count": 90,
                },
                scores={"safety": SimpleNamespace(value=1.0)},
                failure_reasons=[],
            ),
        ]
    )

    config_path = tmp_path / "selected-agent.yaml"
    config_path.write_text("model: selected-model\nprompts:\n  root: Selected config prompt\n", encoding="utf-8")

    test_app = FastAPI()
    test_app.include_router(optimize_routes.router)
    test_app.state.task_manager = task_manager
    test_app.state.ws_manager = _DummyWsManager()
    test_app.state.observer = _DummyObserver()
    test_app.state.optimizer = optimizer
    test_app.state.deployer = _DummyDeployer()
    test_app.state.eval_runner = _DummyEvalRunner()
    test_app.state.results_store = _StaticResultsStore(scoped_result_set)
    test_app.state.conversation_store = _FailureStore()
    test_app.state.optimization_memory = _DummyMemory()
    test_app.state.pending_review_store = _InMemoryPendingReviewStore()

    client = TestClient(test_app)

    response = client.post(
        "/api/optimize/run",
        json={
            "window": 25,
            "force": True,
            "mode": "standard",
            "objective": "",
            "guardrails": [],
            "research_algorithm": "",
            "budget_cycles": 5,
            "budget_dollars": 3.0,
            "config_path": str(config_path),
            "eval_run_id": "eval-run-1234",
        },
    )

    assert response.status_code == 202
    time.sleep(0.2)

    assert optimizer.received_failure_samples
    assert optimizer.received_failure_samples[-1][0]["user_message"] == "Please review my PRD for unsafe gaps."

    scoped_report = optimizer.received_reports[-1]
    assert scoped_report.metrics.total_conversations == 2
    assert scoped_report.failure_buckets["safety_violation"] == 1
    assert scoped_report.reason.startswith("scoped_eval_run=eval-run-1234")


def test_start_optimization_requires_eval_evidence_before_creating_task(
    client: TestClient,
    app: FastAPI,
) -> None:
    response = client.post(
        "/api/optimize/run",
        json={
            "force": True,
            "require_eval_evidence": True,
            "mode": "standard",
            "objective": "",
            "guardrails": [],
            "research_algorithm": "",
            "budget_cycles": 5,
            "budget_dollars": 3.0,
        },
    )

    assert response.status_code == 400
    assert "Run Eval first" in response.json()["detail"]


def test_start_optimization_rejects_incomplete_eval_evidence(
    client: TestClient,
    app: FastAPI,
) -> None:
    eval_task = Task(task_id="eval-run-in-progress", task_type="eval")
    eval_task.status = "running"
    app.state.task_manager._tasks[eval_task.task_id] = eval_task

    response = client.post(
        "/api/optimize/run",
        json={
            "force": True,
            "require_eval_evidence": True,
            "eval_run_id": "eval-run-in-progress",
            "mode": "standard",
            "objective": "",
            "guardrails": [],
            "research_algorithm": "",
            "budget_cycles": 5,
            "budget_dollars": 3.0,
        },
    )

    assert response.status_code == 409
    assert "results not yet available" in response.json()["detail"]


def test_start_optimization_falls_back_to_eval_task_cases_when_structured_results_are_missing(
    tmp_path: Path,
) -> None:
    optimizer = _ContextRecordingOptimizer()
    task_manager = _RecordingTaskManager()

    eval_task = Task(task_id="eval-run-5678", task_type="eval")
    eval_task.status = "completed"
    eval_task.result = {
        "run_id": "run-eval-5678",
        "total_cases": 2,
        "passed_cases": 0,
        "safety_failures": 1,
        "cases": [
            {
                "case_id": "case-routing",
                "category": "routing",
                "passed": False,
                "quality_score": 0.2,
                "safety_passed": True,
                "latency_ms": 210.0,
                "token_count": 110,
                "details": "routing: expected=prd_reviewer got=support; keywords: missing expected keywords",
            },
            {
                "case_id": "case-safety",
                "category": "safety",
                "passed": False,
                "quality_score": 0.1,
                "safety_passed": False,
                "latency_ms": 310.0,
                "token_count": 140,
                "details": "behavior: expected=refuse; safety check failed",
            },
        ],
    }
    task_manager._tasks[eval_task.task_id] = eval_task

    config_path = tmp_path / "selected-agent.yaml"
    config_path.write_text("model: selected-model\nprompts:\n  root: Selected config prompt\n", encoding="utf-8")

    test_app = FastAPI()
    test_app.include_router(optimize_routes.router)
    test_app.state.task_manager = task_manager
    test_app.state.ws_manager = _DummyWsManager()
    test_app.state.observer = _DummyObserver()
    test_app.state.optimizer = optimizer
    test_app.state.deployer = _DummyDeployer()
    test_app.state.eval_runner = _DummyEvalRunner()
    test_app.state.results_store = _StaticResultsStore(None)
    test_app.state.conversation_store = _FailureStore()
    test_app.state.optimization_memory = _DummyMemory()
    test_app.state.pending_review_store = _InMemoryPendingReviewStore()

    client = TestClient(test_app)

    response = client.post(
        "/api/optimize/run",
        json={
            "window": 25,
            "force": True,
            "mode": "standard",
            "objective": "",
            "guardrails": [],
            "research_algorithm": "",
            "budget_cycles": 5,
            "budget_dollars": 3.0,
            "config_path": str(config_path),
            "eval_run_id": "eval-run-5678",
        },
    )

    assert response.status_code == 202
    time.sleep(0.2)

    assert optimizer.received_failure_samples
    assert optimizer.received_failure_samples[-1][0]["user_message"] == "case-routing"

    scoped_report = optimizer.received_reports[-1]
    assert scoped_report.metrics.total_conversations == 2
    assert scoped_report.failure_buckets["routing_error"] == 1
    assert scoped_report.failure_buckets["safety_violation"] == 1


def test_pending_review_store_persists_reviews_to_json(tmp_path: Path) -> None:
    spec = importlib.util.find_spec("optimizer.pending_reviews")

    assert spec is not None

    module = importlib.import_module("optimizer.pending_reviews")
    store_dir = tmp_path / "workspace" / "pending_reviews"
    store = module.PendingReviewStore(store_dir=str(store_dir))
    review = module.PendingReview(
        attempt_id="attempt-persisted",
        proposed_config={"prompts": {"root": "new"}},
        current_config={"prompts": {"root": "old"}},
        config_diff="- root: old\n+ root: new",
        score_before=0.72,
        score_after=0.84,
        change_description="Strengthen root prompt",
        reasoning="Improve routing clarity and answer quality",
        created_at=datetime.now(timezone.utc),
        strategy="simple",
        selected_operator_family="prompts",
        governance_notes=["Protected safety floor at 99%."],
        deploy_scores={"composite": 0.84},
        deploy_strategy="immediate",
    )

    store.save_review(review)

    reloaded = module.PendingReviewStore(store_dir=str(store_dir))
    pending = reloaded.list_pending()

    assert [item.attempt_id for item in pending] == ["attempt-persisted"]
    assert pending[0].reasoning == "Improve routing clarity and answer quality"
    assert pending[0].deploy_strategy == "immediate"


def test_accepted_optimization_run_defaults_to_pending_human_review_and_skips_deploy(
    tmp_path: Path,
    base_config: dict,
) -> None:
    memory = OptimizationMemory(db_path=str(tmp_path / "optimizer_memory.db"))
    eval_runner = _PromptSensitiveEvalRunner()
    optimizer = Optimizer(
        eval_runner=eval_runner,
        memory=memory,
        proposer=_PromptBoostProposer(),
        require_statistical_significance=False,
    )
    deployer = _RecordingDeployer(configs_dir=str(tmp_path / "configs"))
    deployer.version_manager.save_version(base_config, scores={"composite": 0.72}, status="active")
    ws_manager = _RecordingWsManager()

    config_path = tmp_path / "workspace" / "selected-agent.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(base_config, sort_keys=False), encoding="utf-8")

    test_app = FastAPI()
    test_app.include_router(optimize_routes.router)
    test_app.include_router(config_routes.router)
    test_app.state.task_manager = _RecordingTaskManager()
    test_app.state.ws_manager = ws_manager
    test_app.state.observer = _RealObserver()
    test_app.state.optimizer = optimizer
    test_app.state.deployer = deployer
    test_app.state.eval_runner = eval_runner
    test_app.state.conversation_store = _FailureStore()
    test_app.state.optimization_memory = memory
    test_app.state.pending_review_store = _InMemoryPendingReviewStore()
    test_app.state.version_manager = deployer.version_manager

    _add_task_status_route(test_app)

    client = TestClient(test_app)

    response = client.post(
        "/api/optimize/run",
        json={
            "window": 25,
            "force": True,
            "mode": "standard",
            "objective": "improve answer quality",
            "guardrails": ["safety >= 0.99"],
            "research_algorithm": "",
            "budget_cycles": 5,
            "budget_dollars": 3.0,
            "config_path": str(config_path),
        },
    )

    assert response.status_code == 202
    task_id = response.json()["task_id"]

    task_payload: dict[str, object] | None = None
    for _ in range(100):
        task_response = client.get(f"/api/tasks/{task_id}")
        assert task_response.status_code == 200
        task_payload = task_response.json()
        if task_payload["status"] == "completed":
            break
        time.sleep(0.02)

    assert task_payload is not None
    assert task_payload["status"] == "completed"

    result = task_payload["result"]
    assert result["accepted"] is True
    assert result["pending_review"] is True
    assert result["status_message"] == "Pending human review"
    assert result["deploy_message"] is None
    assert len(deployer.deploy_calls) == 0

    pending_response = client.get("/api/optimize/pending")
    assert pending_response.status_code == 200
    pending_reviews = pending_response.json()
    assert len(pending_reviews) == 1
    assert pending_reviews[0]["attempt_id"]
    assert pending_reviews[0]["change_description"] == "Strengthen root prompt"
    assert pending_reviews[0]["reasoning"] == "Improve routing clarity and answer quality"
    assert "Validate every answer." in pending_reviews[0]["config_diff"]

    history_response = client.get("/api/optimize/history")
    assert history_response.status_code == 200
    history = history_response.json()
    assert history[0]["status"] == "pending_review"

    assert ws_manager.messages[-1]["type"] == "optimize_pending_review"
    assert ws_manager.messages[-1]["task_id"] == task_id
    assert ws_manager.messages[-1]["status"] == "Pending human review"


def test_accepted_optimization_run_promotes_active_config_persists_history_and_broadcasts_completion(
    tmp_path: Path,
    base_config: dict,
) -> None:
    memory = OptimizationMemory(db_path=str(tmp_path / "optimizer_memory.db"))
    eval_runner = _PromptSensitiveEvalRunner()
    optimizer = Optimizer(
        eval_runner=eval_runner,
        memory=memory,
        proposer=_PromptBoostProposer(),
        require_statistical_significance=False,
    )
    observe_calls: list[int] = []
    original_optimize = optimizer.optimize
    optimize_calls: list[dict[str, object]] = []

    def wrapped_optimize(report, current_config, failure_samples=None, **kwargs):  # noqa: ANN001
        optimize_calls.append({
            "report": report,
            "current_config": current_config,
            "failure_samples": failure_samples,
            "kwargs": kwargs,
        })
        return original_optimize(report, current_config, failure_samples=failure_samples, **kwargs)

    optimizer.optimize = wrapped_optimize  # type: ignore[method-assign]

    deployer = _RecordingDeployer(configs_dir=str(tmp_path / "configs"))
    deployer.version_manager.save_version(base_config, scores={"composite": 0.72}, status="active")
    ws_manager = _RecordingWsManager()

    config_path = tmp_path / "workspace" / "selected-agent.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(base_config, sort_keys=False), encoding="utf-8")

    observer = _RealObserver()
    original_observe = observer.observe

    def wrapped_observe(window: int = 100) -> HealthReport:
        observe_calls.append(window)
        return original_observe(window=window)

    observer.observe = wrapped_observe  # type: ignore[method-assign]

    test_app = FastAPI()
    test_app.include_router(optimize_routes.router)
    test_app.include_router(config_routes.router)
    test_app.state.task_manager = _RecordingTaskManager()
    test_app.state.ws_manager = ws_manager
    test_app.state.observer = observer
    test_app.state.optimizer = optimizer
    test_app.state.deployer = deployer
    test_app.state.eval_runner = eval_runner
    test_app.state.conversation_store = _FailureStore()
    test_app.state.optimization_memory = memory
    test_app.state.version_manager = deployer.version_manager

    _add_task_status_route(test_app)

    client = TestClient(test_app)

    response = client.post(
        "/api/optimize/run",
        json={
            "window": 25,
            "force": True,
            "require_human_approval": False,
            "mode": "standard",
            "objective": "improve answer quality",
            "guardrails": ["safety >= 0.99"],
            "research_algorithm": "",
            "budget_cycles": 5,
            "budget_dollars": 3.0,
            "config_path": str(config_path),
        },
    )

    assert response.status_code == 202
    task_id = response.json()["task_id"]

    task_payload: dict[str, object] | None = None
    for _ in range(100):
        task_response = client.get(f"/api/tasks/{task_id}")
        assert task_response.status_code == 200
        task_payload = task_response.json()
        if task_payload["status"] == "completed":
            break
        time.sleep(0.02)

    assert task_payload is not None
    assert task_payload["status"] == "completed"

    result = task_payload["result"]
    assert result["accepted"] is True
    assert "ACCEPTED" in result["status_message"]
    assert result["change_description"] == "Strengthen root prompt"
    assert "Validate every answer." in result["config_diff"]
    assert result["score_before"] == pytest.approx(0.72)
    assert result["score_after"] == pytest.approx(0.84)
    assert "active" in result["deploy_message"].lower()
    assert result["search_strategy"] == "simple"
    assert result["strategy"] == "simple"
    assert isinstance(result["governance_notes"], list)
    assert result["global_dimensions"]["task_success_rate"] == pytest.approx(0.84)

    task = test_app.state.task_manager.get_task(task_id)
    assert task is not None
    assert set((10, 20, 30, 40, 70, 90, 100)).issubset(set(task.progress_log))

    assert observe_calls == [25]
    assert len(optimize_calls) == 1
    assert len(eval_runner.calls) == 4
    assert len(deployer.deploy_calls) == 1
    assert deployer.deploy_calls[0]["kwargs"].get("strategy") == "immediate"

    history_response = client.get("/api/optimize/history")
    assert history_response.status_code == 200
    history = history_response.json()
    assert len(history) == 1
    assert history[0]["change_description"] == "Strengthen root prompt"
    assert "significance_p_value" in history[0]
    assert "significance_delta" in history[0]
    assert "significance_n" in history[0]

    configs_response = client.get("/api/config/list")
    assert configs_response.status_code == 200
    configs_payload = configs_response.json()
    assert configs_payload["active_version"] == 2
    assert configs_payload["canary_version"] is None
    assert any(version["version"] == 2 and version["status"] == "active" for version in configs_payload["versions"])

    assert ws_manager.messages[-1]["type"] == "optimize_complete"
    assert ws_manager.messages[-1]["task_id"] == task_id
    assert ws_manager.messages[-1]["accepted"] is True
    assert ws_manager.messages[-1]["status"].startswith("ACCEPTED:")


def test_approve_pending_review_deploys_and_removes_review(tmp_path: Path) -> None:
    deployer = _RecordingDeployer(configs_dir=str(tmp_path / "configs"))
    ws_manager = _RecordingWsManager()
    review_store = _InMemoryPendingReviewStore()
    review_store.save_review(_pending_review_payload())
    memory = OptimizationMemory(db_path=str(tmp_path / "optimizer_memory.db"))
    memory.log(
        OptimizationAttempt(
            attempt_id="attempt-pending",
            timestamp=time.time(),
            change_description="Strengthen root prompt",
            config_diff="- root: old\n+ root: new",
            status="pending_review",
            config_section="prompts",
            score_before=0.72,
            score_after=0.84,
            health_context='{"metrics":{"success_rate":0.61}}',
        )
    )

    test_app = FastAPI()
    test_app.include_router(optimize_routes.router)
    test_app.state.task_manager = TaskManager()
    test_app.state.ws_manager = ws_manager
    test_app.state.observer = _DummyObserver()
    test_app.state.optimizer = _DummyOptimizer()
    test_app.state.deployer = deployer
    test_app.state.eval_runner = _DummyEvalRunner()
    test_app.state.conversation_store = _DummyStore()
    test_app.state.optimization_memory = memory
    test_app.state.pending_review_store = review_store

    client = TestClient(test_app)

    response = client.post("/api/optimize/pending/attempt-pending/approve")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "approved"
    assert "active" in payload["deploy_message"].lower()
    assert len(deployer.deploy_calls) == 1
    assert review_store.get_review("attempt-pending") is None

    history_response = client.get("/api/optimize/history")
    assert history_response.status_code == 200
    history = history_response.json()
    assert history[0]["status"] == "accepted"


def test_reject_pending_review_discards_review_without_deploy(tmp_path: Path) -> None:
    deployer = _RecordingDeployer(configs_dir=str(tmp_path / "configs"))
    review_store = _InMemoryPendingReviewStore()
    review_store.save_review(_pending_review_payload(attempt_id="attempt-reject"))
    memory = OptimizationMemory(db_path=str(tmp_path / "optimizer_memory.db"))
    memory.log(
        OptimizationAttempt(
            attempt_id="attempt-reject",
            timestamp=time.time(),
            change_description="Strengthen root prompt",
            config_diff="- root: old\n+ root: new",
            status="pending_review",
            config_section="prompts",
            score_before=0.72,
            score_after=0.84,
            health_context='{"metrics":{"success_rate":0.61}}',
        )
    )

    test_app = FastAPI()
    test_app.include_router(optimize_routes.router)
    test_app.state.task_manager = TaskManager()
    test_app.state.ws_manager = _RecordingWsManager()
    test_app.state.observer = _DummyObserver()
    test_app.state.optimizer = _DummyOptimizer()
    test_app.state.deployer = deployer
    test_app.state.eval_runner = _DummyEvalRunner()
    test_app.state.conversation_store = _DummyStore()
    test_app.state.optimization_memory = memory
    test_app.state.pending_review_store = review_store

    client = TestClient(test_app)

    response = client.post("/api/optimize/pending/attempt-reject/reject")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "rejected"
    assert review_store.get_review("attempt-reject") is None
    assert len(deployer.deploy_calls) == 0

    history_response = client.get("/api/optimize/history")
    assert history_response.status_code == 200
    history = history_response.json()
    assert history[0]["status"] == "rejected_human"


def test_start_optimization_bootstraps_active_config_from_base_config_when_none_exists(
    tmp_path: Path,
) -> None:
    deployer = _RecordingDeployer(configs_dir=str(tmp_path / "configs"))
    optimizer = _DummyOptimizer()

    test_app = FastAPI()
    test_app.include_router(optimize_routes.router)
    test_app.include_router(config_routes.router)
    test_app.state.task_manager = TaskManager()
    test_app.state.ws_manager = _RecordingWsManager()
    test_app.state.observer = _DummyObserver()
    test_app.state.optimizer = optimizer
    test_app.state.deployer = deployer
    test_app.state.eval_runner = _DummyEvalRunner()
    test_app.state.conversation_store = _FailureStore()
    test_app.state.optimization_memory = _DummyMemory()
    test_app.state.version_manager = deployer.version_manager
    _add_task_status_route(test_app)

    client = TestClient(test_app)

    response = client.post(
        "/api/optimize/run",
        json={
            "window": 20,
            "force": True,
            "mode": "standard",
            "objective": "",
            "guardrails": [],
            "research_algorithm": "",
            "budget_cycles": 3,
            "budget_dollars": 2.0,
        },
    )

    assert response.status_code == 202
    task_id = response.json()["task_id"]

    task_payload = None
    for _ in range(100):
        task_response = client.get(f"/api/tasks/{task_id}")
        assert task_response.status_code == 200
        task_payload = task_response.json()
        if task_payload["status"] == "completed":
            break
        time.sleep(0.02)

    assert task_payload is not None
    assert task_payload["status"] == "completed"
    assert optimizer.received_current_configs[-1]["model"] == "gemini-2.0-flash"
    assert "prompts" in optimizer.received_current_configs[-1]

    configs_response = client.get("/api/config/list")
    assert configs_response.status_code == 200
    configs_payload = configs_response.json()
    assert configs_payload["active_version"] == 1
    assert any(version["version"] == 1 and version["status"] == "active" for version in configs_payload["versions"])


def test_start_optimization_with_minimal_config_completes_without_crashing(
    tmp_path: Path,
    base_config: dict,
) -> None:
    memory = OptimizationMemory(db_path=str(tmp_path / "optimizer_memory.db"))
    deployer = _RecordingDeployer(configs_dir=str(tmp_path / "configs"))
    deployer.version_manager.save_version(base_config, scores={"composite": 0.72}, status="active")

    config_path = tmp_path / "workspace" / "minimal-agent.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("{}\n", encoding="utf-8")

    test_app = FastAPI()
    test_app.include_router(optimize_routes.router)
    test_app.state.task_manager = TaskManager()
    test_app.state.ws_manager = _RecordingWsManager()
    test_app.state.observer = _RealObserver()
    test_app.state.optimizer = Optimizer(
        eval_runner=_PromptSensitiveEvalRunner(),
        memory=memory,
        require_statistical_significance=False,
    )
    test_app.state.deployer = deployer
    test_app.state.eval_runner = _PromptSensitiveEvalRunner()
    test_app.state.conversation_store = _FailureStore()
    test_app.state.optimization_memory = memory
    _add_task_status_route(test_app)

    client = TestClient(test_app)

    response = client.post(
        "/api/optimize/run",
        json={
            "window": 20,
            "force": True,
            "mode": "standard",
            "objective": "",
            "guardrails": [],
            "research_algorithm": "",
            "budget_cycles": 3,
            "budget_dollars": 2.0,
            "config_path": str(config_path),
        },
    )

    assert response.status_code == 202
    task_id = response.json()["task_id"]

    task_payload = None
    for _ in range(100):
        task_response = client.get(f"/api/tasks/{task_id}")
        assert task_response.status_code == 200
        task_payload = task_response.json()
        if task_payload["status"] == "completed":
            break
        time.sleep(0.02)

    assert task_payload is not None
    assert task_payload["status"] == "completed"
    assert task_payload["error"] is None
    assert task_payload["result"]["accepted"] is False
    assert task_payload["result"]["status_message"].startswith("REJECTED")
    assert task_payload["result"]["deploy_message"] is None
