"""Tests for the conversational builder API."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import yaml

from api.routes.builder import router
from cli.workspace import AgentLabWorkspace
from deployer import Deployer
from logger.store import ConversationStore
from optimizer.transcript_intelligence import TranscriptIntelligenceService
from shared.build_artifact_store import BuildArtifactStore
from shared.transcript_report_store import TranscriptReportStore


class _StubLLMResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class _StubLLMRouter:
    def __init__(self, responses: list[str], *, mock_mode: bool = False) -> None:
        self.responses = list(responses)
        self.mock_mode = mock_mode
        self.mock_reason = ""
        self.requests: list[object] = []

    def generate(self, request: object) -> _StubLLMResponse:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("No stub builder response available")
        return _StubLLMResponse(self.responses.pop(0))


def _seed_workspace(root: Path) -> None:
    workspace = AgentLabWorkspace.create(
        root=root,
        name=root.name,
        template="customer-support",
        agent_name="Builder Test Agent",
        platform="Google ADK",
    )
    workspace.ensure_structure()

    runtime_path = root / "agentlab.yaml"
    runtime_path.write_text(
        yaml.safe_dump(
            {
                "optimizer": {
                    "use_mock": False,
                    "models": [
                        {
                            "provider": "openai",
                            "model": "gpt-4o",
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

    base_config_path = Path(__file__).resolve().parents[1] / "agent" / "config" / "base_config.yaml"
    base_config = yaml.safe_load(base_config_path.read_text(encoding="utf-8"))
    store = ConversationStore(db_path=str(root / "conversations.db"))
    deployer = Deployer(configs_dir=str(root / "configs"), store=store)
    saved = deployer.version_manager.save_version(base_config, scores={"composite": 0.0}, status="active")
    (root / "configs" / "v001_base.yaml").write_text(
        yaml.safe_dump(base_config, sort_keys=False),
        encoding="utf-8",
    )
    workspace.set_active_config(saved.version, filename=saved.filename)


def _make_client(root: Path, *, llm_router: object | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    _seed_workspace(root)

    report_store = TranscriptReportStore(str(root / ".agentlab" / "intelligence_reports.json"))
    app.state.transcript_report_store = report_store
    app.state.transcript_intelligence_service = TranscriptIntelligenceService(
        llm_router=llm_router,
        report_store=report_store,
    )
    app.state.build_artifact_store = BuildArtifactStore(
        path=root / ".agentlab" / "build_artifacts.json",
        latest_path=root / ".agentlab" / "build_artifact_latest.json",
    )
    app.state.deployer = Deployer(
        configs_dir=str(root / "configs"),
        store=ConversationStore(db_path=str(root / "conversations.db")),
    )
    app.state.runtime_config = SimpleNamespace()
    return TestClient(app)


def test_chat_creates_a_builder_session_and_base_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    client = _make_client(tmp_path)

    response = client.post(
        "/api/builder/chat",
        json={
            "message": (
                "Build me a customer support agent for an airline that handles "
                "booking changes, cancellations, and flight status"
            )
        },
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["session_id"]
    assert payload["mock_mode"] is True
    assert payload["stats"]["routing_rule_count"] >= 3
    assert "airline" in payload["config"]["agent_name"].lower()
    assert "booking" in payload["config"]["system_prompt"].lower()
    assert payload["messages"][-1]["role"] == "assistant"


def test_chat_updates_existing_config_across_follow_up_turns(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    client = _make_client(tmp_path)

    initial = client.post(
        "/api/builder/chat",
        json={"message": "Build me an airline support agent for cancellations and flight status"},
    )
    session_id = initial.json()["session_id"]

    tool_update = client.post(
        "/api/builder/chat",
        json={
            "session_id": session_id,
            "message": "Add a tool for checking flight status",
        },
    )
    assert tool_update.status_code == 200
    tool_payload = tool_update.json()
    assert any(
        tool["name"] == "flight_status_lookup" for tool in tool_payload["config"]["tools"]
    )

    policy_update = client.post(
        "/api/builder/chat",
        json={
            "session_id": session_id,
            "message": "Add a policy that it should never reveal internal codes",
        },
    )
    assert policy_update.status_code == 200
    policy_payload = policy_update.json()
    assert any(
        "internal codes" in policy["description"].lower()
        for policy in policy_payload["config"]["policies"]
    )

    tone_update = client.post(
        "/api/builder/chat",
        json={
            "session_id": session_id,
            "message": "Make it more empathetic",
        },
    )
    assert tone_update.status_code == 200
    tone_payload = tone_update.json()
    assert "empathetic" in tone_payload["config"]["system_prompt"].lower()


def test_generate_evals_and_read_session_state(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    client = _make_client(tmp_path)

    create = client.post(
        "/api/builder/chat",
        json={"message": "Build me an airline support agent"},
    )
    session_id = create.json()["session_id"]

    evals = client.post(
        "/api/builder/chat",
        json={
            "session_id": session_id,
            "message": "Generate evals for this",
        },
    )

    assert evals.status_code == 200
    eval_payload = evals.json()
    assert eval_payload["evals"]["case_count"] >= 3

    session = client.get(f"/api/builder/session/{session_id}")
    assert session.status_code == 200
    session_payload = session.json()
    assert session_payload["session_id"] == session_id
    assert len(session_payload["messages"]) >= 4
    assert session_payload["evals"]["case_count"] >= 3


def test_preview_uses_built_domain_in_mock_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    client = _make_client(tmp_path)

    create = client.post(
        "/api/builder/chat",
        json={
            "message": (
                "Build me an airline support agent for booking changes, cancellations, "
                "and live flight status"
            )
        },
    )
    session_id = create.json()["session_id"]

    preview = client.post(
        "/api/builder/preview",
        json={
            "session_id": session_id,
            "message": "My flight was delayed and I need to change my booking without paying a fee.",
        },
    )

    assert preview.status_code == 200
    payload = preview.json()
    response_text = payload["response"].lower()
    assert "order" not in response_text
    assert any(token in response_text for token in ("flight", "booking", "reservation"))
    assert payload["specialist_used"] == "orders"
    assert any(
        call.get("tool") == "change_booking" or call.get("name") == "change_booking"
        for call in payload["tool_calls"]
    )


def test_export_returns_serialized_config_for_download(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    client = _make_client(tmp_path)

    create = client.post(
        "/api/builder/chat",
        json={"message": "Build me an airline support agent"},
    )
    session_id = create.json()["session_id"]

    export = client.post(
        "/api/builder/export",
        json={"session_id": session_id, "format": "yaml"},
    )

    assert export.status_code == 200
    payload = export.json()
    assert payload["filename"].endswith(".yaml")
    assert "system_prompt:" in payload["content"]
    assert "agent_name:" in payload["content"]


def test_chat_uses_live_router_output_when_real_provider_router_is_available(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    client = _make_client(
        tmp_path,
        llm_router=_StubLLMRouter(
            [
                json.dumps(
                    {
                        "model": "gpt-4o-mini",
                        "system_prompt": "<role>VIP travel concierge.</role>",
                        "tools": [
                            {
                                "name": "flight_status_lookup",
                                "description": "Fetch flight status for a traveler.",
                                "parameters": ["flight_number", "departure_date"],
                            }
                        ],
                        "routing_rules": [
                            {
                                "condition": "intent == 'flight_status'",
                                "action": "orders",
                                "priority": 10,
                            }
                        ],
                        "policies": [
                            {
                                "name": "vip_handoff",
                                "description": "Escalate VIP disruption cases with full context.",
                                "enforcement": "strict",
                            }
                        ],
                        "eval_criteria": [
                            {
                                "name": "vip_accuracy",
                                "weight": 0.4,
                                "description": "Handle VIP traveler requests accurately.",
                            }
                        ],
                        "metadata": {
                            "agent_name": "VIP Travel Concierge",
                            "version": "1.0.0",
                            "created_from": "prompt",
                        },
                    }
                )
            ]
        ),
    )

    response = client.post(
        "/api/builder/chat",
        json={"message": "Build me a VIP travel concierge for flight status and disruption handling"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mock_mode"] is False
    assert payload["config"]["agent_name"] == "VIP Travel Concierge"
    assert payload["config"]["model"] == "gpt-4o-mini"


def test_save_persists_builder_config_into_workspace_versions(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    client = _make_client(tmp_path)

    create = client.post(
        "/api/builder/chat",
        json={"message": "Build me an airline support agent for cancellations and flight status"},
    )
    session_id = create.json()["session_id"]

    save = client.post(
        "/api/builder/save",
        json={"session_id": session_id},
    )

    assert save.status_code == 200
    payload = save.json()
    assert payload["config_version"] >= 2
    assert Path(payload["config_path"]).exists()
    metadata = json.loads((tmp_path / ".agentlab" / "workspace.json").read_text(encoding="utf-8"))
    assert metadata["active_config_version"] == payload["config_version"]
    assert (tmp_path / "evals" / "cases" / "generated_build.yaml").exists()
