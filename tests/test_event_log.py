"""Unit tests for EventLog append-only system event logging."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from data.event_log import VALID_EVENT_TYPES, EventLog


def test_initialization_creates_database_and_tables(tmp_path: Path) -> None:
    """EventLog.__init__ should create database file and required tables."""
    db_path = tmp_path / "test_events.db"
    log = EventLog(str(db_path))

    assert db_path.exists()

    # Verify table schema
    with sqlite3.connect(log.db_path) as conn:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='system_events'"
        )
        tables = cursor.fetchall()
        assert len(tables) == 1

        # Verify indexes exist
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='system_events'"
        )
        indexes = {row[0] for row in cursor.fetchall()}
        assert "idx_events_type" in indexes
        assert "idx_events_ts" in indexes


def test_initialization_creates_parent_directory(tmp_path: Path) -> None:
    """EventLog should create parent directories if they don't exist."""
    db_path = tmp_path / "nested" / "dirs" / "events.db"
    log = EventLog(str(db_path))

    assert db_path.exists()
    assert db_path.parent.exists()


def test_append_valid_event_type_succeeds(tmp_path: Path) -> None:
    """append() should accept all valid event types and return row ID."""
    db_path = tmp_path / "events.db"
    log = EventLog(str(db_path))

    for event_type in VALID_EVENT_TYPES:
        row_id = log.append(event_type=event_type)
        assert isinstance(row_id, int)
        assert row_id > 0


def test_append_invalid_event_type_raises_value_error(tmp_path: Path) -> None:
    """append() should raise ValueError for invalid event types."""
    db_path = tmp_path / "events.db"
    log = EventLog(str(db_path))

    with pytest.raises(ValueError, match="Invalid event_type: invalid_type"):
        log.append(event_type="invalid_type")

    with pytest.raises(ValueError, match="Invalid event_type: random_event"):
        log.append(event_type="random_event")


def test_append_stores_timestamp_automatically(tmp_path: Path) -> None:
    """append() should automatically set timestamp to current time."""
    db_path = tmp_path / "events.db"
    log = EventLog(str(db_path))

    before = time.time()
    log.append(event_type="eval_started")
    after = time.time()

    events = log.list_events(limit=1)
    assert len(events) == 1
    assert before <= events[0]["timestamp"] <= after


def test_append_with_payload_persists_correctly(tmp_path: Path) -> None:
    """append() should serialize and store payload as JSON."""
    db_path = tmp_path / "events.db"
    log = EventLog(str(db_path))

    payload = {
        "candidate_id": "cand-123",
        "score": 0.95,
        "metrics": {"accuracy": 0.98, "latency": 150},
        "nested": {"deep": {"value": "test"}},
    }

    log.append(event_type="candidate_promoted", payload=payload)

    events = log.list_events(limit=1)
    assert len(events) == 1
    assert events[0]["payload"] == payload


def test_append_with_none_payload_stores_empty_dict(tmp_path: Path) -> None:
    """append() with no payload should store empty dict."""
    db_path = tmp_path / "events.db"
    log = EventLog(str(db_path))

    log.append(event_type="eval_started")

    events = log.list_events(limit=1)
    assert len(events) == 1
    assert events[0]["payload"] == {}


def test_append_with_cycle_id_persists_correctly(tmp_path: Path) -> None:
    """append() should store cycle_id when provided."""
    db_path = tmp_path / "events.db"
    log = EventLog(str(db_path))

    cycle_id = "cycle-42"
    log.append(event_type="mutation_proposed", cycle_id=cycle_id)

    events = log.list_events(limit=1)
    assert len(events) == 1
    assert events[0]["cycle_id"] == cycle_id


def test_append_with_experiment_id_persists_correctly(tmp_path: Path) -> None:
    """append() should store experiment_id when provided."""
    db_path = tmp_path / "events.db"
    log = EventLog(str(db_path))

    experiment_id = "exp-2024-03-24"
    log.append(event_type="canary_started", experiment_id=experiment_id)

    events = log.list_events(limit=1)
    assert len(events) == 1
    assert events[0]["experiment_id"] == experiment_id


