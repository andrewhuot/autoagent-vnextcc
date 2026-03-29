"""Tests for the conversational builder API."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.builder import router


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_chat_creates_a_builder_session_and_base_config() -> None:
    client = _make_client()

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


def test_chat_updates_existing_config_across_follow_up_turns() -> None:
    client = _make_client()

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


def test_generate_evals_and_read_session_state() -> None:
    client = _make_client()

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


def test_export_returns_serialized_config_for_download() -> None:
    client = _make_client()

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
