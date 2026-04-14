"""Tests for context profile and assembly-preview workflows."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import context as context_routes
from context.engineering import (
    CONTEXT_PROFILE_PRESETS,
    ContextProfile,
    build_context_preview,
)


def _sample_config() -> dict:
    return {
        "model": "claude-sonnet-4-5",
        "prompts": {
            "root": (
                "<role>Support router.</role>\n"
                "<instructions>Route customers to the right specialist.</instructions>\n"
                "<examples>Example: Where is my order? Route to orders.</examples>"
            ),
            "orders": "Verify order context before answering.",
        },
        "tools": {
            "orders_db": {"enabled": True, "description": "Lookup orders by order number."},
            "catalog": {"enabled": False, "description": "Search products."},
        },
        "routing": {"rules": [{"specialist": "orders", "keywords": ["order"]}]},
        "context_caching": {"enabled": False},
        "compaction": {"enabled": False},
        "memory_policy": {"preload": True, "max_entries": 100},
    }


def test_build_context_preview_prioritizes_traceable_context_components() -> None:
    preview = build_context_preview(
        _sample_config(),
        profile=CONTEXT_PROFILE_PRESETS["balanced"],
        project_memory_text="Known good pattern: ask one clarifying question before handoff.",
    )

    component_ids = [component.component_id for component in preview.components]

    assert preview.profile_name == "balanced"
    assert preview.status in {"healthy", "watch", "over_budget"}
    assert preview.total_tokens > 0
    assert "instructions" in component_ids
    assert "tool_runtime" in component_ids
    assert "project_memory" in component_ids
    assert "context_strategy" in component_ids
    assert preview.assembly_order[0] == "instructions"
    assert any(item.category == "instruction_hierarchy" for item in preview.diagnostics)


def test_build_context_preview_flags_over_budget_profiles() -> None:
    profile = ContextProfile(
        name="tiny",
        label="Tiny",
        description="Tiny test profile.",
        token_budget=80,
        target_utilization=0.5,
        include_project_memory=True,
        include_tool_catalog=True,
        include_examples=True,
        include_routing=True,
        include_recent_failures=True,
        include_retrieval_plan=True,
        compaction_trigger=0.6,
        retention_ratio=0.4,
        pro_mode=True,
    )

    preview = build_context_preview(
        _sample_config(),
        profile=profile,
        project_memory_text="Memory note. " * 200,
    )

    assert preview.status == "over_budget"
    assert preview.utilization_ratio > 1.0
    assert any(item.severity == "critical" and item.category == "budget" for item in preview.diagnostics)
    assert any("Use the lean profile" in item.recommendation for item in preview.diagnostics)


def test_context_profiles_api_returns_presets() -> None:
    app = FastAPI()
    app.include_router(context_routes.router)

    response = TestClient(app).get("/api/context/profiles")

    assert response.status_code == 200
    payload = response.json()
    assert [profile["name"] for profile in payload["profiles"]] == ["lean", "balanced", "deep"]
    assert payload["default_profile"] == "balanced"


def test_context_preview_api_accepts_inline_config() -> None:
    app = FastAPI()
    app.include_router(context_routes.router)

    response = TestClient(app).post(
        "/api/context/preview",
        json={
            "profile": "lean",
            "agent_config": _sample_config(),
            "project_memory": "Known good pattern: verify order ID.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["profile_name"] == "lean"
    assert payload["total_tokens"] > 0
    assert any(component["component_id"] == "instructions" for component in payload["components"])
    assert any(item["category"] == "instruction_hierarchy" for item in payload["diagnostics"])