def test_append_with_all_optional_fields(tmp_path: Path) -> None:
    """append() should correctly store all optional fields together."""
    db_path = tmp_path / "events.db"
    log = EventLog(str(db_path))

    payload = {"reason": "performance degradation", "threshold": 0.8}
    cycle_id = "cycle-99"
    experiment_id = "exp-test"

    log.append(
        event_type="rollback_triggered",
        payload=payload,
        cycle_id=cycle_id,
        experiment_id=experiment_id,
    )

    events = log.list_events(limit=1)
    assert len(events) == 1
    assert events[0]["event_type"] == "rollback_triggered"
    assert events[0]["payload"] == payload
    assert events[0]["cycle_id"] == cycle_id
    assert events[0]["experiment_id"] == experiment_id


def test_append_without_optional_fields_stores_nulls(tmp_path: Path) -> None:
    """append() without optional fields should store None for cycle_id and experiment_id."""
    db_path = tmp_path / "events.db"
    log = EventLog(str(db_path))

    log.append(event_type="budget_exceeded")

    events = log.list_events(limit=1)
    assert len(events) == 1
    assert events[0]["cycle_id"] is None
    assert events[0]["experiment_id"] is None


def test_list_events_returns_events_in_reverse_chronological_order(tmp_path: Path) -> None:
    """list_events() should return events ordered by ID descending (newest first)."""
    db_path = tmp_path / "events.db"
    log = EventLog(str(db_path))

    # Append events with slight delays to ensure ordering
    event_ids = []
    for i in range(5):
        event_id = log.append(
            event_type="eval_completed",
            payload={"iteration": i},
        )
        event_ids.append(event_id)
        time.sleep(0.001)  # Ensure different timestamps

    events = log.list_events(limit=10)

    # Should be in reverse order (newest first)
    assert len(events) == 5
    assert events[0]["id"] == event_ids[4]
    assert events[1]["id"] == event_ids[3]
    assert events[2]["id"] == event_ids[2]
    assert events[3]["id"] == event_ids[1]
    assert events[4]["id"] == event_ids[0]


def test_list_events_limit_parameter_works(tmp_path: Path) -> None:
    """list_events() should respect the limit parameter."""
    db_path = tmp_path / "events.db"
    log = EventLog(str(db_path))

    # Append 10 events
    for i in range(10):
        log.append(event_type="eval_started", payload={"run": i})

    # Request only 3
    events = log.list_events(limit=3)
    assert len(events) == 3

    # Request all
    events = log.list_events(limit=100)
    assert len(events) == 10

    # Request 1
    events = log.list_events(limit=1)
    assert len(events) == 1


def test_list_events_default_limit_is_100(tmp_path: Path) -> None:
    """list_events() should default to limit=100."""
    db_path = tmp_path / "events.db"
    log = EventLog(str(db_path))

    # Append more than 100 events
    for i in range(150):
        log.append(event_type="mutation_proposed")

    events = log.list_events()
    assert len(events) == 100


def test_list_events_event_type_filter_works(tmp_path: Path) -> None:
    """list_events() should filter by event_type when specified."""
    db_path = tmp_path / "events.db"
    log = EventLog(str(db_path))

    # Append mixed event types
    log.append(event_type="eval_started", payload={"test": 1})
    log.append(event_type="candidate_promoted", payload={"test": 2})
    log.append(event_type="eval_started", payload={"test": 3})
    log.append(event_type="rollback_triggered", payload={"test": 4})
    log.append(event_type="eval_started", payload={"test": 5})

    # Filter for eval_started only
    events = log.list_events(event_type="eval_started", limit=10)
    assert len(events) == 3
    for event in events:
        assert event["event_type"] == "eval_started"

    # Verify ordering is preserved (newest first)
    assert events[0]["payload"]["test"] == 5
    assert events[1]["payload"]["test"] == 3
    assert events[2]["payload"]["test"] == 1


