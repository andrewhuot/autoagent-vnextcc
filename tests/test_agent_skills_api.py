"""Tests for agent skill generation API endpoints."""
from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.agent_skills import router
from agent_skills.store import AgentSkillStore
from agent_skills.types import GeneratedFile, GeneratedSkill


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(tmp_path) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.agent_skill_store = AgentSkillStore(db_path=str(tmp_path / "test.db"))
    app.state.agent_skills_apply_root = str(tmp_path)
    return app


def _make_skill(**overrides) -> GeneratedSkill:
    defaults: dict = {
        "skill_id": "test123",
        "gap_id": "gap456",
        "platform": "adk",
        "skill_type": "tool",
        "name": "check_warranty",
        "description": "Check warranty status",
        "source_code": "def check_warranty(): pass",
        "files": [
            GeneratedFile(
                path="tools/check_warranty.py",
                content="def check_warranty(): pass",
                is_new=True,
            )
        ],
    }
    defaults.update(overrides)
    return GeneratedSkill(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAgentSkillsAPI:
    def test_list_empty(self, tmp_path):
        app = _make_app(tmp_path)
        client = TestClient(app)
        resp = client.get("/api/agent-skills/")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_get_not_found(self, tmp_path):
        app = _make_app(tmp_path)
        client = TestClient(app)
        resp = client.get("/api/agent-skills/nonexistent")
        assert resp.status_code == 404

    def test_save_and_list(self, tmp_path):
        app = _make_app(tmp_path)
        store = app.state.agent_skill_store
        skill = _make_skill()
        store.save(skill)

        client = TestClient(app)
        resp = client.get("/api/agent-skills/")
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

    def test_get_skill(self, tmp_path):
        app = _make_app(tmp_path)
        store = app.state.agent_skill_store
        skill = _make_skill()
        store.save(skill)

        client = TestClient(app)
        resp = client.get("/api/agent-skills/test123")
        assert resp.status_code == 200
        assert resp.json()["skill"]["name"] == "check_warranty"

    def test_approve(self, tmp_path):
        app = _make_app(tmp_path)
        store = app.state.agent_skill_store
        store.save(_make_skill())

        client = TestClient(app)
        resp = client.post("/api/agent-skills/test123/approve")
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

    def test_reject(self, tmp_path):
        app = _make_app(tmp_path)
        store = app.state.agent_skill_store
        store.save(_make_skill())

        client = TestClient(app)
        resp = client.post("/api/agent-skills/test123/reject", json={"reason": "Not needed"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

    def test_list_gaps_empty(self, tmp_path):
        app = _make_app(tmp_path)
        client = TestClient(app)
        resp = client.get("/api/agent-skills/gaps")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_filter_by_status(self, tmp_path):
        app = _make_app(tmp_path)
        store = app.state.agent_skill_store
        store.save(_make_skill(skill_id="s1", status="draft"))
        store.save(_make_skill(skill_id="s2", status="approved"))

        client = TestClient(app)
        resp = client.get("/api/agent-skills/?status=draft")
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

    def test_apply_unapproved(self, tmp_path):
        app = _make_app(tmp_path)
        store = app.state.agent_skill_store
        store.save(_make_skill())  # status=draft

        client = TestClient(app)
        resp = client.post("/api/agent-skills/test123/apply", json={"target": str(tmp_path)})
        assert resp.status_code == 400

    def test_apply_approved_writes_files(self, tmp_path):
        app = _make_app(tmp_path)
        store = app.state.agent_skill_store
        skill = _make_skill()
        store.save(skill)
        store.approve("test123")

        target = tmp_path / "output"
        target.mkdir()

        client = TestClient(app)
        resp = client.post(
            "/api/agent-skills/test123/apply", json={"target": str(target)}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "applied"
        assert len(data["files_written"]) == 1
        assert (target / "tools" / "check_warranty.py").exists()

    def test_apply_rejects_absolute_generated_file_paths(self, tmp_path):
        app = _make_app(tmp_path)
        store = app.state.agent_skill_store
        escaped_path = (tmp_path.parent / "owned-by-skill.txt").resolve()
        escaped_path.unlink(missing_ok=True)

        skill = _make_skill(
            files=[
                GeneratedFile(
                    path=str(escaped_path),
                    content="owned\n",
                    is_new=True,
                )
            ]
        )
        store.save(skill)
        store.approve("test123")

        client = TestClient(app)
        resp = client.post("/api/agent-skills/test123/apply", json={"target": str(tmp_path / "output")})

        assert resp.status_code == 400
        assert "relative" in resp.json()["detail"].lower()
        assert not escaped_path.exists()

    def test_apply_rejects_paths_that_escape_target_directory(self, tmp_path):
        app = _make_app(tmp_path)
        store = app.state.agent_skill_store
        escaped_path = tmp_path / "output" / ".." / "escape.py"
        escaped_path.resolve().unlink(missing_ok=True)

        skill = _make_skill(
            files=[
                GeneratedFile(
                    path="../escape.py",
                    content="owned\n",
                    is_new=True,
                )
            ]
        )
        store.save(skill)
        store.approve("test123")

        client = TestClient(app)
        resp = client.post("/api/agent-skills/test123/apply", json={"target": str(tmp_path / "output")})

        assert resp.status_code == 400
        assert "escapes workspace root" in resp.json()["detail"].lower()
        assert not (tmp_path / "escape.py").exists()

    def test_apply_rejects_target_outside_workspace_root(self, tmp_path):
        app = _make_app(tmp_path)
        store = app.state.agent_skill_store
        store.save(_make_skill())
        store.approve("test123")

        outside_target = tmp_path.parent / "outside-output"
        outside_target.mkdir(exist_ok=True)

        client = TestClient(app)
        resp = client.post("/api/agent-skills/test123/apply", json={"target": str(outside_target)})

        assert resp.status_code == 400
        assert "escapes workspace root" in resp.json()["detail"].lower()

    def test_approve_not_found(self, tmp_path):
        app = _make_app(tmp_path)
        client = TestClient(app)
        resp = client.post("/api/agent-skills/nonexistent/approve")
        assert resp.status_code == 404

    def test_reject_not_found(self, tmp_path):
        app = _make_app(tmp_path)
        client = TestClient(app)
        resp = client.post("/api/agent-skills/nonexistent/reject", json={"reason": "gone"})
        assert resp.status_code == 404

    def test_apply_not_found(self, tmp_path):
        app = _make_app(tmp_path)
        client = TestClient(app)
        resp = client.post("/api/agent-skills/nonexistent/apply", json={"target": str(tmp_path)})
        assert resp.status_code == 404

    def test_filter_by_platform(self, tmp_path):
        app = _make_app(tmp_path)
        store = app.state.agent_skill_store
        store.save(_make_skill(skill_id="a1", platform="adk"))
        store.save(_make_skill(skill_id="c1", platform="cx"))

        client = TestClient(app)
        resp = client.get("/api/agent-skills/?platform=adk")
        assert resp.status_code == 200
        assert resp.json()["count"] == 1
        assert resp.json()["skills"][0]["platform"] == "adk"

    def test_503_when_no_store(self) -> None:
        bare_app = FastAPI()
        bare_app.include_router(router)
        c = TestClient(bare_app, raise_server_exceptions=False)
        resp = c.get("/api/agent-skills/")
        assert resp.status_code == 503

    def test_list_gaps_after_save(self, tmp_path):
        from agent_skills.types import SkillGap

        app = _make_app(tmp_path)
        store = app.state.agent_skill_store
        gap = SkillGap(
            gap_id="g1",
            gap_type="missing_tool",
            description="Need warranty tool",
            evidence=["conv-1"],
            failure_family="tool_error",
            frequency=3,
            impact_score=0.7,
            suggested_name="check_warranty",
            suggested_platform="adk",
        )
        store.save_gap(gap)

        client = TestClient(app)
        resp = client.get("/api/agent-skills/gaps")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["gaps"][0]["gap_id"] == "g1"
