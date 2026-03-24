"""Reliability primitives for long-running optimization loops."""

from __future__ import annotations

import json
import os
import resource
import signal
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class LoopCheckpoint:
    """Persisted loop progress used for crash recovery and resume."""

    next_cycle: int = 1
    completed_cycles: int = 0
    plateau_count: int = 0
    last_status: str = "idle"
    last_cycle_started_at: float = 0.0
    last_cycle_finished_at: float = 0.0
    metadata: dict[str, float | int | str] = field(default_factory=dict)


class LoopCheckpointStore:
    """JSON-backed checkpoint persistence with atomic writes."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> LoopCheckpoint | None:
        """Load checkpoint from disk if one exists."""
        if not self.path.exists():
            return None
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return LoopCheckpoint(**data)

    def save(self, checkpoint: LoopCheckpoint) -> None:
        """Atomically persist checkpoint state."""
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(asdict(checkpoint), indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def clear(self) -> None:
        """Remove checkpoint file from disk."""
        if self.path.exists():
            self.path.unlink()


class DeadLetterQueue:
    """SQLite dead-letter queue for failed loop/eval operations."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dead_letters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    error TEXT NOT NULL,
                    traceback TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.commit()

    def push(self, *, kind: str, payload: dict, error: str, traceback_text: str = "") -> None:
        """Persist one failed event for later triage/replay."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO dead_letters (created_at, kind, payload, error, traceback)
                VALUES (?, ?, ?, ?, ?)
                """,
                (time.time(), kind, json.dumps(payload), error, traceback_text),
            )
            conn.commit()

    def list(self, limit: int = 100) -> list[dict]:
        """Return recent dead-letter entries."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, created_at, kind, payload, error, traceback
                FROM dead_letters
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        result = []
        for row in rows:
            result.append(
                {
                    "id": row[0],
                    "created_at": row[1],
                    "kind": row[2],
                    "payload": json.loads(row[3]),
                    "error": row[4],
                    "traceback": row[5],
                }
            )
        return result

    def count(self) -> int:
        """Return total number of dead-letter entries."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT COUNT(*) FROM dead_letters").fetchone()
        return int(row[0] if row else 0)


class LoopWatchdog:
    """Heartbeat-based stall detector."""

    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = max(1.0e-6, timeout_seconds)
        self._last_beat = 0.0
        self._lock = threading.Lock()

    def beat(self, timestamp: float | None = None) -> None:
        """Record heartbeat timestamp."""
        with self._lock:
            self._last_beat = timestamp if timestamp is not None else time.time()

    def seconds_since_last_beat(self, now: float | None = None) -> float:
        """Return elapsed seconds since last heartbeat."""
        with self._lock:
            last = self._last_beat
        if last <= 0.0:
            return float("inf")
        current = now if now is not None else time.time()
        return max(0.0, current - last)

    def is_stalled(self, now: float | None = None) -> bool:
        """True when elapsed heartbeat age exceeds timeout."""
        return self.seconds_since_last_beat(now=now) > self.timeout_seconds


class LoopScheduler:
    """Compute inter-cycle wait durations for continuous/interval/cron modes."""

    def __init__(
        self,
        *,
        mode: str,
        delay_seconds: float,
        interval_minutes: float | None = None,
        cron_expression: str | None = None,
    ) -> None:
        self.mode = mode
        self.delay_seconds = max(0.0, delay_seconds)
        self.interval_minutes = interval_minutes
        self.cron_expression = cron_expression

    def seconds_until_next(
        self,
        *,
        now_epoch: float,
        cycle_started_at: float,
        cycle_finished_at: float,
    ) -> float:
        """Return wait duration (seconds) before next loop cycle."""
        del cycle_started_at
        if self.mode == "continuous":
            return self.delay_seconds

        if self.mode == "interval":
            minutes = self.interval_minutes if self.interval_minutes is not None else 1.0
            interval_seconds = max(0.0, minutes * 60.0)
            target = cycle_finished_at + interval_seconds
            return round(max(0.0, target - now_epoch), 6)

        if self.mode == "cron":
            expression = self.cron_expression or "*/5 * * * *"
            return round(_seconds_until_next_cron(expression, now_epoch), 6)

        raise ValueError(f"Unsupported scheduler mode: {self.mode}")