def test_list_events_event_type_filter_with_limit(tmp_path: Path) -> None:
    """list_events() should apply limit after filtering by event_type."""
    db_path = tmp_path / "events.db"
    log = EventLog(str(db_path))

    # Append many events of specific type
    for i in range(10):
        log.append(event_type="canary_passed", payload={"iteration": i})
        log.append(event_type="canary_failed" if i % 2 == 0 else "eval_started")

    events = log.list_events(event_type="canary_passed", limit=3)
    assert len(events) == 3
    for event in events:
        assert event["event_type"] == "canary_passed"


def test_list_events_no_results_returns_empty_list(tmp_path: Path) -> None:
    """list_events() should return empty list when no events match."""
    db_path = tmp_path / "events.db"
    log = EventLog(str(db_path))

    # Empty database
    events = log.list_events()
    assert events == []

    # Filter with no matches
    log.append(event_type="eval_started")
    events = log.list_events(event_type="human_pause")
    assert events == []


def test_multiple_events_appended_correctly(tmp_path: Path) -> None:
    """Multiple append() calls should create distinct events with incrementing IDs."""
    db_path = tmp_path / "events.db"
    log = EventLog(str(db_path))

    events_data = [
        {"type": "mutation_proposed", "payload": {"mutation": "add_feature_x"}},
        {"type": "eval_started", "payload": {"eval_id": "eval-1"}},
        {"type": "eval_completed", "payload": {"eval_id": "eval-1", "score": 0.92}},
        {"type": "candidate_promoted", "payload": {"candidate_id": "cand-1"}},
        {"type": "canary_started", "payload": {"canary_id": "canary-1"}},
    ]

    row_ids = []
    for event_data in events_data:
        row_id = log.append(
            event_type=event_data["type"],
            payload=event_data["payload"],
        )
        row_ids.append(row_id)

    # Verify IDs are incrementing
    for i in range(1, len(row_ids)):
        assert row_ids[i] > row_ids[i - 1]

    # Verify all events are stored correctly
    events = log.list_events(limit=10)
    assert len(events) == 5

    # Verify in reverse order
    for i, event in enumerate(events):
        original_idx = len(events_data) - 1 - i
        assert event["event_type"] == events_data[original_idx]["type"]
        assert event["payload"] == events_data[original_idx]["payload"]


def test_event_payload_with_special_characters(tmp_path: Path) -> None:
    """append() should handle payload with special characters and unicode."""
    db_path = tmp_path / "events.db"
    log = EventLog(str(db_path))

    payload = {
        "message": "Test with 'quotes' and \"double quotes\"",
        "unicode": "Testing unicode: 你好 🚀 émoji",
        "special": "Newline\nTab\tBackslash\\",
        "json_chars": '{"nested": "value"}',
    }

    log.append(event_type="human_inject", payload=payload)

    events = log.list_events(limit=1)
    assert len(events) == 1
    assert events[0]["payload"] == payload


def test_event_payload_with_non_serializable_types(tmp_path: Path) -> None:
    """append() should handle non-JSON-serializable types using default=str."""
    db_path = tmp_path / "events.db"
    log = EventLog(str(db_path))

    # Path objects should be converted to string
    payload = {
        "path": Path("/some/path"),
        "timestamp": time.time(),
    }

    log.append(event_type="stall_detected", payload=payload)

    events = log.list_events(limit=1)
    assert len(events) == 1
    # Path should be converted to string
    assert events[0]["payload"]["path"] == "/some/path"
    assert isinstance(events[0]["payload"]["timestamp"], float)


