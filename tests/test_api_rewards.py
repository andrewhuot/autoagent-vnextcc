"""Tests for rewards API endpoints."""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import rewards as rewards_routes


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app() -> FastAPI:
    """Minimal FastAPI app with the rewards router and isolated state."""
    test_app = FastAPI()
    test_app.include_router(rewards_routes.router)
    return test_app


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# Reward CRUD
# ---------------------------------------------------------------------------


class TestCreateReward:
    def test_create_reward_verifiable(self, client: TestClient) -> None:
        response = client.post("/api/rewards", json={"name": "test_reward", "kind": "verifiable"})
        assert response.status_code == 201
        data = response.json()
        assert data["ok"] is True
        assert data["name"] == "test_reward"
        assert "version" in data
        assert "reward_id" in data

    def test_create_reward_preference(self, client: TestClient) -> None:
        response = client.post("/api/rewards", json={"name": "pref_reward", "kind": "preference"})
        assert response.status_code == 201
        data = response.json()
        assert data["ok"] is True
        assert data["name"] == "pref_reward"

    def test_create_reward_missing_name(self, client: TestClient) -> None:
        response = client.post("/api/rewards", json={"kind": "verifiable"})
        assert response.status_code == 400

    def test_create_reward_missing_kind(self, client: TestClient) -> None:
        response = client.post("/api/rewards", json={"name": "no_kind_reward"})
        assert response.status_code == 400

    def test_create_reward_missing_both_fields(self, client: TestClient) -> None:
        response = client.post("/api/rewards", json={})
        assert response.status_code == 400


class TestListRewards:
    def test_list_rewards_returns_valid_structure(self, client: TestClient) -> None:
        response = client.get("/api/rewards")
        assert response.status_code == 200
        data = response.json()
        assert "rewards" in data
        assert "count" in data
        assert data["count"] >= 0

    def test_list_rewards_after_create(self, client: TestClient) -> None:
        import uuid
        suffix = uuid.uuid4().hex[:8]
        # Get baseline count
        baseline = client.get("/api/rewards").json()["count"]
        client.post("/api/rewards", json={"name": f"r1_list_{suffix}", "kind": "verifiable"})
        client.post("/api/rewards", json={"name": f"r2_list_{suffix}", "kind": "preference"})
        response = client.get("/api/rewards")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] >= baseline + 2

    def test_list_rewards_filter_by_kind(self, client: TestClient) -> None:
        client.post("/api/rewards", json={"name": "v_reward", "kind": "verifiable"})
        client.post("/api/rewards", json={"name": "p_reward", "kind": "preference"})
        response = client.get("/api/rewards?kind=verifiable")
        assert response.status_code == 200
        data = response.json()
        assert all(r["kind"] == "verifiable" for r in data["rewards"])


class TestGetReward:
    def test_get_reward(self, client: TestClient) -> None:
        client.post("/api/rewards", json={"name": "get_test", "kind": "preference"})
        response = client.get("/api/rewards/get_test")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "get_test"
        assert data["kind"] == "preference"

    def test_get_reward_not_found(self, client: TestClient) -> None:
        response = client.get("/api/rewards/nonexistent_reward_xyz")
        assert response.status_code == 404

    def test_get_reward_specific_version(self, client: TestClient) -> None:
        client.post("/api/rewards", json={"name": "versioned_reward", "kind": "verifiable"})
        response = client.get("/api/rewards/versioned_reward?version=1")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "versioned_reward"


# ---------------------------------------------------------------------------
# Reward Test
# ---------------------------------------------------------------------------


class TestRewardTest:
    def test_test_reward(self, client: TestClient) -> None:
        client.post("/api/rewards", json={"name": "testable_reward", "kind": "verifiable"})
        response = client.post(
            "/api/rewards/testable_reward/test",
            json={"trace_id": "trace-123", "output": "agent response"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "reward" in data
        assert "test_input" in data

    def test_test_reward_not_found(self, client: TestClient) -> None:
        response = client.post(
            "/api/rewards/nonexistent_reward/test",
            json={"trace_id": "trace-abc"},
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Hard Gates
# ---------------------------------------------------------------------------


class TestHardGates:
    def test_list_hard_gates(self, client: TestClient) -> None:
        response = client.get("/api/rewards/hard-gates/list")
        assert response.status_code == 200
        data = response.json()
        assert "hard_gates" in data
        assert "count" in data


# ---------------------------------------------------------------------------
# Challenge Suite
# ---------------------------------------------------------------------------


class TestChallengeSuite:
    def test_run_challenge_suite_all(self, client: TestClient) -> None:
        response = client.post("/api/rewards/challenge/run", json={})
        assert response.status_code == 200
        data = response.json()
        assert "reports" in data
        assert "count" in data
        assert isinstance(data["reports"], list)

    def test_run_challenge_suite_specific(self, client: TestClient) -> None:
        # Run with nonexistent suite name — expect 404
        response = client.post("/api/rewards/challenge/run", json={"suite": "nonexistent_suite_xyz"})
        assert response.status_code == 404
