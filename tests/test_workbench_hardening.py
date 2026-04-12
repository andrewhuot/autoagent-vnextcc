"""Regression tests for Workbench P0 lifecycle hardening."""

from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.workbench import router
from builder.workbench import WorkbenchService, WorkbenchStore
from builder.workbench_agent import BuildRequest
from builder.workbench_plan import PlanTask


def _make_client(tmp_path: Path) -> TestClient:
    """Create a Workbench API client backed by isolated JSON state."""
    app = FastAPI()
    app.include_router(router)
    app.state.workbench_store = WorkbenchStore(tmp_path / "workbench.json")
    return TestClient(app)


def _seed_running_run(project: dict[str, Any], *, run_id: str = "run-test") -> None:
    """Attach an active running run to a project fixture."""
    project.setdefault("runs", {})[run_id] = {
        "run_id": run_id,
        "project_id": project["project_id"],
        "brief": "Build a hardened agent.",
        "target": "portable",
        "environment": "draft",
        "status": "running",
        "phase": "executing",
        "started_version": int(project.get("version") or 1),
        "completed_version": None,
        "created_at": "2026-04-12T00:00:00Z",
        "updated_at": "2026-04-12T00:00:00Z",
        "completed_at": None,
        "error": None,
        "events": [],
        "messages": [],
        "validation": None,
        "presentation": None,
    }
    project["active_run_id"] = run_id
    project["build_status"] = "running"


def test_cancel_run_endpoint_marks_active_run_cancelled(tmp_path: Path) -> None:
    """Operators can cancel an active run durably through the API."""
    client = _make_client(tmp_path)
    created = client.post(
        "/api/workbench/projects",
        json={"brief": "Build an airline support agent."},
    )
    project_id = created.json()["project"]["project_id"]

    store = WorkbenchStore(tmp_path / "workbench.json")
    project = store.get_project(project_id)
    assert project is not None
    _seed_running_run(project, run_id="run-cancel-me")
    store.save_project(project)

    response = client.post(
        f"/api/workbench/projects/{project_id}/runs/run-cancel-me/cancel",
        json={"reason": "operator requested stop"},
    )

    assert response.status_code == 200
    payload = response.json()
    run = payload["run"]
    assert run["status"] == "cancelled"
    assert run["phase"] == "terminal"
    assert run["cancel_reason"] == "operator requested stop"
    assert run["completed_at"] is not None
    assert run["events"][-1]["event"] == "run.cancelled"

    snapshot = client.get(f"/api/workbench/projects/{project_id}/plan").json()
    assert snapshot["build_status"] == "cancelled"
    assert snapshot["active_run"]["status"] == "cancelled"


def test_get_plan_snapshot_recovers_stale_active_run(tmp_path: Path) -> None:
    """Hydration should not pretend an old in-flight run is still running."""
    store = WorkbenchStore(tmp_path / "workbench.json")
    service = WorkbenchService(store)
    project = store.create_project(brief="Build a refund support agent.")
    _seed_running_run(project, run_id="run-stale")
    project["runs"]["run-stale"]["updated_at"] = "2026-01-01T00:00:00Z"
    store.save_project(project)

    snapshot = service.get_plan_snapshot(project_id=project["project_id"])

    assert snapshot["build_status"] == "failed"
    assert snapshot["active_run"]["status"] == "failed"
    assert snapshot["active_run"]["failure_reason"] == "stale_interrupted"
    assert snapshot["active_run"]["events"][-1]["event"] == "run.recovered"


@pytest.mark.asyncio
async def test_run_build_stream_fails_when_token_budget_exceeded(tmp_path: Path) -> None:
    """Server-side token budgets terminate a run when harness metrics exceed limits."""
    store = WorkbenchStore(tmp_path / "workbench.json")
    service = WorkbenchService(store)

    class BudgetAgent:
        """Small streaming agent that emits metrics over the requested token cap."""

        async def run(
            self,
            request: BuildRequest,
            project: dict[str, Any],
        ) -> AsyncIterator[dict[str, Any]]:
            plan = PlanTask(id="task-root", title="Budget plan")
            yield {"event": "plan.ready", "data": {"plan": plan.to_dict()}}
            yield {
                "event": "harness.metrics",
                "data": {
                    "steps_completed": 1,
                    "total_steps": 1,
                    "tokens_used": 25,
                    "cost_usd": 0.001,
                    "elapsed_ms": 5,
                    "current_phase": "executing",
                },
            }
            yield {
                "event": "build.completed",
                "data": {"project_id": request.project_id, "operations": []},
            }

    stream = await service.run_build_stream(
        project_id=None,
        brief="Build a budgeted agent.",
        agent=BudgetAgent(),
        max_tokens=10,
    )
    events = [event async for event in stream]

    assert events[-1]["event"] == "run.failed"
    assert events[-1]["data"]["failure_reason"] == "budget_exceeded"
    assert events[-1]["data"]["budget"]["exceeded"] == "max_tokens"
    assert events[-1]["data"]["run"]["budget"]["usage"]["tokens"] == 25
