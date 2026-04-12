"""Tests for BuilderTask crash recovery (stale task detection).

Covers:
- Detection of tasks stuck in running/paused state past threshold
- Recovery marks tasks as failed with stale_interrupted reason
- Recovery emits task.failed events
- Tasks within threshold are not recovered
- Tasks in terminal states are not affected
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from builder.events import BuilderEventType, DurableEventStore, EventBroker
from builder.execution import BuilderExecutionEngine
from builder.store import BuilderStore
from builder.types import (
    BuilderSession,
    BuilderTask,
    ExecutionMode,
    TaskStatus,
    now_ts,
)


class _MockOrchestrator:
    """Minimal orchestrator stub for execution engine tests."""

    def start_session(self, session):
        pass


class _MockPermissions:
    """Minimal permissions stub for execution engine tests."""

    pass


@pytest.fixture
def setup(tmp_path: Path):
    """Create a fully wired execution engine with durable events."""
    store = BuilderStore(db_path=str(tmp_path / "builder.db"))
    durable = DurableEventStore(db_path=str(tmp_path / "events.db"))
    broker = EventBroker(durable_store=durable)
    engine = BuilderExecutionEngine(
        store=store,
        orchestrator=_MockOrchestrator(),
        permissions=_MockPermissions(),
        events=broker,
        worktree_root=str(tmp_path / "worktrees"),
    )
    return store, broker, engine, durable


class TestCrashRecovery:
    def test_recovers_stale_running_task(self, setup) -> None:
        store, broker, engine, durable = setup

        # Create a task that's been "stuck" for over 30 minutes
        task = BuilderTask(
            session_id="s1",
            project_id="p1",
            title="Stuck task",
            status=TaskStatus.RUNNING,
            updated_at=now_ts() - 3600,  # 1 hour ago
        )
        store.save_task(task)

        recovered = engine.recover_stale_tasks()
        assert len(recovered) == 1
        assert recovered[0].task_id == task.task_id
        assert recovered[0].status == TaskStatus.FAILED
        assert recovered[0].error == "stale_interrupted"

    def test_recovers_stale_paused_task(self, setup) -> None:
        store, broker, engine, durable = setup

        task = BuilderTask(
            session_id="s1",
            project_id="p1",
            title="Paused task",
            status=TaskStatus.PAUSED,
            updated_at=now_ts() - 3600,
        )
        store.save_task(task)

        recovered = engine.recover_stale_tasks()
        assert len(recovered) == 1
        assert recovered[0].status == TaskStatus.FAILED

    def test_does_not_recover_recent_running_task(self, setup) -> None:
        store, broker, engine, durable = setup

        task = BuilderTask(
            session_id="s1",
            project_id="p1",
            title="Active task",
            status=TaskStatus.RUNNING,
            updated_at=now_ts(),  # Just updated
        )
        store.save_task(task)

        recovered = engine.recover_stale_tasks()
        assert len(recovered) == 0

        loaded = store.get_task(task.task_id)
        assert loaded.status == TaskStatus.RUNNING

    def test_does_not_recover_completed_tasks(self, setup) -> None:
        store, broker, engine, durable = setup

        task = BuilderTask(
            session_id="s1",
            project_id="p1",
            title="Done task",
            status=TaskStatus.COMPLETED,
            updated_at=now_ts() - 7200,  # Very old but already completed
        )
        store.save_task(task)

        recovered = engine.recover_stale_tasks()
        assert len(recovered) == 0

    def test_custom_threshold(self, setup) -> None:
        store, broker, engine, durable = setup

        task = BuilderTask(
            session_id="s1",
            project_id="p1",
            title="Short threshold",
            status=TaskStatus.RUNNING,
            updated_at=now_ts() - 120,  # 2 minutes ago
        )
        store.save_task(task)

        # With default 30-min threshold: not recovered
        assert len(engine.recover_stale_tasks()) == 0

        # With 60-second threshold: recovered
        recovered = engine.recover_stale_tasks(max_age_seconds=60)
        assert len(recovered) == 1

    def test_emits_failed_event(self, setup) -> None:
        store, broker, engine, durable = setup

        task = BuilderTask(
            session_id="s1",
            project_id="p1",
            title="Event task",
            status=TaskStatus.RUNNING,
            updated_at=now_ts() - 3600,
        )
        store.save_task(task)

        engine.recover_stale_tasks()

        events = durable.list_events(session_id="s1")
        assert len(events) >= 1
        fail_events = [e for e in events if e.event_type == BuilderEventType.TASK_FAILED]
        assert len(fail_events) == 1
        assert fail_events[0].payload["error"] == "stale_interrupted"

    def test_recovers_multiple_tasks(self, setup) -> None:
        store, broker, engine, durable = setup

        for i in range(3):
            store.save_task(BuilderTask(
                session_id="s1",
                project_id="p1",
                title=f"Stuck-{i}",
                status=TaskStatus.RUNNING,
                updated_at=now_ts() - 3600,
            ))

        recovered = engine.recover_stale_tasks()
        assert len(recovered) == 3
        assert all(t.status == TaskStatus.FAILED for t in recovered)

    def test_records_original_status_in_metadata(self, setup) -> None:
        store, broker, engine, durable = setup

        task = BuilderTask(
            session_id="s1",
            project_id="p1",
            title="Paused recovery",
            status=TaskStatus.PAUSED,
            updated_at=now_ts() - 3600,
        )
        store.save_task(task)

        recovered = engine.recover_stale_tasks()
        assert len(recovered) == 1
        assert recovered[0].metadata["original_status"] == "paused"
