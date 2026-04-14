"""Tests for Builder Workspace API routes."""
from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.builder import router
from builder.events import EventBroker
from builder.execution import BuilderExecutionEngine
from builder.metrics import BuilderMetricsService
from builder.orchestrator import BuilderOrchestrator
from builder.permissions import PermissionManager
from builder.projects import BuilderProjectManager
from builder.store import BuilderStore


@pytest.fixture
def test_app(tmp_path):
    """Create a minimal FastAPI app with builder state for testing."""
    app = FastAPI()
    app.include_router(router)

    db_path = str(tmp_path / "test_builder.db")
    store = BuilderStore(db_path=db_path)
    events = EventBroker()
    orchestrator = BuilderOrchestrator(store=store)
    permissions = PermissionManager(store=store)
    project_manager = BuilderProjectManager(store=store)
    execution = BuilderExecutionEngine(
        store=store,
        orchestrator=orchestrator,
        permissions=permissions,
        events=events,
        worktree_root=str(tmp_path / "worktrees"),
    )
    metrics_service = BuilderMetricsService(store=store, permissions=permissions)

    app.state.builder_store = store
    app.state.builder_events = events
    app.state.builder_orchestrator = orchestrator
    app.state.builder_permissions = permissions
    app.state.builder_project_manager = project_manager
    app.state.builder_execution = execution
    app.state.builder_metrics = metrics_service

    return app


@pytest.fixture
def client(test_app):
    return TestClient(test_app)


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

