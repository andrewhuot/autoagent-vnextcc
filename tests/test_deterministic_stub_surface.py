"""Tests that the UI clearly surfaces when workers are running stubs.

Before this change, the deterministic fallback produced a "worker
completed" transcript line that looked identical to a live LLM result.
Operators lost hours diagnosing "the CLI does nothing" when in fact the
runtime was happily running the stub. The following tests lock in:

- a degradation event fires on the first plan execution when the
  runtime is running deterministic stubs by auto-selection,
- transcript rendering annotates each stub worker with a ``[stub]``
  marker and a leading warning line,
- ``WorkbenchAgentRuntime`` exposes the degradation reason so the
  banner / status bar can also surface it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from builder.coordinator_runtime import CoordinatorWorkerRuntime
from builder.events import BuilderEventType, EventBroker
from builder.orchestrator import BuilderOrchestrator
from builder.store import BuilderStore
from builder.worker_mode import WorkerMode
from cli.workbench_app.coordinator_session import CoordinatorSession
from cli.workbench_app.runtime import WorkbenchAgentRuntime


def _clear_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "AGENTLAB_WORKER_MODE",
    ):
        monkeypatch.delenv(name, raising=False)


def test_runtime_reports_degradation_reason_for_missing_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_credentials(monkeypatch)
    monkeypatch.chdir(tmp_path)  # no agentlab.yaml nearby

    store = BuilderStore(db_path=str(tmp_path / "builder.db"))
    runtime = CoordinatorWorkerRuntime(
        store=store,
        orchestrator=BuilderOrchestrator(store=store),
        events=EventBroker(),
    )

    assert runtime.worker_mode is WorkerMode.DETERMINISTIC
    reason = runtime.worker_mode_degraded_reason
    assert reason is not None
    assert "no worker model configured" in reason


def test_degraded_event_published_on_first_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_credentials(monkeypatch)
    monkeypatch.chdir(tmp_path)

    store = BuilderStore(db_path=str(tmp_path / "builder.db"))
    events = EventBroker()
    session = CoordinatorSession(
        store=store,
        orchestrator=BuilderOrchestrator(store=store),
        events=events,
    )

    plan = session.plan(
        "Build a support agent",
        verb="build",
        context={"permission_mode": "default"},
    )
    emitted = tuple(session.execute(str(plan["plan_id"])))

    degraded_events = [
        evt
        for evt in emitted
        if evt.event_type == BuilderEventType.COORDINATOR_WORKER_MODE_DEGRADED
    ]
    assert len(degraded_events) == 1
    payload = degraded_events[0].payload
    assert payload["mode"] == WorkerMode.DETERMINISTIC.value
    assert "no worker model configured" in payload["reason"]


def test_transcript_flags_stub_workers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_credentials(monkeypatch)
    monkeypatch.chdir(tmp_path)

    runtime = WorkbenchAgentRuntime(db_path=str(tmp_path / "builder.db"))
    result = runtime.process_turn("Build a support agent")

    joined = "\n".join(result.transcript_lines)
    assert "Worker mode: deterministic stub" in joined
    assert "[stub]" in joined


def test_workbench_runtime_exposes_degraded_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_credentials(monkeypatch)
    monkeypatch.chdir(tmp_path)

    runtime = WorkbenchAgentRuntime(db_path=str(tmp_path / "builder.db"))
    assert runtime.worker_mode is WorkerMode.DETERMINISTIC
    assert runtime.worker_mode_degraded_reason is not None
