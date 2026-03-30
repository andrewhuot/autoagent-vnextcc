"""Tests for the setup overview API route."""

from __future__ import annotations

from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import setup as setup_routes
from cli.workspace import AutoAgentWorkspace


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    workspace = AutoAgentWorkspace.create(
        tmp_path,
        name="Demo Workspace",
        template="support",
        agent_name="Support Agent",
        platform="adk",
    )
    workspace.ensure_structure()
    workspace.save_metadata()
    monkeypatch.chdir(tmp_path)

    app = FastAPI()
    app.include_router(setup_routes.router)
    return TestClient(app)


def test_setup_overview_reports_workspace_and_mcp_state(client: TestClient) -> None:
    response = client.get("/api/setup/overview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["workspace"]["found"] is True
    assert payload["workspace"]["label"] == "Demo Workspace"
    assert "doctor" in payload
    assert "mcp_clients" in payload
    assert payload["recommended_commands"][0] == "autoagent init"
