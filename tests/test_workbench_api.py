"""Tests for the Agent Builder Workbench canonical model API."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.workbench import router
from builder.workbench import WorkbenchStore


def _make_client(tmp_path: Path) -> TestClient:
    """Create a workbench API client backed by isolated JSON state."""
    app = FastAPI()
    app.include_router(router)
    app.state.workbench_store = WorkbenchStore(tmp_path / "workbench.json")
    return TestClient(app)


def test_plan_returns_structured_operations_without_mutating_canonical_project(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    create = client.post(
        "/api/workbench/projects",
        json={"brief": "Build an airline support agent for booking changes and cancellations."},
    )
    assert create.status_code == 201
    project = create.json()

    plan = client.post(
        "/api/workbench/plan",
        json={
            "project_id": project["project"]["project_id"],
            "message": "Add a flight status tool and a guardrail that never reveals internal codes.",
            "mode": "plan",
        },
    )

    assert plan.status_code == 200
    plan_payload = plan.json()
    assert plan_payload["plan"]["status"] == "planned"
    assert [operation["operation"] for operation in plan_payload["plan"]["operations"]] == [
        "add_tool",
        "add_guardrail",
    ]
    assert plan_payload["plan"]["requires_approval"] is True
    assert plan_payload["project"]["version"] == 1
    assert len(plan_payload["project"]["model"]["tools"]) == 0
    assert len(plan_payload["project"]["compatibility"]) >= 1


def test_project_creation_preserves_build_handoff_model_hint(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    create = client.post(
        "/api/workbench/projects",
        json={
            "brief": (
                "Build a Verizon-like phone-company support agent that explains wireless bills. "
                "Continue from the saved Build config at configs/v005.yaml. "
                "Preserve the saved Build model gemini-2.5-pro."
            )
        },
    )

    assert create.status_code == 201
    project = create.json()["project"]
    root_agent = project["model"]["agents"][0]
    assert root_agent["model"] == "gemini-2.5-pro"
    assert root_agent["name"] == "Phone Billing Support Agent"


def test_apply_mutates_canonical_model_creates_version_and_runs_validation(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    create = client.post(
        "/api/workbench/projects",
        json={"brief": "Build an airline support agent for booking changes and cancellations."},
    )
    project_id = create.json()["project"]["project_id"]
    plan_id = client.post(
        "/api/workbench/plan",
        json={
            "project_id": project_id,
            "message": (
                "Add a flight status tool, add an after response callback, "
                "add a guardrail for PII, and add an eval for delayed flights."
            ),
        },
    ).json()["plan"]["plan_id"]

    applied = client.post("/api/workbench/apply", json={"project_id": project_id, "plan_id": plan_id})

    assert applied.status_code == 200
    payload = applied.json()
    project = payload["project"]
    assert project["version"] == 2
    assert project["last_test"]["status"] == "passed"
    assert project["last_test"]["checks"][0]["name"] == "canonical_model_present"
    assert any(tool["name"] == "flight_status_lookup" for tool in project["model"]["tools"])
    assert any(callback["hook"] == "after_response" for callback in project["model"]["callbacks"])
    assert any("PII" in guardrail["name"] for guardrail in project["model"]["guardrails"])
    assert any(suite["name"] == "Delayed Flights" for suite in project["model"]["eval_suites"])
    assert payload["exports"]["adk"]["files"]["agent.py"]
    assert payload["exports"]["cx"]["files"]["agent.json"]
    assert "flight_status_lookup" in payload["exports"]["adk"]["files"]["tools.py"]
    assert payload["activity"][0]["kind"] == "test"
    assert payload["activity"][1]["kind"] == "apply"


def test_rollback_restores_prior_version_and_records_activity(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    create = client.post(
        "/api/workbench/projects",
        json={"brief": "Build an airline support agent."},
    )
    project_id = create.json()["project"]["project_id"]
    plan_id = client.post(
        "/api/workbench/plan",
        json={"project_id": project_id, "message": "Add a flight status tool."},
    ).json()["plan"]["plan_id"]
    client.post("/api/workbench/apply", json={"project_id": project_id, "plan_id": plan_id})

    rollback = client.post(
        "/api/workbench/rollback",
        json={"project_id": project_id, "version": 1},
    )

    assert rollback.status_code == 200
    payload = rollback.json()
    assert payload["project"]["version"] == 3
    assert payload["project"]["rolled_back_from_version"] == 2
    assert payload["project"]["rolled_back_to_version"] == 1
    assert payload["project"]["model"]["tools"] == []
    assert payload["activity"][0]["kind"] == "rollback"


def test_invalid_target_is_reported_in_compatibility_diagnostics(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    project_id = client.post(
        "/api/workbench/projects",
        json={"brief": "Build an agent."},
    ).json()["project"]["project_id"]
    plan_id = client.post(
        "/api/workbench/plan",
        json={
            "project_id": project_id,
            "message": "Add a local shell tool that runs a terminal command.",
            "target": "cx",
        },
    ).json()["plan"]["plan_id"]

    applied = client.post("/api/workbench/apply", json={"project_id": project_id, "plan_id": plan_id})

    assert applied.status_code == 200
    diagnostics = applied.json()["project"]["compatibility"]
    shell_tool = next(item for item in diagnostics if item["object_id"].endswith("local_shell"))
    assert shell_tool["status"] == "invalid"
    assert shell_tool["target"] == "cx"
    assert "not exportable to CX" in shell_tool["reason"]
