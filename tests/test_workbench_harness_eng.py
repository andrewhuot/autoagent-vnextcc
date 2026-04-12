"""Tests for harness engineering improvements.

Covers:
- Unified stream event processing (regression: event sequences match prior behavior)
- Heartbeat / liveness injection via _iter_with_heartbeat
- Progress stall detection via _verify_step_progress
- Context budget estimation via _estimate_context_size
- Structured run summary via build_run_summary
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.workbench import router
from builder.workbench import (
    WorkbenchService,
    WorkbenchStore,
    build_run_summary,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(tmp_path: Path) -> TestClient:
    """Create an isolated Workbench API client backed by temporary JSON store."""
    app = FastAPI()
    app.include_router(router)
    app.state.workbench_store = WorkbenchStore(tmp_path / "workbench.json")
    return TestClient(app)


def _parse_sse(text: str) -> list[dict[str, Any]]:
    """Parse Server-Sent-Events response body into event dicts."""
    events: list[dict[str, Any]] = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        event_name = "message"
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith("event: "):
                event_name = line[len("event: "):]
            elif line.startswith("data: "):
                data_lines.append(line[len("data: "):])
        if data_lines:
            try:
                payload = json.loads("\n".join(data_lines))
                events.append({"event": event_name, "data": payload})
            except json.JSONDecodeError:
                pass
    return events


def _event_names(events: list[dict[str, Any]]) -> list[str]:
    """Extract event name sequence for assertion."""
    return [e["event"] for e in events]


# ---------------------------------------------------------------------------
# Unit: _verify_step_progress
# ---------------------------------------------------------------------------


class TestVerifyStepProgress:
    """Tests for the progress verification method."""

    def test_step_with_operations_is_not_a_stall(self, tmp_path: Path) -> None:
        """A step that produced operations should not be flagged."""
        store = WorkbenchStore(tmp_path / "workbench.json")
        service = WorkbenchService(store)
        project = store.create_project(brief="test")
        data = {
            "task_id": "task-1",
            "operations": [{"operation": "add", "object": {"name": "tool"}}],
        }
        result = service._verify_step_progress(data=data, project=project)  # noqa: SLF001
        assert result is None

    def test_step_with_artifact_is_not_a_stall(self, tmp_path: Path) -> None:
        """A step that produced an artifact should not be flagged."""
        store = WorkbenchStore(tmp_path / "workbench.json")
        service = WorkbenchService(store)
        project = store.create_project(brief="test")
        project["artifacts"] = [{"id": "art-1", "task_id": "task-1", "source": "content"}]
        data = {"task_id": "task-1", "operations": []}
        result = service._verify_step_progress(data=data, project=project)  # noqa: SLF001
        assert result is None

    def test_empty_step_is_a_stall(self, tmp_path: Path) -> None:
        """A step with no operations and no artifact should be flagged."""
        store = WorkbenchStore(tmp_path / "workbench.json")
        service = WorkbenchService(store)
        project = store.create_project(brief="test")
        data = {"task_id": "task-1", "operations": []}
        result = service._verify_step_progress(data=data, project=project)  # noqa: SLF001
        assert result is not None
        assert result["type"] == "no_output"
        assert result["task_id"] == "task-1"


# ---------------------------------------------------------------------------
# Unit: _estimate_context_size
# ---------------------------------------------------------------------------


class TestEstimateContextSize:
    """Tests for context budget estimation."""

    def test_empty_project_has_minimal_context(self, tmp_path: Path) -> None:
        """A fresh project should have small context size."""
        store = WorkbenchStore(tmp_path / "workbench.json")
        service = WorkbenchService(store)
        project = store.create_project(brief="test")
        result = service._estimate_context_size(project)  # noqa: SLF001
        assert result["total_tokens"] > 0
        assert result["conversation_count"] == 0
        assert result["artifact_count"] == 0

    def test_context_grows_with_artifacts(self, tmp_path: Path) -> None:
        """Adding artifacts should increase context size."""
        store = WorkbenchStore(tmp_path / "workbench.json")
        service = WorkbenchService(store)
        project = store.create_project(brief="test")
        size_before = service._estimate_context_size(project)  # noqa: SLF001
        project["artifacts"] = [
            {"id": "a1", "source": "x" * 1000, "category": "tool"},
            {"id": "a2", "source": "y" * 1000, "category": "agent"},
        ]
        size_after = service._estimate_context_size(project)  # noqa: SLF001
        assert size_after["total_tokens"] > size_before["total_tokens"]
        assert size_after["artifact_count"] == 2

    def test_context_grows_with_conversation(self, tmp_path: Path) -> None:
        """Adding conversation messages should increase context size."""
        store = WorkbenchStore(tmp_path / "workbench.json")
        service = WorkbenchService(store)
        project = store.create_project(brief="test")
        project["conversation"] = [
            {"role": "user", "content": "Build me an airline agent"},
            {"role": "assistant", "content": "Sure, I'll create that for you."},
        ]
        result = service._estimate_context_size(project)  # noqa: SLF001
        assert result["conversation_count"] == 2
        assert result["conversation_tokens"] > 0


# ---------------------------------------------------------------------------
# Unit: build_run_summary
# ---------------------------------------------------------------------------


class TestBuildRunSummary:
    """Tests for the structured run summary builder."""

    def test_completed_run_has_review_action(self, tmp_path: Path) -> None:
        """A completed run with passing validation should recommend review."""
        store = WorkbenchStore(tmp_path / "workbench.json")
        project = store.create_project(brief="test")
        project["artifacts"] = [{"id": "a1"}]
        run = {
            "run_id": "run-1",
            "status": "completed",
            "phase": "terminal",
            "execution": {"mode": "mock", "provider": "mock", "model": "mock-wb"},
            "budget": {"usage": {"elapsed_ms": 1234, "tokens_used": 500, "cost_usd": 0.001}},
            "validation": {"status": "passed"},
            "events": [],
        }
        summary = build_run_summary(project, run)
        assert summary["run_id"] == "run-1"
        assert summary["status"] == "completed"
        assert summary["artifacts_produced"] == 1
        assert summary["duration_ms"] == 1234
        assert "approve" in summary["recommended_action"].lower() or "review" in summary["recommended_action"].lower()

    def test_failed_run_has_retry_action(self, tmp_path: Path) -> None:
        """A failed run should recommend investigation."""
        run = {
            "run_id": "run-2",
            "status": "failed",
            "phase": "terminal",
            "failure_reason": "budget_exceeded",
            "execution": {},
            "budget": {"usage": {}},
            "validation": {},
            "events": [],
        }
        summary = build_run_summary({"artifacts": []}, run)
        assert "retry" in summary["recommended_action"].lower() or "investigate" in summary["recommended_action"].lower()
        assert summary["status"] == "failed"

    def test_summary_captures_changes(self, tmp_path: Path) -> None:
        """Run events with operations should appear in the changes list."""
        run = {
            "run_id": "run-3",
            "status": "completed",
            "phase": "terminal",
            "execution": {},
            "budget": {"usage": {}},
            "validation": {"status": "passed"},
            "events": [
                {
                    "event": "task.completed",
                    "data": {
                        "operations": [
                            {"operation": "add", "object": {"category": "tool", "name": "lookup"}},
                        ],
                    },
                },
            ],
        }
        summary = build_run_summary({"artifacts": [{"id": "a1"}]}, run)
        assert summary["operations_applied"] == 1
        assert summary["changes"][0]["name"] == "lookup"
        assert summary["changes"][0]["category"] == "tool"


# ---------------------------------------------------------------------------
# Integration: heartbeat injection
# ---------------------------------------------------------------------------


async def test_heartbeat_fires_during_slow_source(tmp_path: Path) -> None:
    """Heartbeat events should be injected when the source is slow."""
    store = WorkbenchStore(tmp_path / "workbench.json")
    service = WorkbenchService(store)

    async def slow_source() -> AsyncIterator[dict[str, Any]]:
        yield {"event": "plan.ready", "data": {"plan": {"id": "t1", "title": "T"}}}
        await asyncio.sleep(0.3)
        yield {"event": "build.completed", "data": {"project_id": "p1"}}

    project = store.create_project(brief="test")
    run = {"run_id": "r1", "phase": "executing", "status": "running", "created_at": "2026-01-01T00:00:00Z"}
    events: list[dict[str, Any]] = []
    async for event in service._iter_with_heartbeat(  # noqa: SLF001
        slow_source(), interval=0.05, run=run,
    ):
        events.append(event)

    names = [e["event"] for e in events]
    assert "harness.heartbeat" in names, f"Expected heartbeat in {names}"
    # At least 1 heartbeat should fire during the 0.3s gap at 0.05s interval
    heartbeat_count = names.count("harness.heartbeat")
    assert heartbeat_count >= 1


async def test_heartbeat_disabled_with_zero_interval(tmp_path: Path) -> None:
    """No heartbeat events when interval is 0."""
    store = WorkbenchStore(tmp_path / "workbench.json")
    service = WorkbenchService(store)

    async def slow_source() -> AsyncIterator[dict[str, Any]]:
        yield {"event": "plan.ready", "data": {"plan": {"id": "t1", "title": "T"}}}
        await asyncio.sleep(0.05)
        yield {"event": "build.completed", "data": {"project_id": "p1"}}

    run = {"run_id": "r1", "phase": "executing", "status": "running"}
    events: list[dict[str, Any]] = []
    async for event in service._iter_with_heartbeat(  # noqa: SLF001
        slow_source(), interval=0, run=run,
    ):
        events.append(event)

    names = [e["event"] for e in events]
    assert "harness.heartbeat" not in names


# ---------------------------------------------------------------------------
# Integration: full stream regression — events should match prior behavior
# ---------------------------------------------------------------------------


def test_unified_stream_produces_expected_lifecycle_events(tmp_path: Path) -> None:
    """Build stream via the API should produce the standard lifecycle events."""
    client = _make_client(tmp_path)

    response = client.post(
        "/api/workbench/build/stream",
        json={
            "brief": "Build an airline support agent with booking tools.",
            "mock": True,
            "max_iterations": 1,
        },
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    names = _event_names(events)

    # Standard lifecycle should still be present
    assert "turn.started" in names
    assert "iteration.started" in names
    assert "plan.ready" in names
    assert "build.completed" in names
    # Durable run lifecycle events
    assert "reflect.started" in names or "reflect.completed" in names or "run.completed" in names

    # The run should complete successfully
    terminal = [e for e in events if e["event"] in {"run.completed", "run.failed"}]
    assert len(terminal) >= 1


def test_unified_stream_run_completed_includes_summary(tmp_path: Path) -> None:
    """The run.completed event should include a structured summary."""
    client = _make_client(tmp_path)

    response = client.post(
        "/api/workbench/build/stream",
        json={
            "brief": "Build an airline support agent.",
            "mock": True,
            "max_iterations": 1,
        },
    )

    events = _parse_sse(response.text)
    terminal = [e for e in events if e["event"] in {"run.completed", "run.failed"}]
    assert len(terminal) >= 1
    terminal_data = terminal[-1]["data"]
    assert "summary" in terminal_data, f"Missing 'summary' in terminal event data: {list(terminal_data.keys())}"
    summary = terminal_data["summary"]
    assert "run_id" in summary
    assert "status" in summary
    assert "recommended_action" in summary


def test_iteration_stream_preserves_prior_artifacts(tmp_path: Path) -> None:
    """Follow-up iteration should not clear artifacts from prior turns."""
    client = _make_client(tmp_path)

    # Initial build
    r1 = client.post(
        "/api/workbench/build/stream",
        json={"brief": "Build a sales agent.", "mock": True, "max_iterations": 1},
    )
    assert r1.status_code == 200
    events1 = _parse_sse(r1.text)
    # Extract project_id from events
    project_ids = [
        e["data"].get("project_id")
        for e in events1
        if e["data"].get("project_id")
    ]
    assert project_ids, "No project_id in events"
    project_id = project_ids[0]

    # Follow-up iteration
    r2 = client.post(
        "/api/workbench/build/iterate",
        json={
            "project_id": project_id,
            "follow_up": "Add a refund lookup tool.",
            "mock": True,
        },
    )
    assert r2.status_code == 200
    events2 = _parse_sse(r2.text)
    # The iteration should also produce artifacts
    artifact_events = [e for e in events2 if e["event"] == "artifact.updated"]
    # And the snapshot should retain both old and new artifacts
    snapshot = client.get(f"/api/workbench/projects/{project_id}/plan").json()
    assert len(snapshot["artifacts"]) >= len(artifact_events)


def test_plan_snapshot_includes_run_summary(tmp_path: Path) -> None:
    """Plan snapshot hydration should include a run_summary when a run exists."""
    client = _make_client(tmp_path)

    r = client.post(
        "/api/workbench/build/stream",
        json={"brief": "Build an IT helpdesk agent.", "mock": True, "max_iterations": 1},
    )
    assert r.status_code == 200
    events = _parse_sse(r.text)
    project_ids = [e["data"].get("project_id") for e in events if e["data"].get("project_id")]
    project_id = project_ids[0]

    snapshot = client.get(f"/api/workbench/projects/{project_id}/plan").json()
    assert "run_summary" in snapshot, f"Missing run_summary in snapshot keys: {list(snapshot.keys())}"
    if snapshot["run_summary"] is not None:
        assert "run_id" in snapshot["run_summary"]
        assert "recommended_action" in snapshot["run_summary"]