def _parse_cron_values(field: str, min_value: int, max_value: int) -> set[int]:
    """Parse a cron field supporting '*', '*/n', single values, and comma lists."""
    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        if part == "*":
            values.update(range(min_value, max_value + 1))
            continue
        if part.startswith("*/"):
            step = int(part[2:])
            if step <= 0:
                raise ValueError(f"Invalid cron step: {part}")
            values.update(range(min_value, max_value + 1, step))
            continue
        values.add(int(part))

    filtered = {value for value in values if min_value <= value <= max_value}
    if not filtered:
        raise ValueError(f"Invalid cron field: {field}")
    return filtered


def _matches_cron(expression: str, epoch_seconds: float) -> bool:
    minute_f, hour_f, day_f, month_f, weekday_f = expression.split()
    dt = datetime.fromtimestamp(epoch_seconds, tz=timezone.utc)

    minutes = _parse_cron_values(minute_f, 0, 59)
    hours = _parse_cron_values(hour_f, 0, 23)
    days = _parse_cron_values(day_f, 1, 31)
    months = _parse_cron_values(month_f, 1, 12)
    weekdays = _parse_cron_values(weekday_f, 0, 6)

    # Python weekday: Monday=0 .. Sunday=6. Cron commonly uses Sunday=0.
    cron_weekday = (dt.weekday() + 1) % 7

    return (
        dt.minute in minutes
        and dt.hour in hours
        and dt.day in days
        and dt.month in months
        and cron_weekday in weekdays
    )


def _seconds_until_next_cron(expression: str, now_epoch: float) -> float:
    """Find seconds until the next cron tick (minute granularity)."""
    parts = expression.split()
    if len(parts) != 5:
        raise ValueError(f"Cron expression must have 5 fields: {expression}")

    current_minute_floor = int(now_epoch // 60) * 60
    candidate = current_minute_floor + 60
    # Search up to one year ahead to avoid infinite loops on malformed expressions.
    for _ in range(60 * 24 * 366):
        if _matches_cron(expression, candidate):
            return max(0.0, float(candidate) - now_epoch)
        candidate += 60
    raise ValueError(f"Unable to find next run for cron expression: {expression}")


@dataclass
class ResourceSnapshot:
    """Runtime process resource snapshot."""

    memory_mb: float
    cpu_percent: float


class ResourceMonitor:
    """Track process memory and approximate CPU usage over time."""

    def __init__(self) -> None:
        self._last_wall = time.monotonic()
        self._last_cpu = time.process_time()

    def sample(self) -> ResourceSnapshot:
        """Collect current resource usage sample."""
        usage = resource.getrusage(resource.RUSAGE_SELF)
        # macOS reports bytes, Linux reports KiB.
        if os.uname().sysname.lower().startswith("darwin"):
            memory_mb = usage.ru_maxrss / (1024.0 * 1024.0)
        else:
            memory_mb = usage.ru_maxrss / 1024.0

        now_wall = time.monotonic()
        now_cpu = time.process_time()
        wall_delta = max(1.0e-9, now_wall - self._last_wall)
        cpu_delta = max(0.0, now_cpu - self._last_cpu)
        cpu_percent = (cpu_delta / wall_delta) * 100.0

        self._last_wall = now_wall
        self._last_cpu = now_cpu

        return ResourceSnapshot(memory_mb=round(memory_mb, 3), cpu_percent=round(cpu_percent, 3))


class GracefulShutdown:
    """Signal-aware shutdown helper that delays exit until safe boundaries."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._previous: dict[int, signal.Handlers] = {}

    @property
    def stop_requested(self) -> bool:
        """True when SIGINT/SIGTERM has been received."""
        return self._event.is_set()

    @property
    def event(self) -> threading.Event:
        """Expose stop-event for sleep interruption."""
        return self._event

    def _handler(self, signum: int, frame) -> None:  # pragma: no cover - signal frame type is platform-specific
        del signum, frame
        self._event.set()

    @contextmanager
    def install(self):
        """Install temporary SIGINT/SIGTERM handlers."""
        for sig in (signal.SIGINT, signal.SIGTERM):
            self._previous[sig] = signal.getsignal(sig)
            signal.signal(sig, self._handler)
        try:
            yield self
        finally:
            for sig, previous in self._previous.items():
                signal.signal(sig, previous)
            self._previous.clear()
