"""Tests for the Agent Library API."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import agents as agents_routes
from cli.workspace import AgentLabWorkspace
from deployer import Deployer
from deployer.versioning import ConfigVersionManager
from logger.store import ConversationStore
from shared.build_artifact_store import BuildArtifactStore


def _seed_workspace(root: Path) -> ConfigVersionManager:
    workspace = AgentLabWorkspace.create(
        root=root,
        name=root.name,
        template="customer-support",
        agent_name="Workspace Agent",
        platform="Google ADK",
    )
    workspace.ensure_structure()
    workspace.runtime_config_path.write_text(
        yaml.safe_dump(
            {
                "optimizer": {
                    "use_mock": False,
                    "models": [
                        {
                            "provider": "openai",
                            "model": "gpt-4o-mini",
                            "role": "default",
                            "api_key_env": "OPENAI_API_KEY",
                        }
                    ],
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    store = ConversationStore(db_path=str(root / "conversations.db"))
    deployer = Deployer(configs_dir=str(root / "configs"), store=store)
    vm = deployer.version_manager
    base = vm.save_version(
        {"model": "gpt-4o-mini", "agent_library": {"name": "Workspace Agent", "source": "connected"}},
        scores={"composite": 0.7},
        status="active",
    )
    workspace.set_active_config(base.version, filename=base.filename)

    built = vm.save_version(
        {
            "model": "gpt-5.4-mini",
            "journey_build": {
                "agent_name": "Refund Wizard",
                "model": "gpt-5.4-mini",
                "metadata": {"agent_name": "Refund Wizard"},
            },
        },
        scores={"composite": 0.82},
        status="candidate",
    )

    artifact_store = BuildArtifactStore(
        path=root / ".agentlab" / "build_artifacts.json",
        latest_path=root / ".agentlab" / "build_artifact_latest.json",
    )
    artifact_store.save_latest(
        {
            "id": "build-refund-wizard",
            "created_at": "2026-04-01T10:00:00Z",
            "updated_at": "2026-04-01T10:00:00Z",
            "source": "prompt",
            "status": "complete",
            "config_yaml": "model: gpt-5.4-mini\n",
            "starter_config_path": str(root / "configs" / built.filename),
            "selector": "latest",
            "metadata": {"title": "Refund Wizard"},
        }
    )
    return vm


@pytest.fixture()
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.chdir(tmp_path)
    vm = _seed_workspace(tmp_path)

    test_app = FastAPI()
    test_app.include_router(agents_routes.router)
    test_app.state.version_manager = vm
    test_app.state.build_artifact_store = BuildArtifactStore(
        path=tmp_path / ".agentlab" / "build_artifacts.json",
        latest_path=tmp_path / ".agentlab" / "build_artifact_latest.json",
    )
    return test_app


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_list_agents_surfaces_workspace_configs_as_agent_records(client: TestClient) -> None:
    response = client.get("/api/agents")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    names = {agent["name"]: agent for agent in payload["agents"]}
    assert names["Workspace Agent"]["source"] == "connected"
    assert names["Refund Wizard"]["source"] == "built"
    assert names["Refund Wizard"]["config_path"].endswith("v002.yaml")


def test_get_agent_returns_config_payload_for_selected_agent(client: TestClient) -> None:
    listed = client.get("/api/agents").json()["agents"]
    refund_agent = next(agent for agent in listed if agent["name"] == "Refund Wizard")

    response = client.get(f"/api/agents/{refund_agent['id']}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == refund_agent["id"]
    assert payload["config"]["journey_build"]["agent_name"] == "Refund Wizard"
    assert payload["model"] == "gpt-5.4-mini"


def test_save_agent_persists_generated_build_and_returns_library_record(
    client: TestClient,
    tmp_path: Path,
) -> None:
    response = client.post(
        "/api/agents",
        json={
            "source": "built",
            "build_source": "prompt",
            "config": {
                "model": "gpt-5.4",
                "system_prompt": "Resolve support issues safely.",
                "tools": [{"name": "order_lookup", "description": "Look up orders", "parameters": ["order_id"]}],
                "routing_rules": [{"condition": "refund_request", "action": "route_to_refunds", "priority": 10}],
                "policies": [{"name": "Protect data", "description": "Never reveal PII", "enforcement": "strict"}],
                "eval_criteria": [{"name": "Safe handling", "weight": 0.5, "description": "Stay safe"}],
                "metadata": {
                    "agent_name": "Order Guardian",
                    "version": "v1",
                    "created_from": "prompt",
                },
            },
            "prompt_used": "Build an order support agent",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["agent"]["name"] == "Order Guardian"
    assert payload["agent"]["source"] == "built"
    assert payload["save_result"]["config_version"] == 3
    assert Path(payload["save_result"]["config_path"]).exists()
    assert Path(tmp_path / "evals" / "cases" / "generated_build.yaml").exists()
