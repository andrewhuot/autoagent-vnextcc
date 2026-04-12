"""Tests for BuilderExecutionEngine."""
from __future__ import annotations

import pytest

from builder.execution import BuilderExecutionEngine
from builder.events import EventBroker
from builder.orchestrator import BuilderOrchestrator
from builder.permissions import PermissionManager
from builder.store import BuilderStore
from builder.types import ExecutionMode, TaskStatus


@pytest.fixture
def store(tmp_path):
    return BuilderStore(db_path=str(tmp_path / "execution.db"))


@pytest.fixture
def events():
    return EventBroker()


@pytest.fixture
def orchestrator(store):
    return BuilderOrchestrator(store=store)


@pytest.fixture
def permissions(store):
    return PermissionManager(store=store)


@pytest.fixture
def engine(store, orchestrator, permissions, events, tmp_path):
    return BuilderExecutionEngine(
        store=store,
        orchestrator=orchestrator,
        permissions=permissions,
        events=events,
        worktree_root=str(tmp_path / "worktrees"),
    )


@pytest.fixture
def session(store):
    from builder.types import BuilderSession
    session = BuilderSession(project_id="proj-1", title="Test")
    store.save_session(session)
    return session


class TestCreateTask:
    def test_creates_pending_task(self, engine, session):
        task = engine.create_task(
            session_id=session.session_id,
            project_id="proj-1",
            title="Write tests",
            description="Write comprehensive tests",
            mode=ExecutionMode.APPLY,
        )
        assert task.task_id != ""
        assert task.status == TaskStatus.PENDING
        assert task.title == "Write tests"
        assert task.mode == ExecutionMode.APPLY

    def test_task_added_to_session(self, engine, store, session):
        task = engine.create_task(
            session_id=session.session_id,
            project_id="proj-1",
            title="T",
            description="D",
            mode=ExecutionMode.ASK,
        )
        updated_session = store.get_session(session.session_id)
        assert task.task_id in updated_session.task_ids

    def test_delegate_mode_provisions_worktree(self, engine, store, session):
        task = engine.create_task(
            session_id=session.session_id,
            project_id="proj-1",
            title="Delegate task",
            description="Run in isolation",
            mode=ExecutionMode.DELEGATE,
        )
        assert task.worktree_ref is not None
        worktree = store.get_worktree(task.worktree_ref)
        assert worktree is not None
        assert worktree.task_id == task.task_id


class TestTaskLifecycle:
    def test_start_task(self, engine, session):
        task = engine.create_task(session_id=session.session_id, project_id="p", title="T", description="D", mode=ExecutionMode.ASK)
        started = engine.start_task(task.task_id)
        assert started.status == TaskStatus.RUNNING
        assert started.started_at is not None

    def test_pause_running_task(self, engine, session):
        task = engine.create_task(session_id=session.session_id, project_id="p", title="T", description="D", mode=ExecutionMode.ASK)
        engine.start_task(task.task_id)
        paused = engine.pause_task(task.task_id, reason="user requested pause")
        assert paused.status == TaskStatus.PAUSED

    def test_resume_paused_task(self, engine, session):
        task = engine.create_task(session_id=session.session_id, project_id="p", title="T", description="D", mode=ExecutionMode.ASK)
        engine.start_task(task.task_id)
        engine.pause_task(task.task_id)
        resumed = engine.resume_task(task.task_id)
        assert resumed.status == TaskStatus.RUNNING

    def test_cancel_task(self, engine, session):
        task = engine.create_task(session_id=session.session_id, project_id="p", title="T", description="D", mode=ExecutionMode.ASK)
        engine.start_task(task.task_id)
        cancelled = engine.cancel_task(task.task_id, reason="no longer needed")
        assert cancelled.status == TaskStatus.CANCELLED

    def test_complete_task(self, engine, session):
        task = engine.create_task(session_id=session.session_id, project_id="p", title="T", description="D", mode=ExecutionMode.ASK)
        engine.start_task(task.task_id)
        completed = engine.complete_task(task.task_id, artifact_ids=["art-1", "art-2"])
        assert completed.status == TaskStatus.COMPLETED
        assert completed.artifact_ids == ["art-1", "art-2"]
        assert completed.progress == 100

    def test_fail_task(self, engine, session):
        task = engine.create_task(session_id=session.session_id, project_id="p", title="T", description="D", mode=ExecutionMode.ASK)
        engine.start_task(task.task_id)
        failed = engine.fail_task(task.task_id, error="Unexpected exception")
        assert failed.status == TaskStatus.FAILED
        assert failed.error == "Unexpected exception"

    def test_start_missing_task_returns_none(self, engine):
        assert engine.start_task("nonexistent") is None

    def test_pause_missing_task_returns_none(self, engine):
        assert engine.pause_task("nonexistent") is None


