"""Tests for preferences API endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import preferences as preferences_routes


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app(tmp_path: Path) -> FastAPI:
    """Minimal FastAPI app with the preferences router and an isolated SQLite DB."""
    import sqlite3

    test_app = FastAPI()
    test_app.include_router(preferences_routes.router)

    # Pre-create the SQLite store in tmp_path so tests are fully isolated
    db_path = str(tmp_path / "test_preferences.db")
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS preference_pairs (
            pair_id TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'human_review',
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    test_app.state.preference_store = conn

    return test_app


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# Submit Pair
# ---------------------------------------------------------------------------


class TestSubmitPair:
    def test_submit_pair_basic(self, client: TestClient) -> None:
        response = client.post(
            "/api/preferences/pairs",
            json={
                "input_text": "What is 2+2?",
                "chosen": "4",
                "rejected": "5",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["ok"] is True
        assert "pair_id" in data

    def test_submit_pair_with_source(self, client: TestClient) -> None:
        response = client.post(
            "/api/preferences/pairs",
            json={
                "input_text": "Explain gradient descent.",
                "chosen": "Gradient descent minimizes a function by iteratively moving in the direction of steepest descent.",
                "rejected": "It is just math.",
                "source": "ai_preference",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["ok"] is True

    def test_submit_pair_missing_chosen(self, client: TestClient) -> None:
        response = client.post(
            "/api/preferences/pairs",
            json={"input_text": "test", "rejected": "bad answer"},
        )
        assert response.status_code == 400

    def test_submit_pair_missing_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/api/preferences/pairs",
            json={"input_text": "test", "chosen": "good answer"},
        )
        assert response.status_code == 400

    def test_submit_pair_missing_input_text(self, client: TestClient) -> None:
        response = client.post(
            "/api/preferences/pairs",
            json={"chosen": "good answer", "rejected": "bad answer"},
        )
        assert response.status_code == 400

    def test_submit_pair_missing_all_fields(self, client: TestClient) -> None:
        response = client.post("/api/preferences/pairs", json={})
        assert response.status_code == 400

    def test_submit_pair_returns_unique_ids(self, client: TestClient) -> None:
        pair = {"input_text": "question", "chosen": "a", "rejected": "b"}
        r1 = client.post("/api/preferences/pairs", json=pair)
        r2 = client.post("/api/preferences/pairs", json=pair)
        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r1.json()["pair_id"] != r2.json()["pair_id"]


# ---------------------------------------------------------------------------
# List Pairs
# ---------------------------------------------------------------------------


class TestListPairs:
    def test_list_pairs_empty(self, client: TestClient) -> None:
        response = client.get("/api/preferences/pairs")
        assert response.status_code == 200
        data = response.json()
        assert "pairs" in data
        assert "count" in data
        assert data["count"] == 0

    def test_list_pairs_after_submit(self, client: TestClient) -> None:
        pair = {"input_text": "Hello?", "chosen": "Hi there!", "rejected": "What?"}
        client.post("/api/preferences/pairs", json=pair)
        client.post("/api/preferences/pairs", json={**pair, "input_text": "Bye?"})
        response = client.get("/api/preferences/pairs")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2
        assert len(data["pairs"]) == 2

    def test_list_pairs_filter_by_source(self, client: TestClient) -> None:
        client.post(
            "/api/preferences/pairs",
            json={"input_text": "q1", "chosen": "a", "rejected": "b", "source": "human_review"},
        )
        client.post(
            "/api/preferences/pairs",
            json={"input_text": "q2", "chosen": "a", "rejected": "b", "source": "ai_preference"},
        )
        response = client.get("/api/preferences/pairs?source=human_review")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["pairs"][0]["source"] == "human_review"

    def test_list_pairs_pagination(self, client: TestClient) -> None:
        pair_base = {"input_text": "q", "chosen": "c", "rejected": "r"}
        for i in range(5):
            client.post("/api/preferences/pairs", json={**pair_base, "input_text": f"q{i}"})
        response = client.get("/api/preferences/pairs?limit=3&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 3


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


class TestGetStats:
    def test_get_stats_empty(self, client: TestClient) -> None:
        response = client.get("/api/preferences/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_pairs" in data
        assert "by_source" in data
        assert data["total_pairs"] == 0

    def test_get_stats_after_submit(self, client: TestClient) -> None:
        client.post(
            "/api/preferences/pairs",
            json={"input_text": "q1", "chosen": "c", "rejected": "r", "source": "human_review"},
        )
        client.post(
            "/api/preferences/pairs",
            json={"input_text": "q2", "chosen": "c", "rejected": "r", "source": "human_review"},
        )
        client.post(
            "/api/preferences/pairs",
            json={"input_text": "q3", "chosen": "c", "rejected": "r", "source": "ai_preference"},
        )
        response = client.get("/api/preferences/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total_pairs"] == 3
        assert data["by_source"]["human_review"] == 2
        assert data["by_source"]["ai_preference"] == 1
