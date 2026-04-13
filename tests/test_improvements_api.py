"""Tests for the Improvements API and lineage store."""

from __future__ import annotations

import tempfile
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import improvements as improvements_routes
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