class TestDuplicateAndFork:
    def test_duplicate_task(self, engine, session):
        original = engine.create_task(session_id=session.session_id, project_id="p", title="Original", description="D", mode=ExecutionMode.ASK)
        duplicate = engine.duplicate_task(original.task_id)
        assert duplicate is not None
        assert duplicate.task_id != original.task_id
        assert duplicate.duplicate_of_task_id == original.task_id
        assert "copy" in duplicate.title.lower()

    def test_fork_task(self, engine, session):
        original = engine.create_task(session_id=session.session_id, project_id="p", title="Original", description="D", mode=ExecutionMode.ASK)
        fork = engine.fork_task(original.task_id)
        assert fork is not None
        assert fork.task_id != original.task_id
        assert fork.forked_from_task_id == original.task_id
        assert "fork" in fork.title.lower()

    def test_fork_with_different_mode(self, engine, session):
        original = engine.create_task(session_id=session.session_id, project_id="p", title="T", description="D", mode=ExecutionMode.ASK)
        fork = engine.fork_task(original.task_id, mode=ExecutionMode.APPLY)
        assert fork.mode == ExecutionMode.APPLY

    def test_duplicate_missing_returns_none(self, engine):
        assert engine.duplicate_task("nonexistent") is None

    def test_fork_missing_returns_none(self, engine):
        assert engine.fork_task("nonexistent") is None


class TestProgressUpdate:
    def test_progress_task(self, engine, session):
        task = engine.create_task(session_id=session.session_id, project_id="p", title="T", description="D", mode=ExecutionMode.ASK)
        engine.start_task(task.task_id)
        updated = engine.progress_task(task.task_id, progress=50, current_step="Running evals")
        assert updated.progress == 50
        assert updated.current_step == "Running evals"

    def test_progress_100_requires_completion_evidence(self, engine, events, session):
        task = engine.create_task(session_id=session.session_id, project_id="p", title="T", description="D", mode=ExecutionMode.ASK)
        engine.start_task(task.task_id)
        updated = engine.progress_task(task.task_id, progress=150, current_step="Done")
        assert updated.progress == 99
        assert updated.status == TaskStatus.RUNNING
        assert updated.metadata["progress_clamped_from"] == 150
        assert "completion evidence" in updated.metadata["completion_blocked_reason"]

        published = events.list_events(session_id=session.session_id)
        progress_events = [event for event in published if event.task_id == task.task_id]
        assert progress_events[-1].payload["progress"] == 99
        assert progress_events[-1].payload["completion_blocked_reason"] == updated.metadata["completion_blocked_reason"]

    def test_progress_allows_100_with_completion_evidence(self, engine, store, session):
        task = engine.create_task(session_id=session.session_id, project_id="p", title="T", description="D", mode=ExecutionMode.ASK)
        engine.start_task(task.task_id)
        task.artifact_ids.append("art-1")
        store.save_task(task)

        updated = engine.progress_task(task.task_id, progress=100, current_step="Artifact verified")

        assert updated.progress == 100
        assert "completion_blocked_reason" not in updated.metadata

    def test_complete_task_clears_progress_blocker_metadata(self, engine, session):
        task = engine.create_task(session_id=session.session_id, project_id="p", title="T", description="D", mode=ExecutionMode.ASK)
        engine.start_task(task.task_id)
        clamped = engine.progress_task(task.task_id, progress=100, current_step="Done")
        assert clamped.progress == 99

        completed = engine.complete_task(task.task_id, artifact_ids=["art-1"])

        assert completed.progress == 100
        assert completed.status == TaskStatus.COMPLETED
        assert "progress_clamped_from" not in completed.metadata
        assert "completion_blocked_reason" not in completed.metadata

    def test_progress_missing_task_returns_none(self, engine):
        assert engine.progress_task("nonexistent", progress=50, current_step="Step") is None


class TestEventPublishing:
    def test_start_publishes_event(self, engine, events, session):
        task = engine.create_task(session_id=session.session_id, project_id="p", title="T", description="D", mode=ExecutionMode.ASK)
        engine.start_task(task.task_id)
        published = events.list_events(session_id=session.session_id)
        assert len(published) >= 1
        from builder.events import BuilderEventType
        event_types = [e.event_type for e in published]
        assert BuilderEventType.TASK_STARTED in event_types

    def test_complete_publishes_event(self, engine, events, session):
        task = engine.create_task(session_id=session.session_id, project_id="p", title="T", description="D", mode=ExecutionMode.ASK)
        engine.start_task(task.task_id)
        engine.complete_task(task.task_id)
        from builder.events import BuilderEventType
        published = events.list_events(session_id=session.session_id)
        event_types = [e.event_type for e in published]
        assert BuilderEventType.TASK_COMPLETED in event_types


class TestSandboxRun:
    def test_run_delegate_sandbox(self, engine, store, session):
        task = engine.create_task(
            session_id=session.session_id,
            project_id="p",
            title="Delegate",
            description="D",
            mode=ExecutionMode.DELEGATE,
        )
        run = engine.run_delegate_sandbox(task.task_id, command="pytest tests/")
        assert run is not None
        assert run.status == "completed"
        assert run.exit_code == 0
        updated_task = store.get_task(task.task_id)
        assert updated_task.sandbox_run_id == run.sandbox_id

    def test_sandbox_missing_task_returns_none(self, engine):
        assert engine.run_delegate_sandbox("nonexistent", command="cmd") is None
