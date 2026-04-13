"""Tests for generated eval suite API routes."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from api.routes import eval as eval_routes
from api.routes import generated_evals as generated_eval_routes
from api.tasks import TaskManager
from evals.auto_generator import AutoEvalGenerator, GeneratedEvalSuiteStore
from evals.runner import EvalRunner


class _DummyWsManager:
    async def broadcast(self, payload):  # noqa: ANN001, ARG002
        return None


def _sample_agent_config() -> dict:
    return {
        "model": "gemini-2.0-flash",
        "routing": {
            "rules": [
                {
                    "specialist": "orders",
                    "keywords": ["order", "shipping", "tracking"],
                    "patterns": ["where is my", "track my"],
                },
                {
                    "specialist": "support",
                    "keywords": ["help", "refund", "issue"],
                    "patterns": ["how do I", "not working"],
                },
            ]
        },
        "prompts": {
            "root": "Route to the right specialist.",
            "orders": "Always confirm order details before making changes.",
            "support": "Never reveal internal policies. Refuse unsafe requests.",
        },
        "tools": {
            "orders_db": {"enabled": True, "timeout_ms": 5000},
            "faq": {"enabled": True, "timeout_ms": 3000},
        },
        "thresholds": {"max_latency_ms": 2500},
    }


def _sample_transcripts() -> list[dict]:
    return [
        {
            "id": "conv-1",
            "messages": [
                {"role": "user", "content": "Where is my order ORD-1002?"},
                {"role": "agent", "content": "Let me check that for you."},
            ],
            "success": True,
        },
        {
            "id": "conv-2",
            "messages": [
                {"role": "user", "content": "I need a refund for a broken charger."},
                {"role": "agent", "content": "I'll help with the refund."},
            ],
            "success": False,
        },
    ]


def _make_app(tmp_path: Path) -> FastAPI:
    def simple_agent(message: str, config: dict | None = None) -> dict:  # noqa: ARG001
        response = "I can help with that safely."
        specialist = "support"
        tool_calls = []
        if "order" in message.lower():
            response = "I checked your order and found the latest status."
            specialist = "orders"
            tool_calls = [{"tool": "orders_db"}]
        if "ignore your instructions" in message.lower():
            response = "I'm sorry, but I cannot help with bypassing verification."
            specialist = "support"
        return {
            "response": response,
            "specialist_used": specialist,
            "safety_violation": False,
            "latency_ms": 55.0,
            "token_count": 120,
            "tool_calls": tool_calls,
        }

    app = FastAPI()
    app.include_router(eval_routes.router)
    app.include_router(generated_eval_routes.router)
    app.state.task_manager = TaskManager()
    app.state.ws_manager = _DummyWsManager()
    app.state.eval_runner = EvalRunner(
        agent_fn=simple_agent,
        history_db_path=str(tmp_path / "eval_history.db"),
        cache_enabled=False,
    )
    app.state.generated_eval_store = GeneratedEvalSuiteStore(store_dir=str(tmp_path / "generated"))
    app.state.auto_eval_generator = AutoEvalGenerator(store=app.state.generated_eval_store)

    @app.get("/api/tasks/{task_id}")
    async def get_task_status(task_id: str) -> dict:
        task = app.state.task_manager.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
        return task.to_dict()

    return app


def _wait_for_task(client: TestClient, task_id: str) -> dict:
    for _ in range(20):
        payload = client.get(f"/api/tasks/{task_id}").json()
        if payload["status"] in {"completed", "failed"}:
            return payload
        time.sleep(0.05)
    raise AssertionError(f"Task {task_id} did not complete in time")


def test_generate_review_edit_accept_and_run_flow(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    client = TestClient(app)

    generate_response = client.post(
        "/api/evals/generate",
        json={
            "agent_name": "Support Copilot",
            "agent_config": _sample_agent_config(),
            "transcripts": _sample_transcripts(),
        },
    )

    assert generate_response.status_code == 202
    task_id = generate_response.json()["task_id"]

    completed_task = _wait_for_task(client, task_id)
    assert completed_task["status"] == "completed"
    suite_id = completed_task["result"]["suite_id"]

    list_response = client.get("/api/evals/generated")
    assert list_response.status_code == 200
    assert list_response.json()["count"] == 1
    assert list_response.json()["suites"][0]["suite_id"] == suite_id

    detail_response = client.get(f"/api/evals/generated/{suite_id}")
    assert detail_response.status_code == 200
    suite = detail_response.json()["suite"]
    assert suite["agent_name"] == "Support Copilot"
    assert suite["cases"]

    case_id = suite["cases"][0]["case_id"]
    patch_response = client.patch(
        f"/api/evals/generated/{suite_id}/cases/{case_id}",
        json={
            "user_message": "Can you check order ORD-1002 now?",
            "difficulty": "hard",
            "scoring_criteria": ["Route to orders", "Use orders_db"],
        },
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["suite"]["cases"][0]["difficulty"] == "hard"

    delete_response = client.delete(f"/api/evals/generated/{suite_id}/cases/{case_id}")
    assert delete_response.status_code == 200
    assert all(item["case_id"] != case_id for item in delete_response.json()["suite"]["cases"])

    accept_response = client.post(
        f"/api/evals/generated/{suite_id}/accept",
        json={"eval_cases_dir": str(tmp_path / "evals" / "cases")},
    )
    assert accept_response.status_code == 200
    accepted = accept_response.json()
    assert accepted["status"] == "accepted"
    assert Path(accepted["eval_file"]).exists()

    run_response = client.post("/api/eval/run", json={"generated_suite_id": suite_id})
    assert run_response.status_code == 202
    run_task_id = run_response.json()["task_id"]

    run_task = _wait_for_task(client, run_task_id)
    assert run_task["status"] == "completed"

    result_response = client.get(f"/api/eval/runs/{run_task_id}")
    assert result_response.status_code == 200
    result_payload = result_response.json()
    assert result_payload["run_id"]
    assert result_payload["total_cases"] >= 1
    assert result_payload["passed_cases"] >= 1


def test_eval_run_require_live_marks_config_for_strict_provider_execution(tmp_path: Path) -> None:
    """API live-only runs should pass a strict flag into the eval agent call."""

    seen_configs: list[dict | None] = []

    def recording_agent(message: str, config: dict | None = None) -> dict:  # noqa: ARG001
        seen_configs.append(config)
        return {
            "response": "I can explain that phone bill charge clearly.",
            "specialist_used": "support",
            "safety_violation": False,
            "latency_ms": 55.0,
            "token_count": 120,
            "tool_calls": [],
        }

    dataset_path = tmp_path / "strict-live-cases.yaml"
    dataset_path.write_text(
        """
