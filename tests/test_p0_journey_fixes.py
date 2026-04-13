"""Tests for P0 end-to-end journey fixes.

Covers:
1. TaskManager SQLite persistence (history survives restart)
2. Deploy promote endpoint
3. Connect import registration with running server
4. BuilderChatService session persistence
"""

from __future__ import annotations

import json
import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

# ---------------------------------------------------------------------------
# Fix 1: TaskManager persistence
# ---------------------------------------------------------------------------


class TestTaskManagerPersistence:
    """TaskManager should persist tasks to SQLite and reload them on restart."""

    def test_completed_task_survives_restart(self, tmp_path: Path) -> None:
        """A completed task should be visible after creating a new TaskManager."""
        from api.tasks import TaskManager

        db_path = str(tmp_path / "tasks.db")
        manager = TaskManager(db_path=db_path)

        task = manager.create_task("eval", lambda t: {"composite": 0.85})
        task._thread.join(timeout=5)

        assert task.status == "completed"
        assert task.result == {"composite": 0.85}

        # Simulate restart: create a new manager pointing at the same DB
        manager2 = TaskManager(db_path=db_path)
        reloaded = manager2.get_task(task.task_id)

        assert reloaded is not None
        assert reloaded.task_id == task.task_id
        assert reloaded.task_type == "eval"
        assert reloaded.status == "completed"
        assert reloaded.progress == 100
        assert reloaded.result == {"composite": 0.85}

    def test_running_task_marked_interrupted_on_restart(self, tmp_path: Path) -> None:
        """A task that was running when the server stopped should be marked interrupted."""
        from api.tasks import TaskManager
        import sqlite3

        db_path = str(tmp_path / "tasks.db")

        # Manually insert a "running" task into the DB
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY, task_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending', progress INTEGER NOT NULL DEFAULT 0,
                    result TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                )
            """)
            conn.execute(
                "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("test-abc", "optimize", "running", 50, None, None,
                 "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
            )

        # Loading the manager should mark it interrupted
        manager = TaskManager(db_path=db_path)
        task = manager.get_task("test-abc")
        assert task is not None
        assert task.status == "interrupted"

    def test_interrupted_task_exposes_restart_recovery_context(self, tmp_path: Path) -> None:
        """Interrupted tasks should explain the restart state to API consumers."""
        from api.tasks import TaskManager
        import sqlite3

        db_path = str(tmp_path / "tasks.db")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY, task_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending', progress INTEGER NOT NULL DEFAULT 0,
                    result TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                )
            """)
            conn.execute(
                "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("restart-eval", "eval", "running", 40, None, None,
                 "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
            )

        manager = TaskManager(db_path=db_path)
        task = manager.get_task("restart-eval")

        assert task is not None
        payload = task.to_dict()
        assert payload["status"] == "interrupted"
        assert payload["continuity_state"] == "interrupted"
        assert payload["state_label"] == "Interrupted after restart"
        assert "server restart" in payload["state_detail"]
        assert "Start a new run" in (payload["error"] or "")

    def test_interrupted_task_exposes_restart_continuity_metadata(self, tmp_path: Path) -> None:
        """Interrupted tasks should explain that restart stopped live work."""
        from api.tasks import TaskManager
        import sqlite3

        db_path = str(tmp_path / "tasks.db")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY, task_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending', progress INTEGER NOT NULL DEFAULT 0,
                    result TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                )
            """)
            conn.execute(
                "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("eval-restart", "eval", "running", 42, None, None,
                 "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
            )

        manager = TaskManager(db_path=db_path)
        task = manager.get_task("eval-restart")

        assert task is not None
        payload = task.to_dict()
        assert payload["status"] == "interrupted"
        assert payload["continuity"] == {
            "state": "interrupted",
            "label": "Interrupted by restart",
            "detail": "This task was pending or running when the server restarted. It did not finish; rerun it to continue.",
            "is_live": False,
            "is_historical": True,
            "can_rerun": True,
        }

    def test_completed_task_exposes_historical_continuity_metadata(self, tmp_path: Path) -> None:
        """Completed tasks should be labeled as durable historical state."""
        from api.tasks import TaskManager

        db_path = str(tmp_path / "tasks.db")
        manager = TaskManager(db_path=db_path)

        task = manager.create_task("eval", lambda t: {"composite": 0.85})
        task._thread.join(timeout=5)

        payload = task.to_dict()
        assert payload["continuity"]["state"] == "historical"
        assert payload["continuity"]["label"] == "Historical task"
        assert payload["continuity"]["is_live"] is False
        assert payload["continuity"]["is_historical"] is True
        assert payload["continuity"]["can_rerun"] is False

    def test_failed_task_persists_error(self, tmp_path: Path) -> None:
        """A failed task should persist its error message."""
        from api.tasks import TaskManager

        db_path = str(tmp_path / "tasks.db")
        manager = TaskManager(db_path=db_path)

        def failing_fn(t):
            raise ValueError("eval runner exploded")

        task = manager.create_task("eval", failing_fn)
        task._thread.join(timeout=5)

        assert task.status == "failed"
        assert "eval runner exploded" in task.error

        # Reload
        manager2 = TaskManager(db_path=db_path)
        reloaded = manager2.get_task(task.task_id)
        assert reloaded.status == "failed"
        assert "eval runner exploded" in reloaded.error

    def test_list_tasks_filters_by_type(self, tmp_path: Path) -> None:
        """list_tasks should filter by task_type."""
        from api.tasks import TaskManager

        db_path = str(tmp_path / "tasks.db")
        manager = TaskManager(db_path=db_path)

        t1 = manager.create_task("eval", lambda t: {"score": 0.9})
        t2 = manager.create_task("optimize", lambda t: {"improved": True})
        t1._thread.join(timeout=5)
        t2._thread.join(timeout=5)

        eval_tasks = manager.list_tasks(task_type="eval")
        assert len(eval_tasks) == 1
        assert eval_tasks[0].task_type == "eval"

        all_tasks = manager.list_tasks()
        assert len(all_tasks) == 2

    def test_update_task_persists(self, tmp_path: Path) -> None:
        """update_task should write changes to the database."""
        from api.tasks import TaskManager

        db_path = str(tmp_path / "tasks.db")
        manager = TaskManager(db_path=db_path)

        task = manager.create_task("eval", lambda t: None)
        task._thread.join(timeout=5)

        manager.update_task(task.task_id, progress=75, status="running")

        # Reload
        manager2 = TaskManager(db_path=db_path)
        reloaded = manager2.get_task(task.task_id)
        # It was "running" when we stopped, so it gets marked interrupted
        assert reloaded.status == "interrupted"


# ---------------------------------------------------------------------------
# Fix 2: Deploy promote endpoint
# ---------------------------------------------------------------------------


class TestDeployPromoteEndpoint:
    """The /api/deploy/promote endpoint should promote a canary to active."""

    @pytest.fixture
    def deploy_client(self, tmp_path: Path, base_config: dict):
        fastapi = pytest.importorskip("fastapi")
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from api.routes.deploy import router
        from deployer.canary import Deployer
        from deployer.versioning import ConfigVersionManager
        from logger.store import ConversationStore

        app = FastAPI()
        app.include_router(router)

        store = ConversationStore(str(tmp_path / "conversations.db"))
        vm = ConfigVersionManager(str(tmp_path / "configs"))
        deployer = Deployer(configs_dir=str(tmp_path / "configs"), store=store)

        # Save active version
        vm.save_version(base_config, scores={"composite": 0.7}, status="active")

        # Save canary version
        canary_config = deepcopy(base_config)
        canary_config["prompts"]["root"] = canary_config["prompts"]["root"] + " Be clear."
        vm.save_version(canary_config, scores={"composite": 0.8}, status="canary")

        app.state.version_manager = vm
        app.state.deployer = deployer
        return TestClient(app)

    def test_promote_canary_succeeds(self, deploy_client, tmp_path: Path) -> None:
        """POST /api/deploy/promote should promote the canary to active."""
        response = deploy_client.post("/api/deploy/promote")
        assert response.status_code == 200
        payload = response.json()
        assert "Promoted" in payload["message"]
        assert payload["version"] == 2

    def test_promote_specific_version_via_body(self, deploy_client, tmp_path: Path) -> None:
        """POST /api/deploy/promote with JSON body {version: 2} should promote."""
        response = deploy_client.post("/api/deploy/promote", json={"version": 2})
        assert response.status_code == 200
        assert response.json()["version"] == 2

    def test_promote_fails_without_canary(self, tmp_path: Path, base_config: dict) -> None:
        """Promote should fail when no canary exists."""
        fastapi = pytest.importorskip("fastapi")
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from api.routes.deploy import router
        from deployer.canary import Deployer
        from deployer.versioning import ConfigVersionManager
        from logger.store import ConversationStore

        app = FastAPI()
        app.include_router(router)

        store = ConversationStore(str(tmp_path / "conversations.db"))
        vm = ConfigVersionManager(str(tmp_path / "configs"))
        deployer = Deployer(configs_dir=str(tmp_path / "configs"), store=store)
        vm.save_version(base_config, scores={"composite": 0.7}, status="active")

        app.state.version_manager = vm
        app.state.deployer = deployer

        client = TestClient(app)
        response = client.post("/api/deploy/promote")
        assert response.status_code == 400

    def test_deploy_status_refreshes_versions_created_after_deployer_start(
        self,
        tmp_path: Path,
        base_config: dict,
    ) -> None:
        """Deploy status should include versions materialized by Build/Workbench."""
        fastapi = pytest.importorskip("fastapi")
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from api.routes.deploy import router
        from deployer.canary import Deployer
        from deployer.versioning import ConfigVersionManager
        from logger.store import ConversationStore

        configs_dir = tmp_path / "configs"
        store = ConversationStore(str(tmp_path / "conversations.db"))
        deployer = Deployer(configs_dir=str(configs_dir), store=store)
        vm = ConfigVersionManager(str(configs_dir))
        vm.save_version(base_config, scores={"composite": 0.7}, status="candidate")

        app = FastAPI()
        app.include_router(router)
        app.state.version_manager = vm
        app.state.deployer = deployer

        response = TestClient(app).get("/api/deploy/status")

        assert response.status_code == 200
        payload = response.json()
        assert payload["total_versions"] == 1
        assert payload["history"][0]["version"] == 1

    def test_deploy_canaries_selected_existing_version_without_duplication(
        self,
        tmp_path: Path,
        base_config: dict,
    ) -> None:
        """Deploying a selected saved version should not create a duplicate."""
        fastapi = pytest.importorskip("fastapi")
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from api.routes.deploy import router
        from deployer.canary import Deployer
        from deployer.versioning import ConfigVersionManager
        from logger.store import ConversationStore

        configs_dir = tmp_path / "configs"
        store = ConversationStore(str(tmp_path / "conversations.db"))
        deployer = Deployer(configs_dir=str(configs_dir), store=store)
        vm = ConfigVersionManager(str(configs_dir))
        version = vm.save_version(
            base_config,
            scores={"composite": 0.7},
            status="candidate",
        ).version

        app = FastAPI()
        app.include_router(router)
        app.state.version_manager = vm
        app.state.deployer = deployer

        client = TestClient(app)
        response = client.post(
            "/api/deploy",
            json={"version": version, "strategy": "canary"},
        )

        assert response.status_code == 201
        payload = response.json()
        assert payload["version"] == version
        assert payload["strategy"] == "canary"

        status_response = client.get("/api/deploy/status")
        assert status_response.status_code == 200
        status_payload = status_response.json()
        assert status_payload["canary_version"] == version
        assert status_payload["total_versions"] == 1
        assert [item["version"] for item in status_payload["history"]] == [version]
        assert status_payload["history"][0]["status"] == "canary"


# ---------------------------------------------------------------------------
# Fix 3: Connect import registers with running server
# ---------------------------------------------------------------------------


class TestConnectImportRegistration:
    """Imported agents should be registered with the running server."""

    def test_transcript_import_registers_with_version_manager(self, tmp_path: Path) -> None:
        """After transcript import, the agent should appear in the version manager."""
        fastapi = pytest.importorskip("fastapi")
        try:
            from api.routes import connect as connect_routes
        except TypeError:
            pytest.skip("Import chain requires Python 3.11+ (dataclass slots)")
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from deployer.versioning import ConfigVersionManager

        transcript_file = tmp_path / "conversations.jsonl"
        transcript_file.write_text(
            json.dumps({
                "id": "conv-1",
                "messages": [
                    {"role": "user", "content": "Where is my order?"},
                    {"role": "assistant", "content": "Your order shipped yesterday."},
                ],
            }) + "\n",
            encoding="utf-8",
        )

        app = FastAPI()
        app.include_router(connect_routes.router)

        # Set up version manager on the running server
        vm = ConfigVersionManager(str(tmp_path / "server_configs"))
        app.state.version_manager = vm

        client = TestClient(app)

        response = client.post(
            "/api/connect/import",
            json={
                "adapter": "transcript",
                "file": str(transcript_file),
                "output_dir": str(tmp_path),
                "workspace_name": "api-connect-test",
            },
        )

        assert response.status_code == 201
        payload = response.json()

        # The imported agent should now be registered
        assert payload.get("registered_version") is not None
        assert payload["registered_version"] >= 1

        # Verify the version manager has the new version
        versions = vm.get_version_history()
        assert len(versions) == 1
        assert versions[0]["status"] == "candidate"


# ---------------------------------------------------------------------------
# Fix 4: BuilderChatService session persistence
# ---------------------------------------------------------------------------


class TestBuilderChatSessionPersistence:
    """BuilderChatService should persist sessions to SQLite."""

    def test_session_survives_service_recreation(self, tmp_path: Path) -> None:
        """A chat session should be recoverable after creating a new service."""
        try:
            from builder.chat_service import BuilderChatService
        except TypeError:
            pytest.skip("Import chain requires Python 3.11+ (dataclass slots)")

        db_path = str(tmp_path / "chat_sessions.db")

        service1 = BuilderChatService(db_path=db_path)
        result = service1.handle_message("Build me a customer support agent")
        session_id = result["session_id"]

        assert result["config"]["agent_name"]
        assert len(result["messages"]) >= 2

        # Simulate restart
        service2 = BuilderChatService(db_path=db_path)
        recovered = service2.get_session(session_id)

        assert recovered is not None
        assert recovered["session_id"] == session_id
        assert len(recovered["messages"]) >= 2
        assert recovered["config"]["agent_name"]
        assert recovered["continuity"]["state"] == "historical"
        assert recovered["continuity"]["label"] == "Historical session"
        assert recovered["continuity"]["is_live"] is False

    def test_list_sessions_returns_recent(self, tmp_path: Path) -> None:
        """list_sessions should return a summary of recent sessions."""
        try:
            from builder.chat_service import BuilderChatService
        except TypeError:
            pytest.skip("Import chain requires Python 3.11+ (dataclass slots)")

        db_path = str(tmp_path / "chat_sessions.db")
        service = BuilderChatService(db_path=db_path)

        service.handle_message("Build me an airline agent")
        service.handle_message("Build me a banking agent")

        sessions = service.list_sessions()
        assert len(sessions) == 2
        assert all("session_id" in s for s in sessions)
        assert all("agent_name" in s for s in sessions)

    def test_list_sessions_marks_recovered_history_as_resumable(self, tmp_path: Path) -> None:
        """Session summaries should tell the UI that persisted chats are resumable history."""
        try:
            from builder.chat_service import BuilderChatService
        except TypeError:
            pytest.skip("Import chain requires Python 3.11+ (dataclass slots)")

        db_path = str(tmp_path / "chat_sessions.db")
        service1 = BuilderChatService(db_path=db_path)
        created = service1.handle_message("Build me a durable restart agent")

        service2 = BuilderChatService(db_path=db_path)
        sessions = service2.list_sessions()

        assert sessions
        summary = next(item for item in sessions if item["session_id"] == created["session_id"])
        assert summary["continuity_state"] == "historical"
        assert summary["state_label"] == "Historical session"
        assert summary["can_resume"] is True
        assert "Resume" in summary["state_detail"]
        assert all(s["continuity"]["state"] == "historical" for s in sessions)

    def test_follow_up_message_persists(self, tmp_path: Path) -> None:
        """Follow-up messages in a session should persist across restarts."""
        try:
            from builder.chat_service import BuilderChatService
        except TypeError:
            pytest.skip("Import chain requires Python 3.11+ (dataclass slots)")

        db_path = str(tmp_path / "chat_sessions.db")
        service1 = BuilderChatService(db_path=db_path)

        result = service1.handle_message("Build me a customer support agent")
        session_id = result["session_id"]

        service1.handle_message("Add a tool for order lookup", session_id=session_id)

        # Reload
        service2 = BuilderChatService(db_path=db_path)
        recovered = service2.get_session(session_id)

        assert recovered is not None
        # Should have: welcome, user1, assistant1, user2, assistant2
        assert len(recovered["messages"]) >= 4

    def test_restarted_session_summary_exposes_historical_state(self, tmp_path: Path) -> None:
        """Session lists should make restart-resumed history discoverable."""
        try:
            from builder.chat_service import BuilderChatService
        except TypeError:
            pytest.skip("Import chain requires Python 3.11+ (dataclass slots)")

        db_path = str(tmp_path / "chat_sessions.db")
        service1 = BuilderChatService(db_path=db_path)
        created = service1.handle_message("Build me a customer support agent")

        service2 = BuilderChatService(db_path=db_path)
        sessions = service2.list_sessions()

        assert sessions[0]["session_id"] == created["session_id"]
        assert sessions[0]["continuity"] == {
            "state": "historical",
            "label": "Historical session",
            "detail": "This builder chat was restored from durable storage after restart. Resume it to continue editing.",
            "is_live": False,
        }


# ---------------------------------------------------------------------------
# Fix 2 supplement: ConfigVersionManager.reload()
# ---------------------------------------------------------------------------


class TestVersionManagerReload:
    """ConfigVersionManager should support reloading its manifest from disk."""

    def test_reload_picks_up_external_changes(self, tmp_path: Path, base_config: dict) -> None:
        """After another process modifies the manifest, reload() should see changes."""
        from deployer.versioning import ConfigVersionManager

        vm1 = ConfigVersionManager(str(tmp_path / "configs"))
        vm1.save_version(base_config, scores={"composite": 0.7}, status="active")

        # A second instance saves a new version
        vm2 = ConfigVersionManager(str(tmp_path / "configs"))
        vm2.save_version(base_config, scores={"composite": 0.8}, status="canary")

        # vm1 doesn't see it yet
        assert len(vm1.get_version_history()) == 1

        # After reload, vm1 sees both
        vm1.reload()
        assert len(vm1.get_version_history()) == 2
