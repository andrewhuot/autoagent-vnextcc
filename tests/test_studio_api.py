"""Tests for Studio API routes (/api/studio/*)."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import studio as studio_routes


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app() -> FastAPI:
    """Minimal app with studio router and no live services (mock-only mode)."""
    test_app = FastAPI()
    test_app.include_router(studio_routes.router)
    # No app.state services wired — exercises the graceful mock fallback paths.
    return test_app


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _make_mock_memory() -> MagicMock:
    """Return a mock OptimizationMemory with two sample attempts."""
    from optimizer.memory import OptimizationAttempt

    a1 = OptimizationAttempt(
        attempt_id="attempt-aaa",
        timestamp=time.time() - 3600,
        change_description="Tighten escalation rules",
        config_diff="- old rule\n+ new rule",
        status="accepted",
        config_section="routing_rules",
        score_before=0.78,
        score_after=0.84,
        significance_p_value=0.02,
        significance_delta=0.06,
        significance_n=60,
    )
    a2 = OptimizationAttempt(
        attempt_id="attempt-bbb",
        timestamp=time.time() - 1800,
        change_description="Reduce verbosity",
        config_diff="- long prompt\n+ short prompt",
        status="rejected_no_improvement",
        config_section="system_prompt",
        score_before=0.78,
        score_after=0.77,
        significance_p_value=0.72,
        significance_delta=-0.01,
        significance_n=60,
    )
    m = MagicMock()
    m.get_all.return_value = [a1, a2]
    return m


@pytest.fixture()
def app_with_memory(app: FastAPI) -> FastAPI:
    """App with a mock optimization memory attached."""
    app.state.optimization_memory = _make_mock_memory()
    return app


@pytest.fixture()
def client_with_memory(app_with_memory: FastAPI) -> TestClient:
    return TestClient(app_with_memory, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Spec tests
# ---------------------------------------------------------------------------


class TestSpecEndpoints:
    def test_list_versions_returns_mock_when_no_version_manager(self, client: TestClient) -> None:
        resp = client.get("/api/studio/spec/versions")
        assert resp.status_code == 200
        data = resp.json()
        assert "versions" in data
        assert isinstance(data["versions"], list)
        assert len(data["versions"]) > 0
        # Mock data has 3 versions
        assert data["total"] == len(data["versions"])

    def test_list_versions_response_shape(self, client: TestClient) -> None:
        resp = client.get("/api/studio/spec/versions")
        v = resp.json()["versions"][0]
        assert "version_id" in v
        assert "version_num" in v
        assert "status" in v
        assert "composite_score" in v

    def test_active_spec_returns_mock(self, client: TestClient) -> None:
        resp = client.get("/api/studio/spec/active")
        assert resp.status_code == 200
        data = resp.json()
        assert "markdown" in data
        assert len(data["markdown"]) > 0
        assert data["status"] == "active"

    def test_get_version_by_id_mock_v003(self, client: TestClient) -> None:
        resp = client.get("/api/studio/spec/versions/v003")
        assert resp.status_code == 200
        data = resp.json()
        assert data["version_id"] == "v003"
        assert data["version_num"] == 3
        assert "markdown" in data

    def test_get_version_invalid_id_returns_400(self, client: TestClient) -> None:
        resp = client.get("/api/studio/spec/versions/notanumber")
        assert resp.status_code == 400

    def test_get_version_not_found_returns_404(self, client: TestClient) -> None:
        # v999 doesn't exist in mock
        resp = client.get("/api/studio/spec/versions/v999")
        assert resp.status_code == 404

    def test_parse_spec_valid(self, client: TestClient) -> None:
        md = "# Agent\n\n## Role\nYou are a helper.\n\n## Safety\nBe safe.\n"
        resp = client.post("/api/studio/spec/parse", json={"content": md})
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["section_count"] == 2
        assert "Role" in data["extracted_sections"]
        assert "Safety" in data["extracted_sections"]

    def test_parse_spec_too_short_has_warning(self, client: TestClient) -> None:
        resp = client.post("/api/studio/spec/parse", json={"content": "Short spec"})
        assert resp.status_code == 200
        data = resp.json()
        assert any("short" in w.lower() for w in data["warnings"])

    def test_parse_spec_no_safety_section_has_warning(self, client: TestClient) -> None:
        md = "# Agent\n\n## Role\n" + ("word " * 30)
        resp = client.post("/api/studio/spec/parse", json={"content": md})
        assert resp.status_code == 200
        warnings = resp.json()["warnings"]
        assert any("safety" in w.lower() for w in warnings)

    def test_diff_spec_versions_returns_diff(self, client: TestClient) -> None:
        resp = client.get("/api/studio/spec/versions/v003/diff")
        assert resp.status_code == 200
        data = resp.json()
        assert "from_version_id" in data
        assert "to_version_id" in data
        assert isinstance(data["added_lines"], int)
        assert isinstance(data["removed_lines"], int)
        assert isinstance(data["diff_text"], str)

    def test_activate_version_mock(self, client: TestClient) -> None:
        resp = client.post("/api/studio/spec/versions/v001/activate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["version_id"] == "v001"
        assert data.get("activated") is True or data.get("mock") is True


# ---------------------------------------------------------------------------
# Observe tests
# ---------------------------------------------------------------------------


class TestObserveEndpoints:
    def test_list_sources_returns_three_sources(self, client: TestClient) -> None:
        resp = client.get("/api/studio/observe/sources")
        assert resp.status_code == 200
        sources = resp.json()
        assert isinstance(sources, list)
        assert len(sources) == 3
        kinds = {s["kind"] for s in sources}
        assert "synthetic" in kinds  # eval source always present

    def test_source_has_required_fields(self, client: TestClient) -> None:
        resp = client.get("/api/studio/observe/sources")
        s = resp.json()[0]
        for field in ("source_id", "name", "kind", "status", "conversation_count"):
            assert field in s

    def test_metrics_returns_summary(self, client: TestClient) -> None:
        resp = client.get("/api/studio/observe/metrics")
        assert resp.status_code == 200
        data = resp.json()
        for field in (
            "total_conversations",
            "success_rate",
            "safety_pass_rate",
            "avg_quality_score",
            "error_rate",
        ):
            assert field in data

    def test_metrics_window_hours_param(self, client: TestClient) -> None:
        resp = client.get("/api/studio/observe/metrics?window_hours=48")
        assert resp.status_code == 200
        assert resp.json()["window_hours"] == 48

    def test_issues_returns_clusters(self, client: TestClient) -> None:
        resp = client.get("/api/studio/observe/issues")
        assert resp.status_code == 200
        data = resp.json()
        assert "clusters" in data
        assert data["total"] == len(data["clusters"])
        assert len(data["clusters"]) > 0

    def test_issues_severity_filter(self, client: TestClient) -> None:
        resp = client.get("/api/studio/observe/issues?severity=high")
        assert resp.status_code == 200
        for cluster in resp.json()["clusters"]:
            assert cluster["severity"] == "high"

    def test_traces_list_returns_items(self, client: TestClient) -> None:
        resp = client.get("/api/studio/observe/traces")
        assert resp.status_code == 200
        data = resp.json()
        assert "traces" in data
        assert isinstance(data["traces"], list)
        assert data["limit"] == 50

    def test_traces_list_outcome_filter(self, client: TestClient) -> None:
        resp = client.get("/api/studio/observe/traces?outcome=failure")
        assert resp.status_code == 200
        for t in resp.json()["traces"]:
            assert t["outcome"] == "failure"

    def test_trace_detail_mock_returns_ok(self, client: TestClient) -> None:
        resp = client.get("/api/studio/observe/traces/trace-mock-001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["trace_id"] == "trace-mock-001"
        assert data.get("mock") is True  # no live store wired


# ---------------------------------------------------------------------------
# Optimize tests
# ---------------------------------------------------------------------------


class TestOptimizeEndpoints:
    def test_list_sessions_returns_mock_when_no_memory(self, client: TestClient) -> None:
        resp = client.get("/api/studio/optimize/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert "sessions" in data
        assert len(data["sessions"]) > 0

    def test_list_sessions_with_memory(self, client_with_memory: TestClient) -> None:
        resp = client_with_memory.get("/api/studio/optimize/sessions")
        assert resp.status_code == 200
        data = resp.json()
        # Should have at least one day-bucketed session from the mock attempts
        assert len(data["sessions"]) >= 1

    def test_create_session(self, client: TestClient) -> None:
        resp = client.post(
            "/api/studio/optimize/sessions",
            json={"label": "Test session"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert data["status"] == "active"
        assert data["session_id"].startswith("session-")

    def test_get_session_mock_id(self, client: TestClient) -> None:
        resp = client.get("/api/studio/optimize/sessions/session-mock-001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "session-mock-001"

    def test_get_session_not_found(self, client: TestClient) -> None:
        resp = client.get("/api/studio/optimize/sessions/does-not-exist-xyz")
        assert resp.status_code == 404

    def test_get_created_session(self, client: TestClient) -> None:
        create_resp = client.post(
            "/api/studio/optimize/sessions",
            json={"label": "Round-trip test"},
        )
        session_id = create_resp.json()["session_id"]
        get_resp = client.get(f"/api/studio/optimize/sessions/{session_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["session_id"] == session_id

    def test_candidates_mock_session(self, client: TestClient) -> None:
        resp = client.get("/api/studio/optimize/sessions/session-mock-001/candidates")
        assert resp.status_code == 200
        data = resp.json()
        assert "candidates" in data
        assert len(data["candidates"]) > 0
        c = data["candidates"][0]
        for field in ("candidate_id", "status", "score_before", "score_after", "delta"):
            assert field in c

    def test_candidates_with_memory(self, client_with_memory: TestClient) -> None:
        resp = client_with_memory.get("/api/studio/optimize/sessions")
        sessions = resp.json()["sessions"]
        if not sessions:
            pytest.skip("No sessions from memory")
        sid = sessions[0]["session_id"]
        resp2 = client_with_memory.get(f"/api/studio/optimize/sessions/{sid}/candidates")
        assert resp2.status_code == 200
        data = resp2.json()
        assert data["session_id"] == sid
        assert isinstance(data["candidates"], list)

    def test_evals_mock_session(self, client: TestClient) -> None:
        resp = client.get("/api/studio/optimize/sessions/session-mock-001/evals")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "session-mock-001"
        for field in ("quality", "safety", "composite", "total_cases"):
            assert field in data

    def test_backtest_mock_session(self, client: TestClient) -> None:
        resp = client.get("/api/studio/optimize/sessions/session-mock-001/backtest")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "session-mock-001"
        assert "delta" in data
        assert "is_significant" in data
        assert "p_value" in data

    def test_backtest_with_memory(self, client_with_memory: TestClient) -> None:
        resp = client_with_memory.get("/api/studio/optimize/sessions")
        sessions = resp.json()["sessions"]
        if not sessions:
            pytest.skip("No sessions from memory")
        sid = sessions[0]["session_id"]
        resp2 = client_with_memory.get(f"/api/studio/optimize/sessions/{sid}/backtest")
        assert resp2.status_code == 200
        data = resp2.json()
        # Accepted attempt has score delta of 0.06
        assert data["delta"] > 0

    def test_promote_mock_session(self, client: TestClient) -> None:
        resp = client.post(
            "/api/studio/optimize/sessions/session-mock-001/promote",
            json={"candidate_id": "cand-000", "strategy": "canary"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "promoted"
        assert data["candidate_id"] == "cand-000"
        assert data["strategy"] == "canary"

    def test_promote_requires_candidate_id(self, client: TestClient) -> None:
        resp = client.post(
            "/api/studio/optimize/sessions/session-mock-001/promote",
            json={"strategy": "canary"},
        )
        assert resp.status_code == 422  # Pydantic validation error