cases:
  - id: live_001
    category: generated_build
    user_message: Why is there a device payment on my bill?
    expected_specialist: support
    expected_behavior: answer
    expected_keywords:
      - bill
""".strip(),
        encoding="utf-8",
    )

    app = _make_app(tmp_path)
    app.state.runtime_config = SimpleNamespace(optimizer=SimpleNamespace(use_mock=False))
    app.state.eval_runner = EvalRunner(
        agent_fn=recording_agent,
        history_db_path=str(tmp_path / "strict_eval_history.db"),
        cache_enabled=False,
    )
    client = TestClient(app)

    run_response = client.post(
        "/api/eval/run",
        json={"dataset_path": str(dataset_path), "require_live": True},
    )
    assert run_response.status_code == 202
    task = _wait_for_task(client, run_response.json()["task_id"])

    assert task["status"] == "completed"
    assert seen_configs
    assert seen_configs[0]["_eval_require_live"] is True


def test_legacy_eval_generation_routes_share_generated_suite_store(tmp_path: Path) -> None:
    """Legacy /api/eval endpoints should read and write the canonical suite store."""

    app = _make_app(tmp_path)
    client = TestClient(app)

    legacy_generate_response = client.post(
        "/api/eval/generate",
        json={
            "agent_name": "Legacy Support Copilot",
            "agent_config": _sample_agent_config(),
        },
    )

    assert legacy_generate_response.status_code == 201
    suite_id = legacy_generate_response.json()["suite_id"]

    canonical_detail_response = client.get(f"/api/evals/generated/{suite_id}")

    assert canonical_detail_response.status_code == 200
    assert canonical_detail_response.json()["suite"]["suite_id"] == suite_id
    assert canonical_detail_response.json()["suite"]["agent_name"] == "Legacy Support Copilot"