def test_concurrent_appends_all_succeed(tmp_path: Path) -> None:
    """Multiple append() calls should all succeed without conflicts."""
    db_path = tmp_path / "events.db"
    log = EventLog(str(db_path))

    # Rapidly append many events
    row_ids = []
    for i in range(50):
        row_id = log.append(
            event_type="eval_completed",
            payload={"iteration": i},
            cycle_id=f"cycle-{i % 5}",
        )
        row_ids.append(row_id)

    # All should succeed with unique IDs
    assert len(row_ids) == 50
    assert len(set(row_ids)) == 50

    # All should be retrievable
    events = log.list_events(limit=100)
    assert len(events) == 50


def test_list_events_returns_all_fields(tmp_path: Path) -> None:
    """list_events() should return all fields: id, timestamp, event_type, payload, cycle_id, experiment_id."""
    db_path = tmp_path / "events.db"
    log = EventLog(str(db_path))

    log.append(
        event_type="candidate_rejected",
        payload={"reason": "below threshold"},
        cycle_id="cycle-1",
        experiment_id="exp-1",
    )

    events = log.list_events(limit=1)
    assert len(events) == 1

    event = events[0]
    assert "id" in event
    assert "timestamp" in event
    assert "event_type" in event
    assert "payload" in event
    assert "cycle_id" in event
    assert "experiment_id" in event

    assert isinstance(event["id"], int)
    assert isinstance(event["timestamp"], float)
    assert event["event_type"] == "candidate_rejected"
    assert event["payload"] == {"reason": "below threshold"}
    assert event["cycle_id"] == "cycle-1"
    assert event["experiment_id"] == "exp-1"


def test_event_log_persistence_across_instances(tmp_path: Path) -> None:
    """Events should persist and be readable across different EventLog instances."""
    db_path = tmp_path / "events.db"

    # First instance: append events
    log1 = EventLog(str(db_path))
    log1.append(event_type="eval_started", payload={"test": "persistence"})
    log1.append(event_type="eval_completed", payload={"test": "persistence2"})

    # Second instance: should read the same events
    log2 = EventLog(str(db_path))
    events = log2.list_events(limit=10)

    assert len(events) == 2
    assert events[0]["payload"]["test"] == "persistence2"
    assert events[1]["payload"]["test"] == "persistence"


def test_all_valid_event_types_are_accepted(tmp_path: Path) -> None:
    """Verify all VALID_EVENT_TYPES are actually accepted by append()."""
    db_path = tmp_path / "events.db"
    log = EventLog(str(db_path))

    # This test ensures VALID_EVENT_TYPES constant is in sync with validation logic
    expected_types = {
        "mutation_proposed",
        "eval_started",
        "eval_completed",
        "candidate_promoted",
        "candidate_rejected",
        "rollback_triggered",
        "canary_started",
        "canary_passed",
        "canary_failed",
        "budget_exceeded",
        "stall_detected",
        "human_pause",
        "human_reject",
        "human_inject",
        # AutoFix events
        "autofix_suggested",
        "autofix_applied",
        "autofix_rejected",
        # Judge Ops events
        "judge_feedback_recorded",
        "judge_drift_detected",
        "judge_version_created",
        # Context Workbench events
        "context_analyzed",
        "context_simulation_run",
        # Builder lifecycle events (bridged from EventBroker)
        "builder_task_started",
        "builder_task_completed",
        "builder_task_failed",
        "builder_session_opened",
        "builder_session_closed",
        "builder_eval_started",
        "builder_eval_completed",
        # Broadcast events (bridged from WebSocket broadcasts)
        "eval_completed_broadcast",
        "optimize_completed_broadcast",
        "optimize_pending_review_broadcast",
        "loop_cycle_broadcast",
    }

    assert VALID_EVENT_TYPES == expected_types

    # All should work without raising
    for event_type in VALID_EVENT_TYPES:
        log.append(event_type=event_type, payload={"type": event_type})

    events = log.list_events(limit=100)
    assert len(events) == len(VALID_EVENT_TYPES)
