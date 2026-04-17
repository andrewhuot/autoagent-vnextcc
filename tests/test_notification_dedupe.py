"""Tests for C9 — notification dedupe + continuous-loop wiring (R6.4 / R6.5).

Covers:

1. ``NotificationDedupeStore`` SQLite-backed dedupe window semantics.
2. ``NotificationManager.send(..., signature=...)`` suppresses duplicate
   emissions within a 1-hour window.
3. ``ContinuousOrchestrator`` now emits ``regression_detected``,
   ``improvement_queued``, and ``continuous_cycle_failed`` events through
   a wired ``NotificationManager``.
4. ``VALID_EVENT_TYPES`` includes the four new names.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from cli.workspace import AgentLabWorkspace
from optimizer.improvement_lineage import ImprovementLineageStore


# ---------------------------------------------------------------------------
# Fixtures — reused from test_continuous_orchestrator style.
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path) -> AgentLabWorkspace:
    ws = AgentLabWorkspace.create(
        root=tmp_path / "wk",
        name="dedupe-test",
        template="blank",
        agent_name="Dedupe",
        platform="mock",
    )
    ws.ensure_structure()
    cfg = ws.configs_dir / "v001.yaml"
    cfg.write_text("model: mock\nprompts:\n  root: hi\n", encoding="utf-8")
    ws.metadata.active_config_version = 1
    ws.metadata.active_config_file = "v001.yaml"
    ws.save_metadata()
    return ws


@pytest.fixture
def trace_source(tmp_path: Path) -> Path:
    src = tmp_path / "traces"
    src.mkdir()
    (src / "trace_a.jsonl").write_text(
        json.dumps({"trace_id": "t1", "input": "hi"}) + "\n",
        encoding="utf-8",
    )
    return src


@dataclass
class _FakeEvalResult:
    run_id: str
    composite_score: float
    case_count: int


class _FakeEvalRunner:
    def __init__(self, scores: list[float]) -> None:
        self._scores = list(scores)
        self._i = 0

    def score_cases(self, cases: list[dict[str, Any]], *, config: Any = None) -> _FakeEvalResult:
        score = self._scores[self._i]
        self._i += 1
        return _FakeEvalResult(
            run_id=f"run_{self._i}",
            composite_score=score,
            case_count=len(cases),
        )


@dataclass
class _FakeImproveRunResult:
    attempt_id: str | None
    config_path: str | None
    eval_run_id: str | None
    status: str


class _ClockStub:
    """Mock clock that returns a fixed ``datetime`` — settable between calls."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def advance(self, seconds: int) -> None:
        self.now = self.now + timedelta(seconds=seconds)

    def __call__(self) -> datetime:
        return self.now


# ---------------------------------------------------------------------------
# Test G — VALID_EVENT_TYPES includes the four new names.
# ---------------------------------------------------------------------------


def test_valid_event_types_includes_new_names() -> None:
    from notifications.manager import VALID_EVENT_TYPES

    assert "regression_detected" in VALID_EVENT_TYPES
    assert "improvement_queued" in VALID_EVENT_TYPES
    assert "continuous_cycle_failed" in VALID_EVENT_TYPES
    assert "drift_detected" in VALID_EVENT_TYPES


# ---------------------------------------------------------------------------
# NotificationDedupeStore unit tests.
# ---------------------------------------------------------------------------


def test_dedupe_store_first_send_not_within_window(tmp_path: Path) -> None:
    from optimizer.notification_dedupe import NotificationDedupeStore

    store = NotificationDedupeStore(db_path=tmp_path / "log.db")
    now = datetime(2026, 4, 17, 12, 0, 0)
    assert (
        store.was_sent_within(
            "regression_detected",
            "wk",
            "sig1",
            window_seconds=3600,
            now=now,
        )
        is False
    )


