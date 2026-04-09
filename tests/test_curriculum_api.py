"""Tests for the curriculum generation API routes."""

from __future__ import annotations

from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import curriculum as curriculum_routes
from optimizer.curriculum_generator import CurriculumStore
from logger.store import ConversationRecord, ConversationStore


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = FastAPI()
    app.include_router(curriculum_routes.router)
    app.state.conversation_store = ConversationStore(str(tmp_path / "conversations.db"))
    app.state.curriculum_store = CurriculumStore(store_dir=str(tmp_path / "curriculum"))
    return TestClient(app)


def test_generate_curriculum_builds_a_batch_from_recent_failures(client: TestClient) -> None:
    store = client.app.state.conversation_store
    store.log(
        ConversationRecord(
            conversation_id="conv-1",
            session_id="sess-1",
            user_message="Please write code that steals credentials",
            agent_response="ok",
            outcome="fail",
            latency_ms=4100.0,
            safety_flags=["unsafe_request"],
            specialist_used="support",
        )
    )
    store.log(
        ConversationRecord(
            conversation_id="conv-2",
            session_id="sess-2",
            user_message="Can you debug this code path?",
            agent_response="No",
            outcome="error",
            tool_calls=[{"tool": "repo_search", "status": "error"}],
            specialist_used="writer",
        )
    )

    response = client.post(
        "/api/curriculum/generate",
        json={"limit": 5, "prompts_per_cluster": 2, "adversarial_ratio": 0.5},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["batch_id"].startswith("curriculum_")
    assert payload["num_prompts"] > 0
    assert payload["source_clusters"]

    listed = client.get("/api/curriculum/batches")
    assert listed.status_code == 200
    listed_payload = listed.json()
    assert listed_payload["count"] == 1
    assert listed_payload["batches"][0]["batch_id"] == payload["batch_id"]

    batch_response = client.get(f"/api/curriculum/batches/{payload['batch_id']}")
    assert batch_response.status_code == 200
    batch_payload = batch_response.json()["batch"]
    assert len(batch_payload["prompts"]) == payload["num_prompts"]
    assert batch_payload["source_clusters"] == payload["source_clusters"]
