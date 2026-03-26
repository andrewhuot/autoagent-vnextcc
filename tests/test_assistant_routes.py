"""Tests for Assistant API routes — conversational AI interface."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import assistant as assistant_routes


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app() -> FastAPI:
    """Minimal FastAPI app with assistant router."""
    test_app = FastAPI()
    test_app.include_router(assistant_routes.router)

    # Mock app.state (assistant doesn't need much for now)
    test_app.state.conversation_store = None
    test_app.state.observer = None
    test_app.state.optimizer = None

    return test_app


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    """Test client for the app."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_sessions():
    """Clear session storage before each test."""
    assistant_routes._sessions.clear()
    yield
    assistant_routes._sessions.clear()


# ---------------------------------------------------------------------------
# POST /api/assistant/message — SSE streaming
# ---------------------------------------------------------------------------


class TestAssistantMessage:
    """Tests for the message endpoint with SSE streaming."""

    def test_send_message_without_session(self, client: TestClient) -> None:
        """Test sending a message creates a new session."""
        response = client.post(
            "/api/assistant/message",
            json={"message": "Hello, assistant!"},
            headers={"Accept": "text/event-stream"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
        assert "X-Session-ID" in response.headers

        # Parse SSE events
        events = self._parse_sse_events(response.text)
        assert len(events) > 0

        # Should have at least thinking, text, and suggestions events
        event_types = [e["event"] for e in events]
        assert "thinking" in event_types
        assert "text" in event_types or "card" in event_types
        assert "suggestions" in event_types

    def test_send_message_with_session(self, client: TestClient) -> None:
        """Test sending a message with existing session ID."""
        # Create session first
        resp1 = client.post(
            "/api/assistant/message",
            json={"message": "First message"},
            headers={"Accept": "text/event-stream"},
        )
        session_id = resp1.headers["X-Session-ID"]

        # Send second message with session
        resp2 = client.post(
            "/api/assistant/message",
            json={"message": "Second message", "session_id": session_id},
            headers={"Accept": "text/event-stream"},
        )
        assert resp2.status_code == 200
        assert resp2.headers["X-Session-ID"] == session_id

    def test_build_intent_returns_agent_preview_card(self, client: TestClient) -> None:
        """Test that build intent returns agent_preview card."""
        response = client.post(
            "/api/assistant/message",
            json={"message": "Build me a customer support agent"},
            headers={"Accept": "text/event-stream"},
        )
        events = self._parse_sse_events(response.text)

        # Should have agent_preview card
        cards = [e for e in events if e["event"] == "card"]
        assert len(cards) > 0
        agent_preview = next((c for c in cards if c["data"]["type"] == "agent_preview"), None)
        assert agent_preview is not None
        assert "agent_name" in agent_preview["data"]["data"]

    def test_diagnose_intent_returns_diagnosis_card(self, client: TestClient) -> None:
        """Test that diagnose intent returns diagnosis card."""
        response = client.post(
            "/api/assistant/message",
            json={"message": "Why is my agent failing?"},
            headers={"Accept": "text/event-stream"},
        )
        events = self._parse_sse_events(response.text)

        # Should have diagnosis card
        cards = [e for e in events if e["event"] == "card"]
        assert len(cards) > 0
        diagnosis = next((c for c in cards if c["data"]["type"] == "diagnosis"), None)
        assert diagnosis is not None
        assert "root_cause" in diagnosis["data"]["data"]

    def test_fix_intent_returns_diff_card(self, client: TestClient) -> None:
        """Test that fix intent returns diff card."""
        response = client.post(
            "/api/assistant/message",
            json={"message": "Fix the routing issue"},
            headers={"Accept": "text/event-stream"},
        )
        events = self._parse_sse_events(response.text)

        # Should have diff card
        cards = [e for e in events if e["event"] == "card"]
        assert len(cards) > 0
        diff = next((c for c in cards if c["data"]["type"] == "diff"), None)
        assert diff is not None
        assert "before" in diff["data"]["data"]
        assert "after" in diff["data"]["data"]

    def test_explore_intent_returns_cluster_cards(self, client: TestClient) -> None:
        """Test that explore intent returns cluster cards."""
        response = client.post(
            "/api/assistant/message",
            json={"message": "What are the top failures?"},
            headers={"Accept": "text/event-stream"},
        )
        events = self._parse_sse_events(response.text)

        # Should have cluster cards
        cards = [e for e in events if e["event"] == "card"]
        assert len(cards) > 0
        clusters = [c for c in cards if c["data"]["type"] == "cluster"]
        assert len(clusters) >= 1
        assert "rank" in clusters[0]["data"]["data"]
        assert "impact" in clusters[0]["data"]["data"]

    def test_general_message_returns_suggestions(self, client: TestClient) -> None:
        """Test that general message returns helpful suggestions."""
        response = client.post(
            "/api/assistant/message",
            json={"message": "What can you do?"},
            headers={"Accept": "text/event-stream"},
        )
        events = self._parse_sse_events(response.text)

        # Should have suggestions
        suggestions = [e for e in events if e["event"] == "suggestions"]
        assert len(suggestions) == 1
        assert "actions" in suggestions[0]["data"]
        assert len(suggestions[0]["data"]["actions"]) > 0

    def test_message_with_context(self, client: TestClient) -> None:
        """Test sending message with additional context."""
        response = client.post(
            "/api/assistant/message",
            json={
                "message": "Optimize my agent",
                "context": {"agent_id": "agent_123", "current_score": 0.72}
            },
            headers={"Accept": "text/event-stream"},
        )
        assert response.status_code == 200
        session_id = response.headers["X-Session-ID"]

        # Context should be stored in session
        assert session_id in assistant_routes._sessions
        session_data = assistant_routes._sessions[session_id]
        assert "agent_id" in session_data["context"]
        assert session_data["context"]["agent_id"] == "agent_123"

    def test_empty_message_rejected(self, client: TestClient) -> None:
        """Test that empty message is rejected."""
        response = client.post(
            "/api/assistant/message",
            json={"message": ""},
        )
        assert response.status_code == 422  # Validation error

    @staticmethod
    def _parse_sse_events(sse_text: str) -> list[dict]:
        """Parse SSE text into list of event dictionaries."""
        events = []
        current_event = None
        current_data = ""

        for line in sse_text.strip().split("\n"):
            if line.startswith("event: "):
                if current_event and current_data:
                    events.append({
                        "event": current_event,
                        "data": json.loads(current_data)
                    })
                current_event = line.replace("event: ", "").strip()
                current_data = ""
            elif line.startswith("data: "):
                current_data = line.replace("data: ", "").strip()
            elif line == "":
                if current_event and current_data:
                    events.append({
                        "event": current_event,
                        "data": json.loads(current_data)
                    })
                    current_event = None
                    current_data = ""

        # Handle last event if exists
        if current_event and current_data:
            events.append({
                "event": current_event,
                "data": json.loads(current_data)
            })

        return events


# ---------------------------------------------------------------------------
# POST /api/assistant/upload — File uploads
# ---------------------------------------------------------------------------


class TestAssistantUpload:
    """Tests for file upload endpoint."""

    def test_upload_single_file(self, client: TestClient) -> None:
        """Test uploading a single file."""
        file_content = b"conversation,outcome\nconv1,success\nconv2,fail"
        files = {"files": ("transcripts.csv", BytesIO(file_content), "text/csv")}

        response = client.post("/api/assistant/upload", files=files)
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["total_files"] == 1
        assert len(data["files"]) == 1
        assert data["files"][0]["filename"] == "transcripts.csv"
        assert data["files"][0]["extension"] == ".csv"

    def test_upload_multiple_files(self, client: TestClient) -> None:
        """Test uploading multiple files."""
        files = [
            ("files", ("transcripts.csv", BytesIO(b"data"), "text/csv")),
            ("files", ("config.yaml", BytesIO(b"config"), "text/yaml")),
            ("files", ("doc.pdf", BytesIO(b"pdf data"), "application/pdf")),
        ]

        response = client.post("/api/assistant/upload", files=files)
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["total_files"] == 3

    def test_upload_with_session_id(self, client: TestClient) -> None:
        """Test upload with session ID."""
        # Create session
        msg_resp = client.post(
            "/api/assistant/message",
            json={"message": "Hello"},
            headers={"Accept": "text/event-stream"},
        )
        session_id = msg_resp.headers["X-Session-ID"]

        # Upload with session
        files = {"files": ("data.json", BytesIO(b'{"test": true}'), "application/json")}
        data = {"session_id": session_id, "description": "Test data"}

        response = client.post("/api/assistant/upload", files=files, data=data)
        assert response.status_code == 200
        assert response.json()["session_id"] == session_id

        # Verify file is stored in session context
        session_data = assistant_routes._sessions[session_id]
        assert "uploaded_files" in session_data["context"]
        assert len(session_data["context"]["uploaded_files"]) == 1

    def test_upload_unsupported_file_type(self, client: TestClient) -> None:
        """Test that unsupported file types are rejected."""
        files = {"files": ("script.exe", BytesIO(b"binary"), "application/x-executable")}

        response = client.post("/api/assistant/upload", files=files)
        assert response.status_code == 400
        assert "Unsupported file type" in response.json()["detail"]

    def test_upload_file_too_large(self, client: TestClient) -> None:
        """Test that oversized files are rejected."""
        # Create 51MB file (over 50MB limit)
        large_content = b"x" * (51 * 1024 * 1024)
        files = {"files": ("large.csv", BytesIO(large_content), "text/csv")}

        response = client.post("/api/assistant/upload", files=files)
        assert response.status_code == 400
        assert "File too large" in response.json()["detail"]

    def test_upload_supported_file_types(self, client: TestClient) -> None:
        """Test all supported file types are accepted."""
        supported_types = [
            ("data.csv", "text/csv"),
            ("data.json", "application/json"),
            ("data.jsonl", "application/jsonl"),
            ("archive.zip", "application/zip"),
            ("doc.pdf", "application/pdf"),
            ("doc.txt", "text/plain"),
            ("audio.mp3", "audio/mpeg"),
            ("audio.wav", "audio/wav"),
            ("config.yaml", "text/yaml"),
        ]

        for filename, content_type in supported_types:
            files = {"files": (filename, BytesIO(b"test"), content_type)}
            response = client.post("/api/assistant/upload", files=files)
            assert response.status_code == 200, f"Failed for {filename}"


# ---------------------------------------------------------------------------
# GET /api/assistant/history — Conversation history
# ---------------------------------------------------------------------------


class TestAssistantHistory:
    """Tests for conversation history endpoint."""

    def test_get_history_for_session(self, client: TestClient) -> None:
        """Test getting history for a session."""
        # Create session with messages
        resp1 = client.post(
            "/api/assistant/message",
            json={"message": "First message"},
            headers={"Accept": "text/event-stream"},
        )
        session_id = resp1.headers["X-Session-ID"]

        resp2 = client.post(
            "/api/assistant/message",
            json={"message": "Second message", "session_id": session_id},
            headers={"Accept": "text/event-stream"},
        )

        # Get history
        history_resp = client.get(f"/api/assistant/history?session_id={session_id}")
        assert history_resp.status_code == 200

        data = history_resp.json()
        assert data["session_id"] == session_id
        assert data["total"] == 2
        assert len(data["turns"]) == 2
        assert data["turns"][0]["user_message"] == "First message"
        assert data["turns"][1]["user_message"] == "Second message"

    def test_get_history_nonexistent_session(self, client: TestClient) -> None:
        """Test getting history for nonexistent session returns 404."""
        response = client.get("/api/assistant/history?session_id=nonexistent")
        assert response.status_code == 404
        assert "Session not found" in response.json()["detail"]

    def test_history_contains_all_events(self, client: TestClient) -> None:
        """Test that history contains all response events."""
        resp = client.post(
            "/api/assistant/message",
            json={"message": "Build an agent"},
            headers={"Accept": "text/event-stream"},
        )
        session_id = resp.headers["X-Session-ID"]

        # Get history
        history_resp = client.get(f"/api/assistant/history?session_id={session_id}")
        data = history_resp.json()

        # Check that events are stored
        turn = data["turns"][0]
        assert len(turn["assistant_response"]) > 0
        assert any(e["event"] == "thinking" for e in turn["assistant_response"])


# ---------------------------------------------------------------------------
# DELETE /api/assistant/history — Clear conversation
# ---------------------------------------------------------------------------


class TestAssistantClearHistory:
    """Tests for clearing conversation history."""

    def test_clear_history(self, client: TestClient) -> None:
        """Test clearing conversation history."""
        # Create session
        resp = client.post(
            "/api/assistant/message",
            json={"message": "Hello"},
            headers={"Accept": "text/event-stream"},
        )
        session_id = resp.headers["X-Session-ID"]

        # Verify session exists
        assert session_id in assistant_routes._sessions

        # Clear history
        clear_resp = client.delete(f"/api/assistant/history?session_id={session_id}")
        assert clear_resp.status_code == 200
        assert clear_resp.json()["success"] is True

        # Verify session is gone
        assert session_id not in assistant_routes._sessions

    def test_clear_nonexistent_session(self, client: TestClient) -> None:
        """Test clearing nonexistent session returns 404."""
        response = client.delete("/api/assistant/history?session_id=nonexistent")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/assistant/suggestions — Contextual suggestions
# ---------------------------------------------------------------------------


class TestAssistantSuggestions:
    """Tests for suggestions endpoint."""

    def test_get_suggestions(self, client: TestClient) -> None:
        """Test getting contextual suggestions."""
        # Create session
        resp = client.post(
            "/api/assistant/message",
            json={"message": "Hello"},
            headers={"Accept": "text/event-stream"},
        )
        session_id = resp.headers["X-Session-ID"]

        # Get suggestions
        sugg_resp = client.get(f"/api/assistant/suggestions?session_id={session_id}")
        assert sugg_resp.status_code == 200

        data = sugg_resp.json()
        assert data["session_id"] == session_id
        assert len(data["suggestions"]) > 0
        assert len(data["quick_actions"]) > 0

        # Check quick action structure
        action = data["quick_actions"][0]
        assert "label" in action
        assert "action" in action
        assert "icon" in action

    def test_get_suggestions_nonexistent_session(self, client: TestClient) -> None:
        """Test getting suggestions for nonexistent session returns 404."""
        response = client.get("/api/assistant/suggestions?session_id=nonexistent")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/assistant/action/{action_id} — Execute actions
# ---------------------------------------------------------------------------


class TestAssistantActions:
    """Tests for action execution endpoint."""

    def test_approve_fix_action(self, client: TestClient) -> None:
        """Test executing approve_fix action."""
        # Create session
        resp = client.post(
            "/api/assistant/message",
            json={"message": "Hello"},
            headers={"Accept": "text/event-stream"},
        )
        session_id = resp.headers["X-Session-ID"]

        # Execute action
        action_resp = client.post(
            "/api/assistant/action/approve_fix",
            json={"session_id": session_id, "action_data": {}},
        )
        assert action_resp.status_code == 200

        data = action_resp.json()
        assert data["success"] is True
        assert data["action_id"] == "approve_fix"
        assert "result" in data
        assert "applied" in data["result"]

    def test_deploy_action(self, client: TestClient) -> None:
        """Test executing deploy action."""
        resp = client.post(
            "/api/assistant/message",
            json={"message": "Hello"},
            headers={"Accept": "text/event-stream"},
        )
        session_id = resp.headers["X-Session-ID"]

        action_resp = client.post(
            "/api/assistant/action/deploy",
            json={"session_id": session_id},
        )
        assert action_resp.status_code == 200

        data = action_resp.json()
        assert data["success"] is True
        assert "deployed" in data["result"]

    def test_unknown_action_returns_400(self, client: TestClient) -> None:
        """Test that unknown action returns 400."""
        resp = client.post(
            "/api/assistant/message",
            json={"message": "Hello"},
            headers={"Accept": "text/event-stream"},
        )
        session_id = resp.headers["X-Session-ID"]

        action_resp = client.post(
            "/api/assistant/action/unknown_action",
            json={"session_id": session_id},
        )
        assert action_resp.status_code == 400
        assert "Unknown action" in action_resp.json()["detail"]

    def test_action_nonexistent_session(self, client: TestClient) -> None:
        """Test executing action on nonexistent session returns 404."""
        response = client.post(
            "/api/assistant/action/approve_fix",
            json={"session_id": "nonexistent"},
        )
        assert response.status_code == 404

    def test_action_stored_in_session_context(self, client: TestClient) -> None:
        """Test that executed action is stored in session context."""
        resp = client.post(
            "/api/assistant/message",
            json={"message": "Hello"},
            headers={"Accept": "text/event-stream"},
        )
        session_id = resp.headers["X-Session-ID"]

        client.post(
            "/api/assistant/action/approve_fix",
            json={"session_id": session_id},
        )

        # Verify action stored in context
        session_data = assistant_routes._sessions[session_id]
        assert "last_action" in session_data["context"]
        assert session_data["context"]["last_action"]["action_id"] == "approve_fix"

    def test_all_action_types(self, client: TestClient) -> None:
        """Test all supported action types."""
        resp = client.post(
            "/api/assistant/message",
            json={"message": "Hello"},
            headers={"Accept": "text/event-stream"},
        )
        session_id = resp.headers["X-Session-ID"]

        actions = ["approve_fix", "deploy", "rollback", "show_examples", "run_eval"]

        for action_id in actions:
            action_resp = client.post(
                f"/api/assistant/action/{action_id}",
                json={"session_id": session_id},
            )
            assert action_resp.status_code == 200, f"Failed for {action_id}"
            assert action_resp.json()["action_id"] == action_id
