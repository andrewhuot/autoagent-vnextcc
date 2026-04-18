"""Tests for the guidance API route contracts consumed by the web UI."""

from __future__ import annotations

from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import guidance as guidance_routes


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Build a FastAPI app with only the guidance routes registered.

    We point ``discover_workspace`` at a throwaway directory so the routes
    behave as if the server started outside a real AgentLab workspace —
    the guidance engine then exercises the ``workspace_valid=False`` path,
    which is deterministic and doesn't touch disk state owned by other
    tests.
    """
    app = FastAPI()
    app.include_router(guidance_routes.router)
    monkeypatch.setattr(guidance_routes, "discover_workspace", lambda *a, **k: None)
    return TestClient(app)


def test_list_guidance_returns_payload_shape(client: TestClient) -> None:
    response = client.get("/api/guidance")
    assert response.status_code == 200
    data = response.json()
    assert "workspace_valid" in data
    assert "suggestions" in data
    assert data["workspace_valid"] is False
    # Broken-workspace rule should fire and surface a blocker.
    ids = {s["id"] for s in data["suggestions"]}
    assert "broken-workspace" in ids


def test_include_suppressed_bypasses_cooldown(client: TestClient) -> None:
    """With ``include_suppressed=true`` we always see all active rules."""
    response = client.get("/api/guidance?include_suppressed=true")
    assert response.status_code == 200
    assert len(response.json()["suggestions"]) >= 1


def test_dismiss_requires_workspace(client: TestClient) -> None:
    response = client.post(
        "/api/guidance/dismiss", json={"suggestion_id": "x"}
    )
    assert response.status_code == 400


def test_accept_requires_workspace(client: TestClient) -> None:
    response = client.post(
        "/api/guidance/accept", json={"suggestion_id": "x"}
    )
    assert response.status_code == 400