def test_dedupe_store_records_and_suppresses(tmp_path: Path) -> None:
    from optimizer.notification_dedupe import NotificationDedupeStore

    store = NotificationDedupeStore(db_path=tmp_path / "log.db")
    now = datetime(2026, 4, 17, 12, 0, 0)
    store.record_sent("regression_detected", "wk", "sig1", sent_at=now)

    assert store.was_sent_within(
        "regression_detected",
        "wk",
        "sig1",
        window_seconds=3600,
        now=now + timedelta(minutes=30),
    )

    # Same key past the window — no longer suppressed.
    assert not store.was_sent_within(
        "regression_detected",
        "wk",
        "sig1",
        window_seconds=3600,
        now=now + timedelta(minutes=61),
    )


def test_dedupe_store_distinguishes_workspace_and_signature(tmp_path: Path) -> None:
    from optimizer.notification_dedupe import NotificationDedupeStore

    store = NotificationDedupeStore(db_path=tmp_path / "log.db")
    now = datetime(2026, 4, 17, 12, 0, 0)
    store.record_sent("regression_detected", "wk_a", "sig1", sent_at=now)

    assert not store.was_sent_within(
        "regression_detected",
        "wk_b",
        "sig1",
        window_seconds=3600,
        now=now,
    )
    assert not store.was_sent_within(
        "regression_detected",
        "wk_a",
        "sig2",
        window_seconds=3600,
        now=now,
    )


# ---------------------------------------------------------------------------
# Fake channel that records every send(...) call.
# ---------------------------------------------------------------------------


class _RecordingChannel:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def send(self, config: dict[str, Any], event_type: str, payload: dict[str, Any]) -> None:
        self.calls.append((event_type, dict(payload)))


def _build_manager_with_fake(
    tmp_path: Path,
    channel: _RecordingChannel,
    *,
    events: list[str] | None = None,
) -> Any:
    """Build a NotificationManager with a webhook channel replaced by the fake."""
    from notifications.manager import NotificationManager

    events = events or [
        "regression_detected",
        "improvement_queued",
        "continuous_cycle_failed",
    ]
    mgr = NotificationManager(db_path=tmp_path / "notif.db")
    mgr.webhook_channel = channel  # type: ignore[assignment]
    mgr.register_webhook("https://example.com/hook", events=events)
    return mgr


# ---------------------------------------------------------------------------
# Test A — two identical emissions 30 min apart → 1 channel call.
# Test B — third emission 61 min after the first → 2 channel calls total.
# ---------------------------------------------------------------------------


def test_manager_send_suppresses_within_hour(tmp_path: Path) -> None:
    from optimizer.notification_dedupe import NotificationDedupeStore

    channel = _RecordingChannel()
    mgr = _build_manager_with_fake(tmp_path, channel)
    dedupe = NotificationDedupeStore(db_path=tmp_path / "dedupe.db")
    mgr.dedupe_store = dedupe

    clock = _ClockStub(datetime(2026, 4, 17, 12, 0, 0))

    sent_1 = mgr.send(
        "regression_detected",
        {"workspace": "wk", "value": 1},
        workspace="wk",
        signature="sig1",
        clock=clock,
    )
    clock.advance(30 * 60)  # 30 minutes
    sent_2 = mgr.send(
        "regression_detected",
        {"workspace": "wk", "value": 2},
        workspace="wk",
        signature="sig1",
        clock=clock,
    )

    assert sent_1 is True
    assert sent_2 is False  # suppressed
    assert len(channel.calls) == 1

    # Third emission 61 min after the first (31 min past the second).
    clock.advance(31 * 60)
    sent_3 = mgr.send(
        "regression_detected",
        {"workspace": "wk", "value": 3},
        workspace="wk",
        signature="sig1",
        clock=clock,
    )
    assert sent_3 is True
    assert len(channel.calls) == 2


def test_manager_send_different_signature_not_suppressed(tmp_path: Path) -> None:
    from optimizer.notification_dedupe import NotificationDedupeStore

    channel = _RecordingChannel()
    mgr = _build_manager_with_fake(tmp_path, channel)
    mgr.dedupe_store = NotificationDedupeStore(db_path=tmp_path / "dedupe.db")

    clock = _ClockStub(datetime(2026, 4, 17, 12, 0, 0))

    mgr.send(
        "regression_detected",
        {"workspace": "wk"},
        workspace="wk",
        signature="sig_a",
        clock=clock,
    )
    clock.advance(5 * 60)
    mgr.send(
        "regression_detected",
        {"workspace": "wk"},
        workspace="wk",
        signature="sig_b",
        clock=clock,
    )
    # Different workspace as well.
    mgr.send(
        "regression_detected",
        {"workspace": "other"},
        workspace="other",
        signature="sig_a",
        clock=clock,
    )
    assert len(channel.calls) == 3


