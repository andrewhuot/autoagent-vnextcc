"""Tests for long-running loop reliability primitives."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from optimizer.reliability import (
    DeadLetterQueue,
    LoopCheckpoint,
    LoopCheckpointStore,
    LoopScheduler,
    LoopWatchdog,
)


def test_checkpoint_store_round_trip(tmp_path) -> None:
    """Checkpoint state should persist and reload across process restarts."""
    store = LoopCheckpointStore(str(tmp_path / "checkpoint.json"))
    checkpoint = LoopCheckpoint(
        next_cycle=8,
        completed_cycles=7,
        plateau_count=2,
        last_status="running",
    )

    store.save(checkpoint)
    loaded = store.load()

    assert loaded is not None
    assert loaded.next_cycle == 8
    assert loaded.completed_cycles == 7
    assert loaded.plateau_count == 2


def test_dead_letter_queue_persists_failures(tmp_path) -> None:
    """Failed loop/eval events should be retained in dead-letter storage."""
    dlq = DeadLetterQueue(str(tmp_path / "dead_letters.db"))
    dlq.push(kind="loop_cycle", payload={"cycle": 3}, error="timeout")

    items = dlq.list(limit=10)

    assert len(items) == 1
    assert items[0]["kind"] == "loop_cycle"
    assert items[0]["error"] == "timeout"


def test_watchdog_reports_stall_after_timeout() -> None:
    """Watchdog should mark stalled when heartbeat is overdue."""
    watchdog = LoopWatchdog(timeout_seconds=0.05)
    watchdog.beat()
    time.sleep(0.08)

    assert watchdog.is_stalled() is True


def test_interval_scheduler_waits_for_configured_interval() -> None:
    """Interval scheduler should compute wait time from interval minutes."""
    scheduler = LoopScheduler(mode="interval", delay_seconds=0.0, interval_minutes=0.1)

    wait_seconds = scheduler.seconds_until_next(now_epoch=100.0, cycle_started_at=100.0, cycle_finished_at=100.0)

    assert wait_seconds == 6.0


def test_cron_scheduler_matches_next_minute_boundary() -> None:
    """Cron scheduler should support simple minute-step expressions."""
    scheduler = LoopScheduler(mode="cron", delay_seconds=0.0, cron_expression="*/5 * * * *")

    # 2026-03-23T12:02:10Z -> next 5-minute mark at 12:05:00 (170 seconds)
    now_epoch = datetime(2026, 3, 23, 12, 2, 10, tzinfo=timezone.utc).timestamp()
    wait_seconds = scheduler.seconds_until_next(
        now_epoch=now_epoch,
        cycle_started_at=now_epoch,
        cycle_finished_at=now_epoch,
    )

    assert wait_seconds == 170.0
