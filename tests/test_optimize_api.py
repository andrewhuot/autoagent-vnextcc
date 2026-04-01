"""Tests for optimize API route behavior."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import optimize as optimize_routes
from api.tasks import TaskManager
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
    return test_app


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


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
