"""Tests for policy optimization API endpoints."""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import policy_opt as policy_opt_routes


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app() -> FastAPI:
    """Minimal FastAPI app with the policy optimization router and isolated state."""
    test_app = FastAPI()
    test_app.include_router(policy_opt_routes.router)
    return test_app


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------


class TestListPolicies:
    def test_list_policies_empty(self, client: TestClient) -> None:
        response = client.get("/api/rl/policies")
        assert response.status_code == 200
        data = response.json()
        assert "policies" in data
        assert "count" in data
        assert data["count"] == 0

    def test_list_policies_filter_by_status(self, client: TestClient) -> None:
        response = client.get("/api/rl/policies?status=active")
        assert response.status_code == 200
        data = response.json()
        assert "policies" in data

    def test_list_policies_filter_by_type(self, client: TestClient) -> None:
        response = client.get("/api/rl/policies?policy_type=rlvr")
        assert response.status_code == 200
        data = response.json()
        assert "policies" in data


class TestGetPolicy:
    def test_get_policy_not_found(self, client: TestClient) -> None:
        response = client.get("/api/rl/policies/nonexistent")
        assert response.status_code == 404

    def test_get_policy_not_found_random_id(self, client: TestClient) -> None:
        response = client.get("/api/rl/policies/policy-does-not-exist-abc123")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Training Jobs
# ---------------------------------------------------------------------------


class TestListJobs:
    def test_list_jobs_empty(self, client: TestClient) -> None:
        response = client.get("/api/rl/jobs")
        assert response.status_code == 200
        data = response.json()
        assert "jobs" in data
        assert "count" in data
        assert data["count"] == 0

    def test_list_jobs_filter_by_status(self, client: TestClient) -> None:
        response = client.get("/api/rl/jobs?status=pending")
        assert response.status_code == 200
        data = response.json()
        assert "jobs" in data


class TestGetJob:
    def test_get_job_not_found(self, client: TestClient) -> None:
        response = client.get("/api/rl/jobs/nonexistent")
        assert response.status_code == 404

    def test_get_job_not_found_random_id(self, client: TestClient) -> None:
        response = client.get("/api/rl/jobs/job-does-not-exist-xyz999")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Train endpoint — validation
# ---------------------------------------------------------------------------


class TestStartTraining:
    def test_train_missing_all_required_fields(self, client: TestClient) -> None:
        response = client.post("/api/rl/train", json={})
        assert response.status_code == 400

    def test_train_missing_backend_and_dataset(self, client: TestClient) -> None:
        response = client.post("/api/rl/train", json={"mode": "control"})
        assert response.status_code == 400

    def test_train_missing_dataset_path(self, client: TestClient) -> None:
        response = client.post("/api/rl/train", json={"mode": "rlvr", "backend": "openai_rft"})
        assert response.status_code == 400

    def test_train_missing_mode(self, client: TestClient) -> None:
        response = client.post(
            "/api/rl/train",
            json={"backend": "openai_rft", "dataset_path": "/tmp/data.jsonl"},
        )
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# Evaluate endpoint — validation
# ---------------------------------------------------------------------------


class TestEvaluatePolicy:
    def test_evaluate_missing_policy_id(self, client: TestClient) -> None:
        response = client.post("/api/rl/evaluate", json={})
        assert response.status_code == 400

    def test_evaluate_nonexistent_policy(self, client: TestClient) -> None:
        response = client.post("/api/rl/evaluate", json={"policy_id": "nonexistent-policy-id"})
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Canary / Promote / Rollback — validation
# ---------------------------------------------------------------------------


class TestCanaryPromoteRollback:
    def test_canary_missing_policy_id(self, client: TestClient) -> None:
        response = client.post("/api/rl/canary", json={})
        assert response.status_code == 400

    def test_canary_nonexistent_policy(self, client: TestClient) -> None:
        response = client.post("/api/rl/canary", json={"policy_id": "nonexistent-xyz"})
        assert response.status_code == 404

    def test_promote_missing_policy_id(self, client: TestClient) -> None:
        response = client.post("/api/rl/promote", json={})
        assert response.status_code == 400

    def test_rollback_missing_policy_id(self, client: TestClient) -> None:
        response = client.post("/api/rl/rollback", json={})
        assert response.status_code == 400

    def test_rollback_nonexistent_policy(self, client: TestClient) -> None:
        response = client.post("/api/rl/rollback", json={"policy_id": "nonexistent-xyz"})
        assert response.status_code == 404