def test_manager_send_improvement_queued_distinct_attempts(tmp_path: Path) -> None:
    from optimizer.notification_dedupe import NotificationDedupeStore

    channel = _RecordingChannel()
    mgr = _build_manager_with_fake(tmp_path, channel)
    mgr.dedupe_store = NotificationDedupeStore(db_path=tmp_path / "dedupe.db")

    clock = _ClockStub(datetime(2026, 4, 17, 12, 0, 0))

    mgr.send(
        "improvement_queued",
        {"attempt_id": "att_a"},
        workspace="wk",
        signature="att_a",
        clock=clock,
    )
    mgr.send(
        "improvement_queued",
        {"attempt_id": "att_b"},
        workspace="wk",
        signature="att_b",
        clock=clock,
    )
    assert len(channel.calls) == 2


def test_manager_send_without_signature_legacy_behavior(tmp_path: Path) -> None:
    """Back-compat: callers that don't pass signature must keep working."""
    channel = _RecordingChannel()
    mgr = _build_manager_with_fake(tmp_path, channel)

    # Legacy call — positional + no dedupe kwargs.
    mgr.send("regression_detected", {"workspace": "wk"})
    mgr.send("regression_detected", {"workspace": "wk"})
    assert len(channel.calls) == 2


# ---------------------------------------------------------------------------
# Test F — missing dedupe store → first send creates the db file.
# ---------------------------------------------------------------------------


def test_dedupe_store_creates_db_on_first_use(tmp_path: Path) -> None:
    from optimizer.notification_dedupe import NotificationDedupeStore

    db_path = tmp_path / "nested" / "log.db"
    assert not db_path.exists()
    store = NotificationDedupeStore(db_path=db_path)
    store.record_sent(
        "regression_detected",
        "wk",
        "sig",
        sent_at=datetime(2026, 4, 17, 12, 0, 0),
    )
    assert db_path.exists()


# ---------------------------------------------------------------------------
# Test E — orchestrator smoke: regressed cycle fires regression_detected
#                              + improvement_queued.
# ---------------------------------------------------------------------------


def test_orchestrator_emits_regression_and_improvement_events(
    workspace: AgentLabWorkspace, trace_source: Path, tmp_path: Path
) -> None:
    from optimizer.continuous import ContinuousOrchestrator
    from optimizer.notification_dedupe import NotificationDedupeStore

    channel = _RecordingChannel()
    mgr = _build_manager_with_fake(tmp_path, channel)
    mgr.dedupe_store = NotificationDedupeStore(db_path=tmp_path / "dedupe.db")

    lineage = ImprovementLineageStore(db_path=str(tmp_path / "lineage.db"))
    for i in range(3):
        lineage.record_eval_run(
            eval_run_id=f"prior_{i}",
            attempt_id="",
            composite_score=0.9,
            case_count=2,
        )
    fake_eval = _FakeEvalRunner(scores=[0.5])

    def fake_convert(paths: list[Path], **_: Any) -> list[dict[str, Any]]:
        return [{"case_id": p.stem} for p in paths]

    fake_result = _FakeImproveRunResult(
        attempt_id="att_42",
        config_path=None,
        eval_run_id="eval_run_1",
        status="ok",
    )

    clock = _ClockStub(datetime(2026, 4, 17, 12, 0, 0))

    with patch("optimizer.continuous._convert_trace_files_to_cases", side_effect=fake_convert), \
         patch("optimizer.continuous._build_eval_runner", return_value=fake_eval), \
         patch(
             "optimizer.continuous._run_improve_run_in_process",
             return_value=fake_result,
         ):
        orch = ContinuousOrchestrator(
            workspace,
            trace_source=trace_source,
            lineage_store=lineage,
            notification_manager=mgr,
            clock=clock,
        )
        result = orch.run_once()

    assert result.regressed is True
    assert result.improvement_queued is True

    event_types_sent = [c[0] for c in channel.calls]
    assert "regression_detected" in event_types_sent
    assert "improvement_queued" in event_types_sent