class TestProjectsAPI:
    def test_create_project(self, client):
        resp = client.post("/api/builder/projects", json={"name": "My Project", "description": "Test"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "My Project"
        assert "project_id" in data

    def test_list_projects(self, client):
        client.post("/api/builder/projects", json={"name": "P1"})
        client.post("/api/builder/projects", json={"name": "P2"})
        resp = client.get("/api/builder/projects")
        assert resp.status_code == 200
        assert len(resp.json()) >= 2

    def test_get_project(self, client):
        create_resp = client.post("/api/builder/projects", json={"name": "Alpha"})
        project_id = create_resp.json()["project_id"]
        resp = client.get(f"/api/builder/projects/{project_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Alpha"

    def test_get_missing_project_404(self, client):
        resp = client.get("/api/builder/projects/nonexistent")
        assert resp.status_code == 404

    def test_update_project(self, client):
        create_resp = client.post("/api/builder/projects", json={"name": "Old"})
        project_id = create_resp.json()["project_id"]
        resp = client.patch(f"/api/builder/projects/{project_id}", json={"name": "New"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "New"

    def test_delete_project(self, client):
        create_resp = client.post("/api/builder/projects", json={"name": "ToDelete"})
        project_id = create_resp.json()["project_id"]
        resp = client.delete(f"/api/builder/projects/{project_id}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

class TestSessionsAPI:
    def _create_project(self, client):
        resp = client.post("/api/builder/projects", json={"name": "P"})
        return resp.json()["project_id"]

    def test_create_session(self, client):
        project_id = self._create_project(client)
        resp = client.post("/api/builder/sessions", json={"project_id": project_id, "title": "Session 1"})
        assert resp.status_code == 200
        assert "session_id" in resp.json()

    def test_list_sessions(self, client):
        project_id = self._create_project(client)
        client.post("/api/builder/sessions", json={"project_id": project_id})
        client.post("/api/builder/sessions", json={"project_id": project_id})
        resp = client.get(f"/api/builder/sessions?project_id={project_id}")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_get_session(self, client):
        project_id = self._create_project(client)
        create_resp = client.post("/api/builder/sessions", json={"project_id": project_id, "title": "S"})
        session_id = create_resp.json()["session_id"]
        resp = client.get(f"/api/builder/sessions/{session_id}")
        assert resp.status_code == 200

    def test_get_missing_session_404(self, client):
        resp = client.get("/api/builder/sessions/nonexistent")
        assert resp.status_code == 404

    def test_close_session(self, client):
        project_id = self._create_project(client)
        create_resp = client.post("/api/builder/sessions", json={"project_id": project_id})
        session_id = create_resp.json()["session_id"]
        resp = client.post(f"/api/builder/sessions/{session_id}/close")
        assert resp.status_code == 200
        assert resp.json()["status"] == "closed"


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

class TestTasksAPI:
    def _create_session(self, client):
        proj = client.post("/api/builder/projects", json={"name": "P"}).json()
        sess = client.post("/api/builder/sessions", json={"project_id": proj["project_id"]}).json()
        return proj["project_id"], sess["session_id"]

    def _create_task(self, client, project_id, session_id):
        return client.post("/api/builder/tasks", json={
            "project_id": project_id,
            "session_id": session_id,
            "title": "Do something",
            "description": "Detailed description",
            "mode": "ask",
        })

    def test_create_task(self, client):
        project_id, session_id = self._create_session(client)
        resp = self._create_task(client, project_id, session_id)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert data["title"] == "Do something"

    def test_get_task(self, client):
        project_id, session_id = self._create_session(client)
        task_id = self._create_task(client, project_id, session_id).json()["task_id"]
        resp = client.get(f"/api/builder/tasks/{task_id}")
        assert resp.status_code == 200

    def test_get_missing_task_404(self, client):
        resp = client.get("/api/builder/tasks/nonexistent")
        assert resp.status_code == 404

    def test_list_tasks_by_session(self, client):
        project_id, session_id = self._create_session(client)
        self._create_task(client, project_id, session_id)
        self._create_task(client, project_id, session_id)
        resp = client.get(f"/api/builder/tasks?session_id={session_id}")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_list_tasks_invalid_status_400(self, client):
        resp = client.get("/api/builder/tasks?status=invalid")
        assert resp.status_code == 400

    def test_pause_task(self, client):
        project_id, session_id = self._create_session(client)
        task_id = self._create_task(client, project_id, session_id).json()["task_id"]
        # Start then pause
        client.post(f"/api/builder/tasks/{task_id}/progress", json={"progress": 10, "current_step": "Starting"})
        resp = client.post(f"/api/builder/tasks/{task_id}/pause")
        assert resp.status_code == 200
        assert resp.json()["status"] == "paused"

    def test_resume_task(self, client):
        project_id, session_id = self._create_session(client)
        task_id = self._create_task(client, project_id, session_id).json()["task_id"]
        client.post(f"/api/builder/tasks/{task_id}/pause")
        resp = client.post(f"/api/builder/tasks/{task_id}/resume")
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"

    def test_cancel_task(self, client):
        project_id, session_id = self._create_session(client)
        task_id = self._create_task(client, project_id, session_id).json()["task_id"]
        resp = client.post(f"/api/builder/tasks/{task_id}/cancel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    def test_duplicate_task(self, client):
        project_id, session_id = self._create_session(client)
        task_id = self._create_task(client, project_id, session_id).json()["task_id"]
        resp = client.post(f"/api/builder/tasks/{task_id}/duplicate")
        assert resp.status_code == 200
        dup = resp.json()
        assert dup["task_id"] != task_id
        assert dup["duplicate_of_task_id"] == task_id

    def test_fork_task(self, client):
        project_id, session_id = self._create_session(client)
        task_id = self._create_task(client, project_id, session_id).json()["task_id"]
        resp = client.post(f"/api/builder/tasks/{task_id}/fork")
        assert resp.status_code == 200
        fork = resp.json()
        assert fork["task_id"] != task_id
        assert fork["forked_from_task_id"] == task_id


# ---------------------------------------------------------------------------
# Proposals
# ---------------------------------------------------------------------------

class TestProposalsAPI:
    def _create_proposal(self, client, store):
        from builder.types import BuilderProposal
        proposal = BuilderProposal(task_id="t1", session_id="s1", project_id="p1", goal="Proposal 1")
        store.save_proposal(proposal)
        return proposal

    def test_list_proposals(self, client, test_app):
        self._create_proposal(client, test_app.state.builder_store)
        resp = client.get("/api/builder/proposals")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_get_proposal(self, client, test_app):
        proposal = self._create_proposal(client, test_app.state.builder_store)
        resp = client.get(f"/api/builder/proposals/{proposal.proposal_id}")
        assert resp.status_code == 200

    def test_approve_proposal(self, client, test_app):
        proposal = self._create_proposal(client, test_app.state.builder_store)
        resp = client.post(f"/api/builder/proposals/{proposal.proposal_id}/approve")
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

    def test_reject_proposal(self, client, test_app):
        proposal = self._create_proposal(client, test_app.state.builder_store)
        resp = client.post(f"/api/builder/proposals/{proposal.proposal_id}/reject")
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

    def test_revise_proposal(self, client, test_app):
        proposal = self._create_proposal(client, test_app.state.builder_store)
        resp = client.post(f"/api/builder/proposals/{proposal.proposal_id}/revise", json={"comment": "Needs more detail"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["revision_count"] == 1
        assert "Needs more detail" in data["revision_comments"]


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------

class TestArtifactsAPI:
    def _create_artifact(self, store):
        from builder.types import ArtifactRef, ArtifactType
        artifact = ArtifactRef(task_id="t", session_id="s", project_id="p", artifact_type=ArtifactType.PLAN, title="Plan", summary="A plan")
        store.save_artifact(artifact)
        return artifact

    def test_list_artifacts(self, client, test_app):
        self._create_artifact(test_app.state.builder_store)
        resp = client.get("/api/builder/artifacts")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_get_artifact(self, client, test_app):
        artifact = self._create_artifact(test_app.state.builder_store)
        resp = client.get(f"/api/builder/artifacts/{artifact.artifact_id}")
        assert resp.status_code == 200
        assert resp.json()["artifact_type"] == "plan"

    def test_get_missing_artifact_404(self, client):
        resp = client.get("/api/builder/artifacts/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Approvals and permissions
# ---------------------------------------------------------------------------

class TestPermissionsAPI:
    def _create_approval(self, store):
        from builder.types import ApprovalRequest, PrivilegedAction
        approval = ApprovalRequest(task_id="t", session_id="s", project_id="p", action=PrivilegedAction.SOURCE_WRITE, description="Write access")
        store.save_approval(approval)
        return approval

    def test_list_approvals(self, client, test_app):
        self._create_approval(test_app.state.builder_store)
        resp = client.get("/api/builder/approvals")
        assert resp.status_code == 200

    def test_respond_approval_approve(self, client, test_app):
        approval = self._create_approval(test_app.state.builder_store)
        resp = client.post(
            f"/api/builder/approvals/{approval.approval_id}/respond",
            json={"approved": True, "responder": "admin"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

    def test_create_grant(self, client):
        resp = client.post("/api/builder/permissions/grants", json={
            "project_id": "proj-1",
            "action": "source_write",
            "scope": "task",
        })
        assert resp.status_code == 200
        assert resp.json()["action"] == "source_write"

    def test_list_grants(self, client):
        client.post("/api/builder/permissions/grants", json={"project_id": "proj-1", "action": "source_write", "scope": "once"})
        resp = client.get("/api/builder/permissions/grants?project_id=proj-1")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_revoke_grant(self, client):
        grant_resp = client.post("/api/builder/permissions/grants", json={"project_id": "proj-1", "action": "source_write", "scope": "once"})
        grant_id = grant_resp.json()["grant_id"]
        resp = client.delete(f"/api/builder/permissions/grants/{grant_id}")
        assert resp.status_code == 200
        assert resp.json()["revoked"] is True


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

class TestEventsAPI:
    def test_list_events(self, client):
        resp = client.get("/api/builder/events")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_stream_events_returns_streaming_response(self, client):
        resp = client.get("/api/builder/events/stream")
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

class TestMetricsAPI:
    def test_get_metrics(self, client):
        resp = client.get("/api/builder/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "session_count" in data
        assert "task_count" in data
        assert "acceptance_rate" in data

    def test_get_metrics_with_project(self, client):
        resp = client.get("/api/builder/metrics?project_id=proj-1")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Specialists
# ---------------------------------------------------------------------------

class TestSpecialistsAPI:
    def test_list_specialists(self, client):
        resp = client.get("/api/builder/specialists")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 13
        roles = [s["role"] for s in data]
        assert "build_engineer" in roles
        assert "optimization_engineer" in roles
        assert "eval_author" in roles
        assert "deployment_engineer" in roles

    def test_invoke_specialist(self, client, test_app):
        project_id = client.post("/api/builder/projects", json={"name": "P"}).json()["project_id"]
        session_id = client.post("/api/builder/sessions", json={"project_id": project_id}).json()["session_id"]
        task_id = client.post("/api/builder/tasks", json={
            "project_id": project_id, "session_id": session_id,
            "title": "T", "description": "D", "mode": "ask",
        }).json()["task_id"]

        resp = client.post(
            "/api/builder/specialists/eval_author/invoke",
            json={"task_id": task_id, "message": "write evals"},
        )
        assert resp.status_code == 200
        assert resp.json()["specialist"] == "eval_author"
        assert resp.json()["worker_capability"]["role"] == "eval_author"

    def test_create_coordinator_plan(self, client):
        project_id = client.post(
            "/api/builder/projects",
            json={
                "name": "P",
                "buildtime_skills": ["prompt_hardening"],
                "runtime_skills": ["order_lookup"],
            },
        ).json()["project_id"]
        session_id = client.post("/api/builder/sessions", json={"project_id": project_id}).json()["session_id"]
        task_id = client.post("/api/builder/tasks", json={
            "project_id": project_id,
            "session_id": session_id,
            "title": "T",
            "description": "D",
            "mode": "ask",
        }).json()["task_id"]

        resp = client.post(
            "/api/builder/coordinator/plan",
            json={
                "task_id": task_id,
                "goal": "Build, evaluate, optimize, and deploy a support agent",
                "materialize_tasks": True,
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "coordinator_worker"
        assert data["root_task_id"] == task_id
        assert any(entry["worker_role"] == "eval_author" for entry in data["tasks"])
        assert any(entry.get("materialized_task_id") for entry in data["tasks"])
        assert data["skill_context"]["buildtime_skills"] == ["prompt_hardening"]


# ---------------------------------------------------------------------------
# Coordinator execution
# ---------------------------------------------------------------------------

class TestCoordinatorExecutionAPI:
    def _setup_task_with_plan(self, client):
        project_resp = client.post(
            "/api/builder/projects",
            json={"name": "Exec Project", "buildtime_skills": ["prompt_hardening"]},
        )
        project_id = project_resp.json()["project_id"]
        session_resp = client.post(
            "/api/builder/sessions",
            json={"project_id": project_id, "title": "exec session"},
        )
        session_id = session_resp.json()["session_id"]
        task_resp = client.post(
            "/api/builder/tasks",
            json={
                "session_id": session_id,
                "project_id": project_id,
                "title": "build and eval",
                "description": "build and eval",
            },
        )
        task_id = task_resp.json()["task_id"]

        client.post(
            "/api/builder/coordinator/plan",
            json={
                "task_id": task_id,
                "goal": "Build an agent and add evals",
            },
        )
        return task_id

    def test_execute_plan_returns_completed_run(self, client):
        task_id = self._setup_task_with_plan(client)
        resp = client.post(
            "/api/builder/coordinator/execute",
            json={"task_id": task_id},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["task_id"] == task_id
        assert len(data["worker_states"]) > 0
        assert data["synthesis"]["completed_count"] > 0

    def test_get_execution_after_execute(self, client):
        task_id = self._setup_task_with_plan(client)
        client.post(
            "/api/builder/coordinator/execute",
            json={"task_id": task_id},
        )

        resp = client.get(f"/api/builder/coordinator/execution/{task_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"

    def test_get_execution_404_without_execution(self, client):
        project_resp = client.post(
            "/api/builder/projects", json={"name": "P"}
        )
        project_id = project_resp.json()["project_id"]
        session_resp = client.post(
            "/api/builder/sessions",
            json={"project_id": project_id},
        )
        session_id = session_resp.json()["session_id"]
        task_resp = client.post(
            "/api/builder/tasks",
            json={
                "session_id": session_id,
                "project_id": project_id,
                "title": "no plan",
                "description": "no plan",
            },
        )
        task_id = task_resp.json()["task_id"]

        resp = client.get(f"/api/builder/coordinator/execution/{task_id}")
        assert resp.status_code == 404

    def test_execute_without_plan_400(self, client):
        project_resp = client.post(
            "/api/builder/projects", json={"name": "P"}
        )
        project_id = project_resp.json()["project_id"]
        session_resp = client.post(
            "/api/builder/sessions",
            json={"project_id": project_id},
        )
        session_id = session_resp.json()["session_id"]
        task_resp = client.post(
            "/api/builder/tasks",
            json={
                "session_id": session_id,
                "project_id": project_id,
                "title": "no plan",
                "description": "no plan",
            },
        )
        task_id = task_resp.json()["task_id"]

        resp = client.post(
            "/api/builder/coordinator/execute",
            json={"task_id": task_id},
        )
        assert resp.status_code == 400

    def test_execute_with_nonexistent_task_404(self, client):
        resp = client.post(
            "/api/builder/coordinator/execute",
            json={"task_id": "nonexistent-id"},
        )
        assert resp.status_code == 404
