"""API tests for transcript intelligence import, analysis, and build flows."""

from __future__ import annotations

import base64
import io
import json
import zipfile
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import changes as changes_routes
from api.routes import diagnose as diagnose_routes
from api.routes import edit as edit_routes
from core.project_memory import ProjectMemory
from deployer import Deployer
from logger.store import ConversationStore
from observer import Observer
from optimizer.change_card import ChangeCardStore
from optimizer.memory import OptimizationMemory


@dataclass
class _Score:
    quality: float
    safety: float
    latency: float
    cost: float
    composite: float


class _FakeEvalRunner:
    def run(self, config: dict | None = None) -> _Score:
        cfg = config or {}
        root = str(cfg.get("prompts", {}).get("root", "")).lower()
        score = 0.72
        if "order number" in root:
            score += 0.04
        if "empathetic" in root or "warm" in root:
            score += 0.03
        if "never share confidential" in root:
            score += 0.02
        return _Score(quality=score, safety=1.0, latency=0.8, cost=0.8, composite=score)


def _build_archive_base64() -> str:
    transcripts_json = [
        {
            "conversation_id": "hist-001",
            "session_id": "archive-1",
            "user_message": "Where is my order? I do not have my order number.",
            "agent_response": "I cannot look up the order without the order number, so I will transfer you to live support.",
            "outcome": "transfer",
        },
        {
            "conversation_id": "hist-002",
            "session_id": "archive-2",
            "user_message": "I need to change my shipping address but I do not have the order number.",
            "agent_response": "I need the order number to verify the request, so I am transferring you to a human.",
            "outcome": "transfer",
        },
        {
            "conversation_id": "hist-003",
            "session_id": "archive-3",
            "user_message": "How do I cancel my order?",
            "agent_response": "First open the orders page, then select the order, and finally confirm the cancellation.",
            "outcome": "success",
        },
    ]

    transcripts_csv = io.StringIO()
    transcripts_csv.write("conversation_id,session_id,user_message,agent_response,outcome\n")
    transcripts_csv.write(
        "hist-004,archive-4,Necesito cambiar la direccion de envio,Te voy a transferir a soporte porque falta el numero de pedido,transfer\n"
    )
    transcripts_csv.write(
        "hist-005,archive-5,How do I get a refund?,First verify identity, then confirm the refund amount, and finally submit the refund,success\n"
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as zf:
        zf.writestr("transcripts.json", json.dumps(transcripts_json))
        zf.writestr("support.csv", transcripts_csv.getvalue())

    return base64.b64encode(buffer.getvalue()).decode("ascii")


@pytest.fixture()
def app(tmp_path: Path) -> FastAPI:
    test_app = FastAPI()
    test_app.include_router(edit_routes.router)
    test_app.include_router(diagnose_routes.router)
    test_app.include_router(changes_routes.router)

    try:
        intelligence_routes = import_module("api.routes.intelligence")
    except ModuleNotFoundError:
        intelligence_routes = None
    if intelligence_routes is not None:
        test_app.include_router(intelligence_routes.router)

    store = ConversationStore(str(tmp_path / "conversations.db"))
    observer = Observer(store)
    deployer = Deployer(configs_dir=str(tmp_path / "configs"), store=store)
    memory = OptimizationMemory(db_path=str(tmp_path / "memory.db"))
    change_card_store = ChangeCardStore(db_path=str(tmp_path / "change_cards.db"))

    test_app.state.conversation_store = store
    test_app.state.observer = observer
    test_app.state.eval_runner = _FakeEvalRunner()
    test_app.state.deployer = deployer
    test_app.state.optimization_memory = memory
    test_app.state.project_memory = ProjectMemory(agent_name="Archive Bot", platform="ADK", use_case="Support")
    test_app.state.change_card_store = change_card_store

    return test_app


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


class TestTranscriptArchiveImport:
    def test_archive_import_extracts_multilingual_insights_and_assets(self, client: TestClient) -> None:
        resp = client.post(
            "/api/intelligence/archive",
            json={
                "archive_name": "support-history.zip",
                "archive_base64": _build_archive_base64(),
            },
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["archive_name"] == "support-history.zip"
        assert data["conversation_count"] == 5
        assert set(data["languages"]) >= {"en", "es"}
        assert any(intent["intent"] == "address_change" for intent in data["missing_intents"])
        assert len(data["faq_entries"]) >= 1
        assert len(data["procedure_summaries"]) >= 1
        assert len(data["workflow_suggestions"]) >= 1
        assert len(data["suggested_tests"]) >= 1

    def test_analytics_question_quantifies_transfer_root_cause(self, client: TestClient) -> None:
        imported = client.post(
            "/api/intelligence/archive",
            json={
                "archive_name": "support-history.zip",
                "archive_base64": _build_archive_base64(),
            },
        )
        report_id = imported.json()["report_id"]

        resp = client.post(
            f"/api/intelligence/reports/{report_id}/ask",
            json={"question": "Why are people transferring to live support?"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "order number" in data["answer"].lower()
        assert data["metrics"]["share"] > 0.5
        assert data["recommended_insight_id"]

    def test_apply_insight_creates_a_reviewable_change_card(self, client: TestClient, app: FastAPI) -> None:
        imported = client.post(
            "/api/intelligence/archive",
            json={
                "archive_name": "support-history.zip",
                "archive_base64": _build_archive_base64(),
            },
        )
        report = imported.json()
        insight_id = report["insights"][0]["insight_id"]

        resp = client.post(
            f"/api/intelligence/reports/{report['report_id']}/apply",
            json={"insight_id": insight_id},
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "pending_review"
        assert data["change_card"]["card_id"]
        stored = app.state.change_card_store.get(data["change_card"]["card_id"])
        assert stored is not None
        assert stored.status == "pending"
        assert stored.diff_hunks


class TestPromptToAgentBuilder:
    def test_prompt_to_agent_build_generates_artifact_not_just_text(self, client: TestClient) -> None:
        resp = client.post(
            "/api/intelligence/build",
            json={
                "connectors": ["Shopify", "Amazon Connect"],
                "prompt": (
                    "Build a customer service agent for order tracking, cancellation, and "
                    "shipping-address changes. Escalate when the customer lacks the order number."
                ),
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert any(intent["name"] == "order_tracking" for intent in data["intents"])
        assert any(intent["name"] == "cancellation" for intent in data["intents"])
        assert any(intent["name"] == "address_change" for intent in data["intents"])
        assert any("order number" in condition.lower() for condition in data["escalation_conditions"])
        assert any(tool["name"] == "shopify_order_lookup" for tool in data["tools"])
        assert len(data["journeys"]) >= 1
        assert len(data["guardrails"]) >= 1
        assert len(data["suggested_tests"]) >= 1
