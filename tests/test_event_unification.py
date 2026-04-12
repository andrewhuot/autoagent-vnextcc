"""Tests for runtime event unification.

Covers:
- EventBroker wired with DurableEventStore persists builder events
- EventBroker bridge delivers lifecycle events to system EventLog
- Broadcast events (eval/optimize/loop) recorded in EventLog
- Unified event query merges system + builder events correctly
- Source filtering on the unified endpoint
- Chronological ordering across sources
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from builder.events import (
    BuilderEventType,
    DurableEventStore,
    EventBroker,
    LIFECYCLE_EVENT_TYPES,
    event_to_dict,
)
from data.event_log import EventLog, VALID_EVENT_TYPES


# ---------------------------------------------------------------------------
# 1. EventBroker wiring: durable store + system log bridge
# ---------------------------------------------------------------------------


class TestEventBrokerWiring:
    """Verify the wiring that api/server.py now performs."""

    def test_broker_with_durable_store_persists_events(self, tmp_path: Path) -> None:
        """When DurableEventStore is provided, events survive broker restart."""
        db = str(tmp_path / "builder_events.db")
        durable = DurableEventStore(db_path=db)
        broker = EventBroker(durable_store=durable)

        broker.publish(
            BuilderEventType.TASK_STARTED,
            session_id="sess-1",
            task_id="task-1",
            payload={"phase": "plan"},
        )
        broker.publish(
            BuilderEventType.ARTIFACT_UPDATED,
            session_id="sess-1",
            task_id="task-1",
            payload={"artifact": "routing"},
        )

        # Simulate restart — new broker, same durable store
        durable2 = DurableEventStore(db_path=db)
        broker2 = EventBroker(durable_store=durable2)
        events = broker2.list_events(session_id="sess-1")
        assert len(events) == 2
        assert events[0].event_type == BuilderEventType.TASK_STARTED
        assert events[1].event_type == BuilderEventType.ARTIFACT_UPDATED

    def test_broker_with_event_log_bridges_lifecycle_events(self, tmp_path: Path) -> None:
        """Lifecycle events should appear in the system EventLog."""
        event_log = EventLog(str(tmp_path / "event_log.db"))
        durable = DurableEventStore(db_path=str(tmp_path / "builder_events.db"))
        broker = EventBroker(durable_store=durable, system_event_log=event_log)

        # Publish a lifecycle event
        broker.publish(
            BuilderEventType.TASK_STARTED,
            session_id="sess-1",
            task_id="task-1",
            payload={"phase": "plan"},
        )

        # Check system event log
        system_events = event_log.list_events(event_type="builder_task_started")
        assert len(system_events) == 1
        assert system_events[0]["payload"]["task_id"] == "task-1"
        assert system_events[0]["session_id"] == "sess-1"

    def test_non_lifecycle_events_not_bridged(self, tmp_path: Path) -> None:
        """Non-lifecycle events (message.delta, task.progress) should NOT go to EventLog."""
        event_log = EventLog(str(tmp_path / "event_log.db"))
        durable = DurableEventStore(db_path=str(tmp_path / "builder_events.db"))
        broker = EventBroker(durable_store=durable, system_event_log=event_log)

        broker.publish(BuilderEventType.MESSAGE_DELTA, "sess-1", "task-1", {"text": "hello"})
        broker.publish(BuilderEventType.TASK_PROGRESS, "sess-1", "task-1", {"note": "working"})
        broker.publish(BuilderEventType.PLAN_READY, "sess-1", "task-1", {"plan": {}})

        system_events = event_log.list_events()
        assert len(system_events) == 0

    def test_all_lifecycle_types_bridge_correctly(self, tmp_path: Path) -> None:
        """Every lifecycle event type should create the correct system event."""
        event_log = EventLog(str(tmp_path / "event_log.db"))
        durable = DurableEventStore(db_path=str(tmp_path / "builder_events.db"))
        broker = EventBroker(durable_store=durable, system_event_log=event_log)

        for event_type in LIFECYCLE_EVENT_TYPES:
            broker.publish(event_type, "sess-1", "task-1", {"type": event_type.value})

        system_events = event_log.list_events(limit=50)
        assert len(system_events) == len(LIFECYCLE_EVENT_TYPES)

        system_types = {e["event_type"] for e in system_events}
        expected_types = {
            f"builder_{et.value.replace('.', '_')}" for et in LIFECYCLE_EVENT_TYPES
        }
        assert system_types == expected_types

    def test_durable_and_system_log_independent(self, tmp_path: Path) -> None:
        """Both durable store and system log should receive their events independently."""
        event_log = EventLog(str(tmp_path / "event_log.db"))
        durable = DurableEventStore(db_path=str(tmp_path / "builder_events.db"))
        broker = EventBroker(durable_store=durable, system_event_log=event_log)

        # Publish mix of lifecycle and non-lifecycle
        broker.publish(BuilderEventType.TASK_STARTED, "s1", "t1", {})
        broker.publish(BuilderEventType.MESSAGE_DELTA, "s1", "t1", {"text": "hi"})
        broker.publish(BuilderEventType.TASK_COMPLETED, "s1", "t1", {})

        # Durable store has ALL events
        durable_events = durable.list_events(session_id="s1")
        assert len(durable_events) == 3

        # System log has only lifecycle events
        system_events = event_log.list_events()
        assert len(system_events) == 2


# ---------------------------------------------------------------------------
# 2. Broadcast event types in EventLog
# ---------------------------------------------------------------------------


class TestBroadcastEventTypes:
    """Verify the new broadcast event types are accepted by EventLog."""

    def test_eval_completed_broadcast_type_valid(self, tmp_path: Path) -> None:
        log = EventLog(str(tmp_path / "events.db"))
        row_id = log.append(
            event_type="eval_completed_broadcast",
            payload={"task_id": "t1", "composite": 0.85, "passed": 8, "total": 10},
        )
        assert row_id > 0
        events = log.list_events(event_type="eval_completed_broadcast")
        assert len(events) == 1
        assert events[0]["payload"]["composite"] == 0.85

    def test_optimize_completed_broadcast_type_valid(self, tmp_path: Path) -> None:
        log = EventLog(str(tmp_path / "events.db"))
        row_id = log.append(
            event_type="optimize_completed_broadcast",
            payload={"task_id": "t1", "accepted": True, "status": "Accepted"},
        )
        assert row_id > 0

    def test_optimize_pending_review_broadcast_type_valid(self, tmp_path: Path) -> None:
        log = EventLog(str(tmp_path / "events.db"))
        row_id = log.append(
            event_type="optimize_pending_review_broadcast",
            payload={"task_id": "t1", "attempt_id": "a1"},
        )
        assert row_id > 0

    def test_loop_cycle_broadcast_type_valid(self, tmp_path: Path) -> None:
        log = EventLog(str(tmp_path / "events.db"))
        row_id = log.append(
            event_type="loop_cycle_broadcast",
            payload={"cycle": 1, "total_cycles": 5, "success_rate": 0.9},
        )
        assert row_id > 0

    def test_all_broadcast_types_in_valid_set(self) -> None:
        """Ensure all broadcast event types are registered in VALID_EVENT_TYPES."""
        broadcast_types = {
            "eval_completed_broadcast",
            "optimize_completed_broadcast",
            "optimize_pending_review_broadcast",
            "loop_cycle_broadcast",
        }
        assert broadcast_types.issubset(VALID_EVENT_TYPES)


# ---------------------------------------------------------------------------
# 3. Unified event query logic
# ---------------------------------------------------------------------------


class TestUnifiedEventMerge:
    """Test the merge logic used by the unified endpoint.

    These tests exercise the merge at the data layer level (not HTTP),
    simulating what GET /api/events/unified does internally.
    """

    # Bridged builder event types — same set used by the unified endpoint
    _BRIDGED_BUILDER_TYPES = frozenset({
        "builder_task_started", "builder_task_completed", "builder_task_failed",
        "builder_session_opened", "builder_session_closed",
        "builder_eval_started", "builder_eval_completed",
    })

    def _merge_events(
        self,
        event_log: EventLog,
        builder_broker: EventBroker,
        *,
        limit: int = 100,
        session_id: str | None = None,
        source: str | None = None,
    ) -> list[dict]:
        """Reproduce the merge logic from the unified endpoint."""
        include_builder = source in (None, "builder") and builder_broker is not None
        merged: list[dict] = []

        if source in (None, "system"):
            system_events = event_log.list_events(limit=limit, session_id=session_id)
            for evt in system_events:
                # Skip bridged builder events when builder source is also included
                if include_builder and evt["event_type"] in self._BRIDGED_BUILDER_TYPES:
                    continue
                merged.append({
                    "id": f"sys-{evt['id']}",
                    "timestamp": evt["timestamp"],
                    "event_type": evt["event_type"],
                    "source": "system",
                    "session_id": evt.get("session_id"),
                    "payload": evt.get("payload", {}),
                })

        if include_builder:
            builder_events = builder_broker.list_events(
                session_id=session_id,
                limit=limit,
            )
            for evt in builder_events:
                evt_dict = event_to_dict(evt)
                merged.append({
                    "id": f"bld-{evt_dict['event_id']}",
                    "timestamp": evt_dict["timestamp"],
                    "event_type": evt_dict["event_type"],
                    "source": "builder",
                    "session_id": evt_dict.get("session_id"),
                    "payload": evt_dict.get("payload", {}),
                })

        merged.sort(key=lambda e: e["timestamp"], reverse=True)
        return merged[:limit]

    def test_merges_system_and_builder_events(self, tmp_path: Path) -> None:
        """Both system and builder events appear in merged output without duplicates."""
        event_log = EventLog(str(tmp_path / "event_log.db"))
        durable = DurableEventStore(db_path=str(tmp_path / "builder_events.db"))
        broker = EventBroker(durable_store=durable, system_event_log=event_log)

        # System event (non-builder)
        event_log.append(event_type="eval_started", payload={"run_id": "r1"})

        # Builder lifecycle event — this goes to both durable store AND system log via bridge
        broker.publish(BuilderEventType.TASK_STARTED, "sess-1", "task-1", {"phase": "plan"})

        merged = self._merge_events(event_log, broker)

        # Should be exactly 2: eval_started (system) + task.started (builder)
        # The bridged builder_task_started in system log should be deduplicated
        assert len(merged) == 2
        sources = {e["source"] for e in merged}
        assert "system" in sources
        assert "builder" in sources

    def test_merged_events_sorted_newest_first(self, tmp_path: Path) -> None:
        """Merged events should be sorted by timestamp descending."""
        event_log = EventLog(str(tmp_path / "event_log.db"))
        durable = DurableEventStore(db_path=str(tmp_path / "builder_events.db"))
        broker = EventBroker(durable_store=durable)

        # Create events with known timestamps
        event_log.append(event_type="eval_started", payload={"order": 1})
        time.sleep(0.01)
        broker.publish(BuilderEventType.TASK_STARTED, "s1", "t1", {"order": 2})
        time.sleep(0.01)
        event_log.append(event_type="eval_completed", payload={"order": 3})

        merged = self._merge_events(event_log, broker)
        timestamps = [e["timestamp"] for e in merged]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_source_filter_system_only(self, tmp_path: Path) -> None:
        """source='system' should exclude builder events."""
        event_log = EventLog(str(tmp_path / "event_log.db"))
        durable = DurableEventStore(db_path=str(tmp_path / "builder_events.db"))
        broker = EventBroker(durable_store=durable)

        event_log.append(event_type="eval_started", payload={})
        broker.publish(BuilderEventType.TASK_STARTED, "s1", "t1", {})

        merged = self._merge_events(event_log, broker, source="system")
        assert all(e["source"] == "system" for e in merged)

    def test_source_filter_builder_only(self, tmp_path: Path) -> None:
        """source='builder' should exclude system events."""
        event_log = EventLog(str(tmp_path / "event_log.db"))
        durable = DurableEventStore(db_path=str(tmp_path / "builder_events.db"))
        broker = EventBroker(durable_store=durable)

        event_log.append(event_type="eval_started", payload={})
        broker.publish(BuilderEventType.TASK_STARTED, "s1", "t1", {})

        merged = self._merge_events(event_log, broker, source="builder")
        assert all(e["source"] == "builder" for e in merged)
        assert len(merged) == 1

    def test_session_id_filter(self, tmp_path: Path) -> None:
        """session_id filter should narrow both system and builder events."""
        event_log = EventLog(str(tmp_path / "event_log.db"))
        durable = DurableEventStore(db_path=str(tmp_path / "builder_events.db"))
        broker = EventBroker(durable_store=durable, system_event_log=event_log)

        # Events for session "sess-1"
        broker.publish(BuilderEventType.TASK_STARTED, "sess-1", "t1", {})
        event_log.append(event_type="eval_started", payload={}, session_id="sess-1")

        # Events for a different session
        broker.publish(BuilderEventType.TASK_STARTED, "sess-2", "t2", {})
        event_log.append(event_type="eval_started", payload={}, session_id="sess-2")

        merged = self._merge_events(event_log, broker, session_id="sess-1")
        assert all(e["session_id"] == "sess-1" for e in merged)

    def test_limit_applied_to_merged_result(self, tmp_path: Path) -> None:
        """Limit should apply to the final merged set, not per-source."""
        event_log = EventLog(str(tmp_path / "event_log.db"))
        durable = DurableEventStore(db_path=str(tmp_path / "builder_events.db"))
        broker = EventBroker(durable_store=durable)

        for i in range(10):
            event_log.append(event_type="eval_started", payload={"i": i})
            broker.publish(BuilderEventType.TASK_PROGRESS, "s1", "t1", {"i": i})

        merged = self._merge_events(event_log, broker, limit=5)
        assert len(merged) == 5

    def test_unified_event_schema(self, tmp_path: Path) -> None:
        """Every merged event should have the unified schema fields."""
        event_log = EventLog(str(tmp_path / "event_log.db"))
        durable = DurableEventStore(db_path=str(tmp_path / "builder_events.db"))
        broker = EventBroker(durable_store=durable)

        event_log.append(event_type="eval_started", payload={"x": 1})
        broker.publish(BuilderEventType.TASK_STARTED, "s1", "t1", {"y": 2})

        merged = self._merge_events(event_log, broker)
        required_keys = {"id", "timestamp", "event_type", "source", "session_id", "payload"}
        for event in merged:
            assert required_keys.issubset(event.keys()), f"Missing keys in {event}"

    def test_lifecycle_events_not_duplicated(self, tmp_path: Path) -> None:
        """Bridged builder lifecycle events should not appear as both system + builder."""
        event_log = EventLog(str(tmp_path / "event_log.db"))
        durable = DurableEventStore(db_path=str(tmp_path / "builder_events.db"))
        broker = EventBroker(durable_store=durable, system_event_log=event_log)

        # Publish lifecycle events — each goes to both durable + system log
        broker.publish(BuilderEventType.SESSION_OPENED, "s1", None, {})
        broker.publish(BuilderEventType.TASK_STARTED, "s1", "t1", {})
        broker.publish(BuilderEventType.TASK_COMPLETED, "s1", "t1", {})
        broker.publish(BuilderEventType.SESSION_CLOSED, "s1", None, {})

        merged = self._merge_events(event_log, broker)

        # Should be 4, not 8 (each lifecycle event counted once, not twice)
        assert len(merged) == 4
        assert all(e["source"] == "builder" for e in merged)

    def test_system_only_source_includes_bridged_events(self, tmp_path: Path) -> None:
        """When source='system', bridged builder events SHOULD appear (no builder source to prefer)."""
        event_log = EventLog(str(tmp_path / "event_log.db"))
        durable = DurableEventStore(db_path=str(tmp_path / "builder_events.db"))
        broker = EventBroker(durable_store=durable, system_event_log=event_log)

        broker.publish(BuilderEventType.TASK_STARTED, "s1", "t1", {})

        # With source="system", bridged events should still appear
        merged = self._merge_events(event_log, broker, source="system")
        assert len(merged) == 1
        assert merged[0]["source"] == "system"
        assert merged[0]["event_type"] == "builder_task_started"

    def test_id_prefix_distinguishes_sources(self, tmp_path: Path) -> None:
        """System events should have 'sys-' prefix, builder events 'bld-' prefix."""
        event_log = EventLog(str(tmp_path / "event_log.db"))
        durable = DurableEventStore(db_path=str(tmp_path / "builder_events.db"))
        broker = EventBroker(durable_store=durable)

        event_log.append(event_type="eval_started", payload={})
        broker.publish(BuilderEventType.TASK_STARTED, "s1", "t1", {})

        merged = self._merge_events(event_log, broker)
        sys_events = [e for e in merged if e["source"] == "system"]
        bld_events = [e for e in merged if e["source"] == "builder"]

        assert all(e["id"].startswith("sys-") for e in sys_events)
        assert all(e["id"].startswith("bld-") for e in bld_events)


# ---------------------------------------------------------------------------
# 4. End-to-end: full lifecycle through unified system
# ---------------------------------------------------------------------------


class TestEndToEndEventFlow:
    """Simulate the full event flow: builder publishes → durable + system log → unified query."""

    def test_builder_session_lifecycle_in_unified_timeline(self, tmp_path: Path) -> None:
        """A complete builder session should appear coherently in the unified timeline."""
        event_log = EventLog(str(tmp_path / "event_log.db"))
        durable = DurableEventStore(db_path=str(tmp_path / "builder_events.db"))
        broker = EventBroker(durable_store=durable, system_event_log=event_log)

        # Simulate a builder session
        broker.publish(BuilderEventType.SESSION_OPENED, "sess-1", None, {"brief": "Build routing agent"})
        time.sleep(0.01)
        broker.publish(BuilderEventType.TASK_STARTED, "sess-1", "task-1", {"phase": "plan"})
        time.sleep(0.01)
        broker.publish(BuilderEventType.PLAN_READY, "sess-1", "task-1", {"plan": {"steps": 3}})
        time.sleep(0.01)
        broker.publish(BuilderEventType.MESSAGE_DELTA, "sess-1", "task-1", {"text": "Building..."})
        time.sleep(0.01)
        broker.publish(BuilderEventType.ARTIFACT_UPDATED, "sess-1", "task-1", {"artifact": "config"})
        time.sleep(0.01)
        broker.publish(BuilderEventType.TASK_COMPLETED, "sess-1", "task-1", {"status": "done"})
        time.sleep(0.01)
        broker.publish(BuilderEventType.SESSION_CLOSED, "sess-1", None, {})

        # Durable store has all 7 events
        durable_events = durable.list_events(session_id="sess-1")
        assert len(durable_events) == 7

        # System log has lifecycle events only (4: session_opened, task_started, task_completed, session_closed)
        system_events = event_log.list_events(session_id="sess-1")
        assert len(system_events) == 4
        system_types = {e["event_type"] for e in system_events}
        assert system_types == {
            "builder_session_opened",
            "builder_task_started",
            "builder_task_completed",
            "builder_session_closed",
        }

    def test_mixed_subsystem_events_in_unified(self, tmp_path: Path) -> None:
        """Events from builder + optimizer + eval should all appear in unified view."""
        event_log = EventLog(str(tmp_path / "event_log.db"))
        durable = DurableEventStore(db_path=str(tmp_path / "builder_events.db"))
        broker = EventBroker(durable_store=durable, system_event_log=event_log)

        # Builder event
        broker.publish(BuilderEventType.TASK_STARTED, "sess-1", "task-1", {})
        time.sleep(0.01)

        # Eval broadcast event (simulating what eval.py now does)
        event_log.append(
            event_type="eval_completed_broadcast",
            payload={"task_id": "eval-1", "composite": 0.92},
        )
        time.sleep(0.01)

        # Optimizer event
        event_log.append(
            event_type="optimize_completed_broadcast",
            payload={"task_id": "opt-1", "accepted": True},
        )

        # Query unified — should see builder + all system events
        system_events = event_log.list_events(limit=50)
        builder_events = broker.list_events(session_id="sess-1")

        # System log has: builder_task_started (bridged) + eval + optimize = 3
        assert len(system_events) == 3
        # Builder durable has: 1
        assert len(builder_events) == 1

    def test_broadcast_events_persist_across_restart(self, tmp_path: Path) -> None:
        """Broadcast events should be queryable after EventLog is re-instantiated."""
        db = str(tmp_path / "event_log.db")
        log1 = EventLog(db)

        log1.append(
            event_type="eval_completed_broadcast",
            payload={"task_id": "t1", "composite": 0.85},
        )
        log1.append(
            event_type="loop_cycle_broadcast",
            payload={"cycle": 3, "total_cycles": 10},
        )

        # Simulate restart
        log2 = EventLog(db)
        events = log2.list_events(limit=50)
        assert len(events) == 2
        types = {e["event_type"] for e in events}
        assert "eval_completed_broadcast" in types
        assert "loop_cycle_broadcast" in types


# ---------------------------------------------------------------------------
# 5. Regression: existing event types still work
# ---------------------------------------------------------------------------


class TestExistingEventTypesRegression:
    """Ensure adding new types didn't break existing ones."""

    def test_all_original_event_types_still_valid(self, tmp_path: Path) -> None:
        """Every previously-valid event type should still be accepted."""
        original_types = {
            "mutation_proposed", "eval_started", "eval_completed",
            "candidate_promoted", "candidate_rejected", "rollback_triggered",
            "canary_started", "canary_passed", "canary_failed",
            "budget_exceeded", "stall_detected",
            "human_pause", "human_reject", "human_inject",
            "autofix_suggested", "autofix_applied", "autofix_rejected",
            "judge_feedback_recorded", "judge_drift_detected", "judge_version_created",
            "context_analyzed", "context_simulation_run",
            "builder_task_started", "builder_task_completed", "builder_task_failed",
            "builder_session_opened", "builder_session_closed",
            "builder_eval_started", "builder_eval_completed",
        }
        log = EventLog(str(tmp_path / "events.db"))
        for event_type in original_types:
            row_id = log.append(event_type=event_type)
            assert row_id > 0

    def test_invalid_type_still_rejected(self, tmp_path: Path) -> None:
        """Random event types should still be rejected."""
        log = EventLog(str(tmp_path / "events.db"))
        with pytest.raises(ValueError, match="Invalid event_type"):
            log.append(event_type="not_a_real_event")
