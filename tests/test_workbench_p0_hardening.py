"""P0 hardening tests for Workbench run lifecycle, cancellation, and budgets."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.workbench import router
from builder.workbench import WorkbenchService, WorkbenchStore


def _make_client(tmp_path: Path) -> TestClient:
    """Create an isolated Workbench API client for persistence tests."""
    app = FastAPI()
    app.include_router(router)
    app.state.workbench_store = WorkbenchStore(tmp_path / "workbench.json")
    return TestClient(app)


def _parse_sse(stream_body: str) -> list[dict]:
    """Parse an SSE response body into event dictionaries."""
    events: list[dict] = []
    for block in stream_body.strip().split("\n\n"):
        event_name = "message"
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event: "):
                event_name = line[len("event: ") :].strip()
            elif line.startswith("data: "):
                data_lines.append(line[len("data: ") :])
        if data_lines:
            events.append({"event": event_name, "data": json.loads("\n".join(data_lines))})
    return events


def test_workbench_store_refuses_corrupt_json_without_resetting(tmp_path: Path) -> None:
    """A corrupt durable store should fail closed instead of erasing projects."""
    path = tmp_path / "workbench.json"
    path.write_text('{"projects": {"wb-existing": ', encoding="utf-8")
    store = WorkbenchStore(path)

    with pytest.raises(RuntimeError, match="corrupt Workbench store"):
        store.list_projects()

    assert path.read_text(encoding="utf-8").startswith('{"projects": {"wb-existing"')


def test_cancel_endpoint_marks_active_run_cancelled(tmp_path: Path) -> None:
    """Cancelling an active run should persist a terminal cancelled state."""
    store = WorkbenchStore(tmp_path / "workbench.json")
    service = WorkbenchService(store)
    project = store.create_project(brief="Build an airline support agent.")
    run = service._start_run(  # noqa: SLF001 - tests seed an active run envelope.
        project,
        brief="Build an airline support agent.",
        target="portable",
        environment="draft",
    )
    store.save_project(project)

    client = _make_client(tmp_path)
    response = client.post(
        f"/api/workbench/runs/{run['run_id']}/cancel",
        json={"project_id": project["project_id"], "reason": "operator stopped run"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "cancelled"
    assert payload["run"]["cancel_reason"] == "operator stopped run"
    assert payload["run"]["completed_at"] is not None

    snapshot = client.get(f"/api/workbench/projects/{project['project_id']}/plan").json()
    assert snapshot["build_status"] == "cancelled"
    assert snapshot["active_run"]["status"] == "cancelled"
    event_names = [event["event"] for event in snapshot["active_run"]["events"]]
    assert "run.cancel_requested" in event_names
    assert "run.cancelled" in event_names


def test_token_budget_breach_fails_stream_with_explicit_reason(tmp_path: Path) -> None:
    """A tiny token budget should terminate the stream as a budget failure."""
    client = _make_client(tmp_path)

    response = client.post(
        "/api/workbench/build/stream",
        json={
            "brief": "Build a refund support agent with policy tools.",
            "mock": True,
            "max_iterations": 1,
            "max_tokens": 1,
        },
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert events[-1]["event"] in {"turn.completed", "run.failed"}
    run_failed = next(event for event in events if event["event"] == "run.failed")
    assert run_failed["data"]["status"] == "failed"
    assert run_failed["data"]["failure_reason"] == "budget_exceeded"
    assert run_failed["data"]["budget"]["breach"]["kind"] == "tokens"


def test_snapshot_recovers_stale_inflight_run(tmp_path: Path, monkeypatch) -> None:
    """Hydration should not leave old in-flight runs pretending to be active."""
    monkeypatch.setenv("AGENTLAB_WORKBENCH_STALE_RUN_SECONDS", "1")
    store = WorkbenchStore(tmp_path / "workbench.json")
    service = WorkbenchService(store)
    project = store.create_project(brief="Build an airline support agent.")
    run = service._start_run(  # noqa: SLF001 - tests seed an interrupted run.
        project,
        brief="Build an airline support agent.",
        target="portable",
        environment="draft",
    )
    run["updated_at"] = "2000-01-01T00:00:00Z"
    project["build_status"] = "running"
    store.save_project(project)

    snapshot = service.get_plan_snapshot(project_id=project["project_id"])

    assert snapshot["build_status"] == "failed"
    assert snapshot["active_run"]["status"] == "failed"
    assert snapshot["active_run"]["failure_reason"] == "stale_interrupted"
    assert "interrupted after process recovery" in snapshot["active_run"]["error"]
    handoff = snapshot["active_run"]["handoff"]
    assert handoff["run_id"] == run["run_id"]
    assert handoff["failure_reason"] == "stale_interrupted"
    assert handoff["recovery"]["reason"] == "stale_interrupted"
    assert "interrupted" in handoff["next_action"].lower()
    assert snapshot["harness_state"]["latest_handoff"]["run_id"] == run["run_id"]
    event_names = [event["event"] for event in snapshot["active_run"]["events"]]
    assert "run.recovered" in event_names


def test_stream_events_include_telemetry_and_mock_mode_metadata(tmp_path: Path) -> None:
    """Run events should be traceable and honest about mock execution."""
    client = _make_client(tmp_path)

    response = client.post(
        "/api/workbench/build/stream",
        json={
            "brief": "Build an M&A agent that evaluates acquisition targets.",
            "mock": True,
            "max_iterations": 1,
        },
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    first_payload = events[0]["data"]
    assert first_payload["execution_mode"] == "mock"
    assert first_payload["provider"] == "mock"
    assert first_payload["model"] == "mock-workbench"
    assert first_payload["telemetry"]["run_id"] == first_payload["run_id"]
    assert first_payload["telemetry"]["phase"] in {"queued", "planning"}

    terminal = events[-1]["data"]
    assert terminal["run"]["execution"]["mode"] == "mock"
    assert terminal["run"]["telemetry_summary"]["provider"] == "mock"
    assert terminal["run"]["budget"]["limits"]["max_iterations"] == 1
