"""Tests for DurableEventStore and enhanced EventBroker persistence.

Covers:
- DurableEventStore SQLite init, persist, and list operations
- EventBroker with durable_store writes events to SQLite
- EventBroker.list_events reads from durable store when available
- EventBroker without durable_store falls back to in-memory
- System event log bridge for lifecycle events
- Event filtering by session_id, task_id, event_type
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from builder.events import (
    BuilderEvent,
    BuilderEventType,
    DurableEventStore,
    EventBroker,
    LIFECYCLE_EVENT_TYPES,
)


# ---------------------------------------------------------------------------
# DurableEventStore unit tests
# ---------------------------------------------------------------------------


class TestDurableEventStore:
    def test_init_creates_database_and_table(self, tmp_path: Path) -> None:
        db = str(tmp_path / "events.db")
        store = DurableEventStore(db_path=db)
        assert Path(db).exists()

    def test_persist_and_list_single_event(self, tmp_path: Path) -> None:
        store = DurableEventStore(db_path=str(tmp_path / "events.db"))
        event = BuilderEvent(
            event_id="evt-1",
            event_type=BuilderEventType.TASK_STARTED,
            session_id="sess-1",
            task_id="task-1",
            payload={"step": "Planning"},
        )
        store.persist(event)
        events = store.list_events(session_id="sess-1")
        assert len(events) == 1
        assert events[0].event_id == "evt-1"
        assert events[0].event_type == BuilderEventType.TASK_STARTED
        assert events[0].payload == {"step": "Planning"}

    def test_list_filters_by_session_id(self, tmp_path: Path) -> None:
        store = DurableEventStore(db_path=str(tmp_path / "events.db"))
        store.persist(BuilderEvent(event_id="a", session_id="s1", task_id="t1"))
        store.persist(BuilderEvent(event_id="b", session_id="s2", task_id="t2"))
        store.persist(BuilderEvent(event_id="c", session_id="s1", task_id="t3"))

        events = store.list_events(session_id="s1")
        assert len(events) == 2
        assert {e.event_id for e in events} == {"a", "c"}

    def test_list_filters_by_task_id(self, tmp_path: Path) -> None:
        store = DurableEventStore(db_path=str(tmp_path / "events.db"))
        store.persist(BuilderEvent(event_id="a", session_id="s1", task_id="t1"))
        store.persist(BuilderEvent(event_id="b", session_id="s1", task_id="t2"))

        events = store.list_events(task_id="t1")
        assert len(events) == 1
        assert events[0].event_id == "a"

    def test_list_filters_by_event_type(self, tmp_path: Path) -> None:
        store = DurableEventStore(db_path=str(tmp_path / "events.db"))
        store.persist(BuilderEvent(
            event_id="a", session_id="s1",
            event_type=BuilderEventType.TASK_STARTED,
        ))
        store.persist(BuilderEvent(
            event_id="b", session_id="s1",
            event_type=BuilderEventType.TASK_COMPLETED,
        ))

        events = store.list_events(event_type="task.started")
        assert len(events) == 1
        assert events[0].event_type == BuilderEventType.TASK_STARTED

    def test_list_respects_limit(self, tmp_path: Path) -> None:
        store = DurableEventStore(db_path=str(tmp_path / "events.db"))
        for i in range(10):
            store.persist(BuilderEvent(event_id=f"evt-{i}", session_id="s1"))
        events = store.list_events(limit=3)
        assert len(events) == 3

    def test_list_returns_chronological_order(self, tmp_path: Path) -> None:
        store = DurableEventStore(db_path=str(tmp_path / "events.db"))
        for i in range(5):
            store.persist(BuilderEvent(
                event_id=f"evt-{i}",
                session_id="s1",
                timestamp=1000.0 + i,
            ))
        events = store.list_events(session_id="s1")
        timestamps = [e.timestamp for e in events]
        assert timestamps == sorted(timestamps)

    def test_persistence_across_instances(self, tmp_path: Path) -> None:
        db = str(tmp_path / "events.db")
        store1 = DurableEventStore(db_path=db)
        store1.persist(BuilderEvent(event_id="a", session_id="s1", payload={"x": 1}))

        store2 = DurableEventStore(db_path=db)
        events = store2.list_events(session_id="s1")
        assert len(events) == 1
        assert events[0].payload == {"x": 1}

    def test_duplicate_event_id_ignored(self, tmp_path: Path) -> None:
        store = DurableEventStore(db_path=str(tmp_path / "events.db"))
        event = BuilderEvent(event_id="dupe", session_id="s1")
        store.persist(event)
        store.persist(event)  # Should not raise
        events = store.list_events()
        assert len(events) == 1


# ---------------------------------------------------------------------------
# EventBroker with durable store
# ---------------------------------------------------------------------------


class TestEventBrokerDurable:
    def test_publish_persists_to_durable_store(self, tmp_path: Path) -> None:
        durable = DurableEventStore(db_path=str(tmp_path / "events.db"))
        broker = EventBroker(durable_store=durable)

        broker.publish(
            BuilderEventType.TASK_STARTED,
            session_id="s1",
            task_id="t1",
            payload={"step": "init"},
        )

        events = durable.list_events(session_id="s1")
        assert len(events) == 1
        assert events[0].event_type == BuilderEventType.TASK_STARTED

    def test_list_events_reads_from_durable(self, tmp_path: Path) -> None:
        durable = DurableEventStore(db_path=str(tmp_path / "events.db"))
        broker = EventBroker(durable_store=durable)

        broker.publish(BuilderEventType.TASK_STARTED, "s1", "t1", {"a": 1})
        broker.publish(BuilderEventType.TASK_COMPLETED, "s1", "t1", {"b": 2})

        events = broker.list_events(session_id="s1")
        assert len(events) == 2

    def test_events_survive_broker_restart(self, tmp_path: Path) -> None:
        db = str(tmp_path / "events.db")
        durable = DurableEventStore(db_path=db)

        broker1 = EventBroker(durable_store=durable)
        broker1.publish(BuilderEventType.TASK_STARTED, "s1", "t1", {"x": 1})

        # Simulate restart — new broker, same durable store
        durable2 = DurableEventStore(db_path=db)
        broker2 = EventBroker(durable_store=durable2)
        events = broker2.list_events(session_id="s1")
        assert len(events) == 1
        assert events[0].payload == {"x": 1}

    def test_iter_events_uses_in_memory_buffer(self, tmp_path: Path) -> None:
        """iter_events should always use in-memory for low-latency SSE."""
        durable = DurableEventStore(db_path=str(tmp_path / "events.db"))
        broker = EventBroker(durable_store=durable)

        broker.publish(BuilderEventType.TASK_STARTED, "s1", "t1", {})
        events = list(broker.iter_events(session_id="s1"))
        assert len(events) == 1


# ---------------------------------------------------------------------------
# EventBroker without durable store (backward compat)
# ---------------------------------------------------------------------------


class TestEventBrokerInMemory:
    def test_publish_and_list_without_durable(self) -> None:
        broker = EventBroker()
        broker.publish(BuilderEventType.TASK_STARTED, "s1", "t1", {"a": 1})
        events = broker.list_events(session_id="s1")
        assert len(events) == 1


# ---------------------------------------------------------------------------
# System event log bridge
# ---------------------------------------------------------------------------


class _MockSystemEventLog:
    """Captures calls to append() for testing the bridge."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def append(self, *, event_type: str, payload: dict | None = None, **kwargs) -> int:
        self.calls.append({"event_type": event_type, "payload": payload, **kwargs})
        return len(self.calls)


