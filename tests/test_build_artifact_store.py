"""Tests for the shared build artifact store and API surface."""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.build_artifact_store import BuildArtifactStore, StateStoreCorruptionError
from shared.contracts import BuildArtifact

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.intelligence import router as intelligence_router


def _build_artifact(
    artifact_id: str,
    *,
    created_at: str,
    selector: str = "latest",
    prompt_used: str = "Build a support agent",
) -> BuildArtifact:
    return BuildArtifact(
        id=artifact_id,
        created_at=created_at,
        updated_at=created_at,
        source="prompt",
        status="complete",
        config_yaml="metadata:\n  agent_name: Support Agent\n",
        prompt_used=prompt_used,
        selector=selector,
        metadata={
            "title": "Support Agent",
            "summary": "Generated from a prompt.",
            "connectors": ["Shopify"],
            "intents": [{"name": "order_status"}],
            "tools": [],
            "guardrails": ["no_pii"],
            "skills": [],
        },
    )


def test_build_artifact_store_persists_latest_and_recent_order(tmp_path: Path) -> None:
    store = BuildArtifactStore(
        path=tmp_path / ".agentlab" / "build_artifacts.json",
        latest_path=tmp_path / ".agentlab" / "build_artifact_latest.json",
    )

    older = _build_artifact("build-001", created_at="2026-03-29T12:00:00Z")
    newer = _build_artifact("build-002", created_at="2026-03-29T12:05:00Z")

    store.save_latest(older)
    store.save_latest(newer)

    latest = store.get_latest()
    assert latest is not None
    assert latest["id"] == "build-002"
    assert store.get_by_id("build-001") is not None
    assert [artifact["id"] for artifact in store.list_recent()] == ["build-002", "build-001"]

    legacy_payload = store.get_latest_legacy()
    assert legacy_payload is not None
    assert legacy_payload["artifact_id"] == "build-002"
    assert legacy_payload["source_prompt"] == "Build a support agent"
    assert (tmp_path / ".agentlab" / "build_artifact_latest.json").exists()


def test_build_artifact_api_lists_and_fetches_saved_records(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(intelligence_router)

    store = BuildArtifactStore(
        path=tmp_path / ".agentlab" / "build_artifacts.json",
        latest_path=tmp_path / ".agentlab" / "build_artifact_latest.json",
    )
    saved = store.save_latest(_build_artifact("build-api-001", created_at="2026-03-29T14:00:00Z"))
    app.state.build_artifact_store = store

    client = TestClient(app)

    list_response = client.get("/api/intelligence/build-artifacts")
    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload["artifacts"][0]["id"] == saved["id"]

    detail_response = client.get(f"/api/intelligence/build-artifacts/{saved['id']}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["metadata"]["title"] == "Support Agent"
    assert detail["prompt_used"] == "Build a support agent"


def test_build_artifact_store_raises_on_corrupt_primary_store(tmp_path: Path) -> None:
    """Corrupt shared build state should fail closed instead of silently resetting latest selection."""
    path = tmp_path / ".agentlab" / "build_artifacts.json"
    latest_path = tmp_path / ".agentlab" / "build_artifact_latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"latest_id": "broken"', encoding="utf-8")

    store = BuildArtifactStore(path=path, latest_path=latest_path)

    with pytest.raises(StateStoreCorruptionError, match="build artifact store"):
        store.get_latest()
