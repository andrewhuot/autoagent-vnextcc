"""Tests for enhanced replay harness with snapshot store."""

from __future__ import annotations

import json

import pytest

from core.types import ReplayMode
from evals.replay import (
    EnhancedReplayHarness,
    EnvironmentSnapshot,
    ReplayStore,
    SnapshotDiff,
    SnapshotStore,
)
from evals.side_effects import SideEffectClass, ToolContract, ToolContractRegistry


# ---------------------------------------------------------------------------
# SnapshotStore tests
# ---------------------------------------------------------------------------


def test_snapshot_store_save_and_get():
    store = SnapshotStore()
    snapshot = EnvironmentSnapshot(
        source="orders_db",
        state={"order_123": {"status": "pending", "total": 99.99}},
    )

    store.save_snapshot(snapshot)
    retrieved = store.get_snapshot(snapshot.snapshot_id)

    assert retrieved is not None
    assert retrieved.snapshot_id == snapshot.snapshot_id
    assert retrieved.source == "orders_db"
    assert retrieved.state["order_123"]["status"] == "pending"


def test_snapshot_store_get_nonexistent():
    store = SnapshotStore()
    retrieved = store.get_snapshot("does-not-exist")

    assert retrieved is None


def test_snapshot_store_list_snapshots():
    store = SnapshotStore()
    snap1 = EnvironmentSnapshot(source="db1", state={"key1": "val1"})
    snap2 = EnvironmentSnapshot(source="db2", state={"key2": "val2"})

    store.save_snapshot(snap1)
    store.save_snapshot(snap2)

    all_snapshots = store.list_snapshots(limit=10)

    # Should have at least 2
    assert len(all_snapshots) >= 2
    snapshot_ids = {s.snapshot_id for s in all_snapshots}
    assert snap1.snapshot_id in snapshot_ids
    assert snap2.snapshot_id in snapshot_ids


def test_snapshot_store_list_snapshots_by_source():
    store = SnapshotStore()
    snap1 = EnvironmentSnapshot(source="orders_db", state={"order": 1})
    snap2 = EnvironmentSnapshot(source="orders_db", state={"order": 2})
    snap3 = EnvironmentSnapshot(source="products_db", state={"product": 1})

    store.save_snapshot(snap1)
    store.save_snapshot(snap2)
    store.save_snapshot(snap3)

    orders_snapshots = store.list_snapshots(source="orders_db", limit=10)

    # Should have at least 2 from orders_db
    assert len(orders_snapshots) >= 2
    assert all(s.source == "orders_db" for s in orders_snapshots)


# ---------------------------------------------------------------------------
# EnhancedReplayHarness tests
# ---------------------------------------------------------------------------


def test_enhanced_replay_can_replay_tool():
    registry = ToolContractRegistry()
    registry.register_contract(
        ToolContract(
            tool_name="catalog",
            side_effect=SideEffectClass.read_only_external,
            replay_mode=ReplayMode.recorded_stub_with_freshness,
        )
    )

    harness = EnhancedReplayHarness(
        store=ReplayStore(),
        contract_registry=registry,
    )

    assert harness.can_replay_tool("catalog") is True
    assert harness.can_replay_tool("unknown_tool") is False


def test_enhanced_replay_capture_snapshot():
    harness = EnhancedReplayHarness(
        store=ReplayStore(),
        snapshot_store=SnapshotStore(),
    )

    state = {"order_123": {"status": "completed"}}
    snapshot = harness.capture_snapshot("orders_db", state)

    assert snapshot is not None
    assert snapshot.source == "orders_db"
    assert snapshot.state == state

    # Should be saved in store
    retrieved = harness.snapshot_store.get_snapshot(snapshot.snapshot_id)
    assert retrieved is not None


def test_enhanced_replay_compare_snapshots():
    store = SnapshotStore()
    snap1 = EnvironmentSnapshot(
        source="db",
        state={"order_123": {"status": "pending", "total": 99.99}},
    )
    snap2 = EnvironmentSnapshot(
        source="db",
        state={"order_123": {"status": "completed", "total": 99.99}},
    )

    store.save_snapshot(snap1)
    store.save_snapshot(snap2)

    harness = EnhancedReplayHarness(
        store=ReplayStore(),
        snapshot_store=store,
    )

    diff = harness.compare_snapshots(snap1.snapshot_id, snap2.snapshot_id)

    assert diff is not None
    # SnapshotDiff has changed_keys dict, not modified_keys list
    assert "order_123" in diff.changed_keys
    assert diff.added_keys == []
    assert diff.removed_keys == []


def test_enhanced_replay_compare_snapshots_missing():
    harness = EnhancedReplayHarness(
        store=ReplayStore(),
        snapshot_store=SnapshotStore(),
    )

    diff = harness.compare_snapshots("missing1", "missing2")

    assert diff is None


def test_enhanced_replay_check_freshness_no_window():
    registry = ToolContractRegistry()
    registry.register_contract(
        ToolContract(
            tool_name="catalog",
            side_effect=SideEffectClass.read_only_external,
            replay_mode=ReplayMode.recorded_stub_with_freshness,
            freshness_window_seconds=None,  # no window
        )
    )

    harness = EnhancedReplayHarness(
        store=ReplayStore(),
        contract_registry=registry,
    )

    contract = registry.get_contract("catalog")
    assert contract is not None

    # Mock recorded_io
    recorded_io = type("RecordedIO", (), {})()

    fresh = harness.check_freshness(recorded_io, contract)

    assert fresh is True  # no window = always fresh


def test_enhanced_replay_check_freshness_with_window():
    registry = ToolContractRegistry()
    registry.register_contract(
        ToolContract(
            tool_name="catalog",
            side_effect=SideEffectClass.read_only_external,
            replay_mode=ReplayMode.recorded_stub_with_freshness,
            freshness_window_seconds=3600,
        )
    )

    harness = EnhancedReplayHarness(
        store=ReplayStore(),
        contract_registry=registry,
    )

    contract = registry.get_contract("catalog")
    assert contract is not None

    # Mock recorded_io
    recorded_io = type("RecordedIO", (), {})()

    # Default implementation returns True (needs session timestamp)
    fresh = harness.check_freshness(recorded_io, contract)

    assert fresh is True