class TestSystemEventBridge:
    def test_lifecycle_events_bridge_to_system_log(self, tmp_path: Path) -> None:
        mock_log = _MockSystemEventLog()
        durable = DurableEventStore(db_path=str(tmp_path / "events.db"))
        broker = EventBroker(durable_store=durable, system_event_log=mock_log)

        broker.publish(BuilderEventType.TASK_STARTED, "s1", "t1", {"step": "init"})
        assert len(mock_log.calls) == 1
        assert mock_log.calls[0]["event_type"] == "builder_task_started"
        assert mock_log.calls[0]["session_id"] == "s1"
        assert mock_log.calls[0]["payload"]["task_id"] == "t1"

    def test_non_lifecycle_events_not_bridged(self, tmp_path: Path) -> None:
        mock_log = _MockSystemEventLog()
        durable = DurableEventStore(db_path=str(tmp_path / "events.db"))
        broker = EventBroker(durable_store=durable, system_event_log=mock_log)

        broker.publish(BuilderEventType.TASK_PROGRESS, "s1", "t1", {})
        broker.publish(BuilderEventType.MESSAGE_DELTA, "s1", None, {})
        assert len(mock_log.calls) == 0

    def test_all_lifecycle_types_are_bridged(self) -> None:
        """Verify LIFECYCLE_EVENT_TYPES matches what we expect."""
        expected = {
            BuilderEventType.TASK_STARTED,
            BuilderEventType.TASK_COMPLETED,
            BuilderEventType.TASK_FAILED,
            BuilderEventType.SESSION_OPENED,
            BuilderEventType.SESSION_CLOSED,
            BuilderEventType.EVAL_STARTED,
            BuilderEventType.EVAL_COMPLETED,
        }
        assert LIFECYCLE_EVENT_TYPES == expected

    def test_bridge_failure_does_not_break_publish(self, tmp_path: Path) -> None:
        """If the system log rejects the event, publish still succeeds."""

        class _FailingLog:
            def append(self, **kwargs):
                raise ValueError("Nope")

        durable = DurableEventStore(db_path=str(tmp_path / "events.db"))
        broker = EventBroker(durable_store=durable, system_event_log=_FailingLog())

        event = broker.publish(BuilderEventType.TASK_STARTED, "s1", "t1", {})
        assert event.event_id  # Should not raise
