"""Tests for optimization surface coverage inventory."""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import optimize as optimize_routes
from optimizer.surface_inventory import build_surface_inventory


def test_build_surface_inventory_exposes_component_gaps() -> None:
    """Inventory should expose broad declared surfaces and the current reachability gaps."""
    inventory = build_surface_inventory()

    summary = inventory["summary"]
    surfaces = {item["surface_id"]: item for item in inventory["surfaces"]}

    assert summary["total_surfaces"] >= 10
    assert summary["support_level_counts"]["full"] >= 2
    assert summary["support_level_counts"]["partial"] >= 1
    assert summary["support_level_counts"]["nominal"] >= 1
    assert summary["surfaces_missing_agent_config"] >= 1
    assert summary["surfaces_missing_adaptive_loop"] == 0

    instructions = surfaces["instructions"]
    assert instructions["support_level"] == "full"
    assert instructions["has_default_operator"] is True
    assert instructions["reachable_from_adaptive_loop"] is True
    assert instructions["represented_in_agent_config"] is True

    tool_runtime = surfaces["tool_runtime_config"]
    assert tool_runtime["support_level"] == "partial"
    assert tool_runtime["represented_in_adk_import"] is True
    assert tool_runtime["represented_in_connect_import"] is True

    callbacks = surfaces["callbacks"]
    assert callbacks["support_level"] == "nominal"
    assert callbacks["has_default_operator"] is True
    assert callbacks["represented_in_agent_config"] is False
    assert callbacks["reachable_from_opportunity_generation"] is True

    handoffs = surfaces["handoff_artifacts"]
    assert handoffs["support_level"] == "nominal"
    assert handoffs["has_default_operator"] is True
    assert handoffs["represented_in_agent_config"] is False
    assert handoffs["reachable_from_adaptive_loop"] is True

    workflow = surfaces["workflow_topology"]
    assert workflow["support_level"] == "nominal"
    assert workflow["has_default_operator"] is True
    assert workflow["has_experimental_operator"] is True
    assert workflow["reachable_from_adaptive_loop"] is True

    compaction = surfaces["compaction"]
    assert compaction["support_level"] == "none"
    assert compaction["represented_in_agent_config"] is True
    assert compaction["has_default_operator"] is False


def test_optimize_surfaces_route_returns_inventory() -> None:
    """The optimize surfaces endpoint should expose the inventory for UI and coding agents."""
    app = FastAPI()
    app.include_router(optimize_routes.router)
    client = TestClient(app)

    response = client.get("/api/optimize/surfaces")

    assert response.status_code == 200
    payload = response.json()
    assert "summary" in payload
    assert "surfaces" in payload
    assert "support_level_counts" in payload["summary"]
    assert any(item["surface_id"] == "instructions" for item in payload["surfaces"])
    assert all("support_level" in item for item in payload["surfaces"])