def test_orchestrator_emits_continuous_cycle_failed_on_exception(
    workspace: AgentLabWorkspace, trace_source: Path, tmp_path: Path
) -> None:
    from optimizer.continuous import ContinuousOrchestrator
    from optimizer.notification_dedupe import NotificationDedupeStore

    channel = _RecordingChannel()
    mgr = _build_manager_with_fake(tmp_path, channel)
    mgr.dedupe_store = NotificationDedupeStore(db_path=tmp_path / "dedupe.db")

    lineage = ImprovementLineageStore(db_path=str(tmp_path / "lineage.db"))

    def boom(_paths: list[Path], **_: Any) -> list[dict[str, Any]]:
        raise RuntimeError("kaboom line 1\nignored line 2")

    fake_eval = _FakeEvalRunner(scores=[0.9])
    clock = _ClockStub(datetime(2026, 4, 17, 12, 0, 0))

    with patch("optimizer.continuous._convert_trace_files_to_cases", side_effect=boom), \
         patch("optimizer.continuous._build_eval_runner", return_value=fake_eval), \
         patch("optimizer.continuous._run_improve_run_in_process"):
        orch = ContinuousOrchestrator(
            workspace,
            trace_source=trace_source,
            lineage_store=lineage,
            notification_manager=mgr,
            clock=clock,
        )
        result = orch.run_once()

    assert result.error is not None
    event_types_sent = [c[0] for c in channel.calls]
    assert "continuous_cycle_failed" in event_types_sent


def test_orchestrator_regression_dedupes_across_two_cycles(
    workspace: AgentLabWorkspace, trace_source: Path, tmp_path: Path
) -> None:
    """Invariant: two consecutive regressed cycles with identical profile
    must NOT alert twice for regression_detected."""
    from optimizer.continuous import ContinuousOrchestrator
    from optimizer.notification_dedupe import NotificationDedupeStore

    channel = _RecordingChannel()
    mgr = _build_manager_with_fake(tmp_path, channel)
    mgr.dedupe_store = NotificationDedupeStore(db_path=tmp_path / "dedupe.db")

    lineage = ImprovementLineageStore(db_path=str(tmp_path / "lineage.db"))
    for i in range(3):
        lineage.record_eval_run(
            eval_run_id=f"prior_{i}",
            attempt_id="",
            composite_score=0.9,
            case_count=2,
        )

    fake_eval = _FakeEvalRunner(scores=[0.5, 0.5])

    def fake_convert(paths: list[Path], **_: Any) -> list[dict[str, Any]]:
        return [{"case_id": p.stem} for p in paths]

    fake_result = _FakeImproveRunResult(
        attempt_id="att_a", config_path=None, eval_run_id=None, status="ok"
    )

    clock = _ClockStub(datetime(2026, 4, 17, 12, 0, 0))

    def _touch_trace() -> None:
        # Tap a new mtime so the second cycle ingests.
        p = trace_source / "trace_a.jsonl"
        st = p.stat()
        import os
        os.utime(p, (st.st_atime, st.st_mtime + 60))

    with patch("optimizer.continuous._convert_trace_files_to_cases", side_effect=fake_convert), \
         patch("optimizer.continuous._build_eval_runner", return_value=fake_eval), \
         patch("optimizer.continuous._run_improve_run_in_process", return_value=fake_result):
        orch = ContinuousOrchestrator(
            workspace,
            trace_source=trace_source,
            lineage_store=lineage,
            notification_manager=mgr,
            clock=clock,
        )
        orch.run_once()
        _touch_trace()
        clock.advance(5 * 60)  # 5 minutes later
        orch.run_once()

    regression_calls = [c for c in channel.calls if c[0] == "regression_detected"]
    assert len(regression_calls) == 1, (
        "regression_detected must dedupe across cycles within 1h window"
    )
