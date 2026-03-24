"""Tests for registry, traces (grades/blame/graph), and scorers API routes."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import registry as registry_routes
from api.routes import scorers as scorers_routes
from api.routes import traces as traces_routes
from evals.nl_scorer import NLScorer
from observer.traces import TraceEvent, TraceEventType, TraceSpan, TraceStore
from registry.store import RegistryStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _TestRegistryStore(RegistryStore):
    """RegistryStore with check_same_thread=False for test client compatibility."""

    def __init__(self, db_path: str = "registry.db") -> None:
        import sqlite3
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()


@pytest.fixture()
def registry_store(tmp_path: Path) -> RegistryStore:
    """Create a fresh in-tmp-dir RegistryStore."""
    return _TestRegistryStore(db_path=str(tmp_path / "test_registry.db"))


@pytest.fixture()
def nl_scorer() -> NLScorer:
    return NLScorer()


@pytest.fixture()
def trace_store(tmp_path: Path) -> TraceStore:
    return TraceStore(db_path=str(tmp_path / "test_traces.db"))


@pytest.fixture()
def app(registry_store: RegistryStore, nl_scorer: NLScorer, trace_store: TraceStore) -> FastAPI:
    """Minimal FastAPI app with the three routers and mock state."""
    test_app = FastAPI()
    test_app.include_router(registry_routes.router)
    test_app.include_router(scorers_routes.router)
    test_app.include_router(traces_routes.router)

    test_app.state.registry_store = registry_store
    test_app.state.nl_scorer = nl_scorer
    test_app.state.trace_store = trace_store

    return test_app


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# Registry — Skills
# ---------------------------------------------------------------------------


class TestRegistrySkills:
    def test_list_skills_empty(self, client: TestClient) -> None:
        resp = client.get("/api/registry/skills")
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    def test_create_skill(self, client: TestClient) -> None:
        resp = client.post(
            "/api/registry/skills",
            json={"name": "returns_handling", "instructions": "Handle returns politely"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "returns_handling"
        assert data["version"] == 1

    def test_get_skill(self, client: TestClient) -> None:
        client.post(
            "/api/registry/skills",
            json={"name": "greet", "instructions": "Greet the user"},
        )
        resp = client.get("/api/registry/skills/greet")
        assert resp.status_code == 200
        assert resp.json()["item"]["name"] == "greet"

    def test_get_skill_specific_version(self, client: TestClient) -> None:
        client.post("/api/registry/skills", json={"name": "v_test", "instructions": "v1"})
        client.post("/api/registry/skills", json={"name": "v_test", "instructions": "v2"})
        resp = client.get("/api/registry/skills/v_test?version=1")
        assert resp.status_code == 200
        assert resp.json()["item"]["version"] == 1

    def test_get_skill_not_found(self, client: TestClient) -> None:
        resp = client.get("/api/registry/skills/nonexistent")
        assert resp.status_code == 404

    def test_list_skills_after_create(self, client: TestClient) -> None:
        client.post("/api/registry/skills", json={"name": "s1", "instructions": "i1"})
        client.post("/api/registry/skills", json={"name": "s2", "instructions": "i2"})
        resp = client.get("/api/registry/skills")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 2


# ---------------------------------------------------------------------------
# Registry — Policies
# ---------------------------------------------------------------------------


class TestRegistryPolicies:
    def test_create_and_get_policy(self, client: TestClient) -> None:
        resp = client.post(
            "/api/registry/policies",
            json={"name": "safety_rules", "rules": ["no PII", "no profanity"]},
        )
        assert resp.status_code == 200
        assert resp.json()["version"] == 1

        resp = client.get("/api/registry/policies/safety_rules")
        assert resp.status_code == 200
        item = resp.json()["item"]
        assert item["data"]["rules"] == ["no PII", "no profanity"]

    def test_list_policies(self, client: TestClient) -> None:
        client.post("/api/registry/policies", json={"name": "p1", "rules": ["r1"]})
        resp = client.get("/api/registry/policies")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1


# ---------------------------------------------------------------------------
# Registry — Tool Contracts
# ---------------------------------------------------------------------------


class TestRegistryToolContracts:
    def test_create_tool_contract(self, client: TestClient) -> None:
        resp = client.post(
            "/api/registry/tool_contracts",
            json={"name": "order_lookup", "description": "Look up orders"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "order_lookup"

    def test_list_tool_contracts(self, client: TestClient) -> None:
        client.post("/api/registry/tool_contracts", json={"name": "tc1", "description": "d"})
        resp = client.get("/api/registry/tool_contracts")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1


# ---------------------------------------------------------------------------
# Registry — Handoff Schemas
# ---------------------------------------------------------------------------


class TestRegistryHandoffSchemas:
    def test_create_handoff_schema(self, client: TestClient) -> None:
        resp = client.post(
            "/api/registry/handoff_schemas",
            json={
                "name": "support_to_billing",
                "from_agent": "support",
                "to_agent": "billing",
                "required_fields": ["customer_id", "issue"],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "support_to_billing"

    def test_get_handoff_schema(self, client: TestClient) -> None:
        client.post(
            "/api/registry/handoff_schemas",
            json={
                "name": "hs1",
                "from_agent": "a",
                "to_agent": "b",
                "required_fields": ["x"],
            },
        )
        resp = client.get("/api/registry/handoff_schemas/hs1")
        assert resp.status_code == 200
        assert resp.json()["item"]["data"]["from_agent"] == "a"


# ---------------------------------------------------------------------------
# Registry — Diff
# ---------------------------------------------------------------------------


class TestRegistryDiff:
    def test_diff_two_versions(self, client: TestClient) -> None:
        client.post("/api/registry/skills", json={"name": "ds", "instructions": "v1"})
        client.post("/api/registry/skills", json={"name": "ds", "instructions": "v2"})
        resp = client.get("/api/registry/skills/ds/diff?v1=1&v2=2")
        assert resp.status_code == 200
        data = resp.json()
        assert "changes" in data
        assert any(c["field"] == "instructions" for c in data["changes"])


# ---------------------------------------------------------------------------
# Registry — Search
# ---------------------------------------------------------------------------


class TestRegistrySearch:
    def test_search_skills(self, client: TestClient) -> None:
        client.post("/api/registry/skills", json={"name": "returns_handling", "instructions": "Handle returns"})
        client.post("/api/registry/skills", json={"name": "greeting", "instructions": "Greet user"})
        resp = client.get("/api/registry/search?q=return&type=skills")
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) >= 1
        assert any("returns" in r["name"] for r in results)

    def test_search_all_types(self, client: TestClient) -> None:
        client.post("/api/registry/skills", json={"name": "findme", "instructions": "x"})
        client.post("/api/registry/policies", json={"name": "findme_policy", "rules": ["r"]})
        resp = client.get("/api/registry/search?q=findme")
        assert resp.status_code == 200
        assert len(resp.json()["results"]) >= 2

    def test_search_invalid_type(self, client: TestClient) -> None:
        resp = client.get("/api/registry/search?q=x&type=invalid")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Registry — Import
# ---------------------------------------------------------------------------


class TestRegistryImport:
    def test_import_from_json_file(self, client: TestClient, tmp_path: Path) -> None:
        data = {
            "skills": [
                {"name": "imported_skill", "instructions": "do stuff"},
            ],
            "policies": [
                {"name": "imported_policy", "rules": ["rule1"]},
            ],
        }
        f = tmp_path / "import.json"
        f.write_text(json.dumps(data))

        resp = client.post("/api/registry/import", json={"file_path": str(f)})
        assert resp.status_code == 200
        imported = resp.json()["imported"]
        assert imported["skills"] == 1
        assert imported["policies"] == 1

    def test_import_file_not_found(self, client: TestClient) -> None:
        resp = client.post("/api/registry/import", json={"file_path": "/nonexistent/file.json"})
        assert resp.status_code == 404

    def test_import_missing_path(self, client: TestClient) -> None:
        resp = client.post("/api/registry/import", json={})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Registry — Invalid type
# ---------------------------------------------------------------------------


class TestRegistryEdgeCases:
    def test_invalid_item_type(self, client: TestClient) -> None:
        resp = client.get("/api/registry/invalid_type")
        assert resp.status_code == 400

    def test_create_missing_name(self, client: TestClient) -> None:
        resp = client.post("/api/registry/skills", json={"instructions": "no name"})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Traces — Grades
# ---------------------------------------------------------------------------


class TestTraceGrades:
    def test_grades_empty_trace(self, client: TestClient) -> None:
        resp = client.get("/api/traces/nonexistent-trace/grades")
        assert resp.status_code == 200
        data = resp.json()
        assert data["trace_id"] == "nonexistent-trace"
        assert data["grades"] == []

    def test_grades_with_spans(self, client: TestClient, trace_store: TraceStore) -> None:
        # Insert a span and event so grader has something to work with
        now = time.time()
        trace_store.log_span(
            TraceSpan(
                trace_id="t1",
                span_id="s1",
                parent_span_id=None,
                operation="root",
                agent_path="/root",
                start_time=now - 1,
                end_time=now,
                status="ok",
                attributes={},
            )
        )
        trace_store.log_event(
            TraceEvent(
                event_id="e1",
                trace_id="t1",
                event_type=TraceEventType.model_response.value,
                timestamp=now - 0.5,
                invocation_id="inv1",
                session_id="sess1",
                agent_path="/root",
                branch="main",
            )
        )
        resp = client.get("/api/traces/t1/grades")
        assert resp.status_code == 200
        data = resp.json()
        assert data["trace_id"] == "t1"
        assert len(data["grades"]) > 0


# ---------------------------------------------------------------------------
# Traces — Blame map
# ---------------------------------------------------------------------------


class TestTraceBlame:
    def test_blame_empty(self, client: TestClient) -> None:
        resp = client.get("/api/traces/blame?window=86400")
        assert resp.status_code == 200
        data = resp.json()
        assert data["clusters"] == []
        assert data["window_seconds"] == 86400


# ---------------------------------------------------------------------------
# Traces — Graph
# ---------------------------------------------------------------------------


class TestTraceGraph:
    def test_graph_empty_trace(self, client: TestClient) -> None:
        resp = client.get("/api/traces/nonexistent/graph")
        assert resp.status_code == 200
        data = resp.json()
        assert data["nodes"] == []
        assert data["edges"] == []
        assert data["critical_path"] == []
        assert data["bottlenecks"] == []

    def test_graph_with_spans(self, client: TestClient, trace_store: TraceStore) -> None:
        now = time.time()
        trace_store.log_span(
            TraceSpan(
                trace_id="t2",
                span_id="s1",
                parent_span_id=None,
                operation="root_op",
                agent_path="/root",
                start_time=now - 2,
                end_time=now,
                status="ok",
                attributes={},
            )
        )
        trace_store.log_span(
            TraceSpan(
                trace_id="t2",
                span_id="s2",
                parent_span_id="s1",
                operation="child_op",
                agent_path="/root/child",
                start_time=now - 1.5,
                end_time=now - 0.5,
                status="ok",
                attributes={},
            )
        )
        resp = client.get("/api/traces/t2/graph")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["nodes"]) == 2
        assert len(data["edges"]) >= 1
        assert len(data["critical_path"]) >= 1


# ---------------------------------------------------------------------------
# Scorers — Create
# ---------------------------------------------------------------------------


class TestScorerCreate:
    def test_create_scorer(self, client: TestClient) -> None:
        resp = client.post(
            "/api/scorers/create",
            json={"description": "The agent should respond accurately and politely"},
        )
        assert resp.status_code == 200
        scorer = resp.json()["scorer"]
        assert "name" in scorer
        assert "dimensions" in scorer
        assert len(scorer["dimensions"]) > 0

    def test_create_scorer_with_name(self, client: TestClient) -> None:
        resp = client.post(
            "/api/scorers/create",
            json={"description": "Be accurate", "name": "my_scorer"},
        )
        assert resp.status_code == 200
        assert resp.json()["scorer"]["name"] == "my_scorer"

    def test_create_scorer_missing_description(self, client: TestClient) -> None:
        resp = client.post("/api/scorers/create", json={})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Scorers — List & Get
# ---------------------------------------------------------------------------


class TestScorerListGet:
    def test_list_empty(self, client: TestClient) -> None:
        resp = client.get("/api/scorers")
        assert resp.status_code == 200
        assert resp.json()["scorers"] == []

    def test_list_after_create(self, client: TestClient) -> None:
        client.post("/api/scorers/create", json={"description": "Be accurate", "name": "s1"})
        client.post("/api/scorers/create", json={"description": "Be fast", "name": "s2"})
        resp = client.get("/api/scorers")
        assert resp.status_code == 200
        assert len(resp.json()["scorers"]) == 2

    def test_get_scorer(self, client: TestClient) -> None:
        client.post("/api/scorers/create", json={"description": "Be accurate", "name": "get_me"})
        resp = client.get("/api/scorers/get_me")
        assert resp.status_code == 200
        assert resp.json()["scorer"]["name"] == "get_me"

    def test_get_scorer_not_found(self, client: TestClient) -> None:
        resp = client.get("/api/scorers/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Scorers — Refine
# ---------------------------------------------------------------------------


class TestScorerRefine:
    def test_refine_scorer(self, client: TestClient) -> None:
        client.post(
            "/api/scorers/create",
            json={"description": "Be accurate", "name": "refine_me"},
        )
        resp = client.post(
            "/api/scorers/refine_me/refine",
            json={"description": "Also check for empathy"},
        )
        assert resp.status_code == 200
        scorer = resp.json()["scorer"]
        assert scorer["version"] == 2

    def test_refine_nonexistent(self, client: TestClient) -> None:
        resp = client.post(
            "/api/scorers/nonexistent/refine",
            json={"description": "stuff"},
        )
        assert resp.status_code == 404

    def test_refine_missing_description(self, client: TestClient) -> None:
        client.post("/api/scorers/create", json={"description": "Be accurate", "name": "rd"})
        resp = client.post("/api/scorers/rd/refine", json={})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Scorers — Test
# ---------------------------------------------------------------------------


class TestScorerTest:
    def test_test_scorer(self, client: TestClient) -> None:
        client.post(
            "/api/scorers/create",
            json={"description": "The agent should respond accurately", "name": "test_me"},
        )
        resp = client.post(
            "/api/scorers/test_me/test",
            json={
                "eval_result": {
                    "case_id": "c1",
                    "passed": True,
                    "quality_score": 0.9,
                    "safety_passed": True,
                    "latency_ms": 200,
                    "token_count": 50,
                },
            },
        )
        assert resp.status_code == 200
        scores = resp.json()["scores"]
        assert "per_dimension" in scores
        assert "aggregate" in scores
        assert isinstance(scores["aggregate"], float)

    def test_test_scorer_not_found(self, client: TestClient) -> None:
        resp = client.post(
            "/api/scorers/nonexistent/test",
            json={"eval_result": {"case_id": "c1", "passed": True, "quality_score": 0.8, "safety_passed": True, "latency_ms": 100, "token_count": 10}},
        )
        assert resp.status_code == 404

    def test_test_scorer_missing_eval_result(self, client: TestClient) -> None:
        client.post("/api/scorers/create", json={"description": "Be good", "name": "tm"})
        resp = client.post("/api/scorers/tm/test", json={})
        assert resp.status_code == 400
